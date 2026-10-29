"""Per-stage content builders + the single ingestion entrypoint.

Every ingestion call MUST pass rfq_id, version, and source/stage explicitly
(plan §0.C) -- version is never inferred from a DuckDB table, since several
of them (bom_structure_items, processed_bom_items, update_alternatives,
gerber_geometry, gerber_checklist) have no version column at all and cannot
be trusted as a version signal.

Content builders only produce TEXT + a CITATION constructed from the real
row/file being read (plan §0.D) -- never a citation invented after the
fact. What gets indexed here deliberately excludes exact prices/quantities
(plan §8): those stay DuckDB/Postgres-only and are read live at chat-query
time via MCP tools, not pre-indexed into Cognee.
"""

import logging
import sys
from pathlib import Path

import duckdb

# config MUST be imported before cognee -- it sets cognee's LLM/embedding/
# access-control env vars at import time (ENABLE_BACKEND_ACCESS_CONTROL
# etc.), which cognee reads once during its own module-level init.
import config
import cognee

import versioning
import citation_store

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent

# Reuses the SAME DuckDB path resolution every other tool server already
# uses (mcp-tools/shared/db_config.py) -- not a second, possibly-divergent
# copy of that path.
sys.path.insert(0, str(_REPO_ROOT / "mcp-tools"))
from shared.db_config import DB_PATH as BOM_STORAGE_DB_PATH  # noqa: E402

# reporting/superset's own config.py resolves CBOM_DB_PATH -- same
# REPORTING_DATABASE_DIR-env-var-override gap bom_qa_lookup_server.py
# already documents; this service's manage_backend.py SERVICES entry must
# pass the same env override (see plan task for wiring into
# manage_backend.py).
sys.path.insert(0, str(_REPO_ROOT / "mcp-tools" / "reporting" / "superset"))
import config as reporting_config  # noqa: E402

logger = logging.getLogger("rfq_memory.ingest")


def _bom_storage_conn():
    return duckdb.connect(str(BOM_STORAGE_DB_PATH), read_only=True)


def _cbom_conn():
    return duckdb.connect(reporting_config.CBOM_DB_PATH, read_only=True)


# ---------------------------------------------------------------------------
# Content builders -- each returns a list of (text, citation) tuples.
# citation is a dict matching the MessageCitation shape (plan §4/§10):
# {"sourceType": str, "identifier": {...real fields from this exact row...}, "label": str}
# ---------------------------------------------------------------------------

def build_file_upload_content(rfq_id: str, version: int, tool_result: dict) -> list[tuple[str, dict]]:
    """Sourced from Postgres rfq_file_telemetry -- file role/path/type/scan
    status only, never the file's own numeric content."""
    items = []
    with config.db.get_metadata_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT file_role, file_path, file_type, scan_status
                FROM rfq_file_telemetry
                WHERE rfq_id = %s AND version = %s AND is_active
                """,
                (rfq_id, version),
            )
            rows = cur.fetchall()
    for file_role, file_path, file_type, scan_status in rows:
        text = (
            f"RFQ {rfq_id} (version {version}) has an uploaded {file_role} file: "
            f"{Path(file_path).name} ({file_type}), scan status: {scan_status}."
        )
        citation = {
            "sourceType": "file_telemetry",
            "identifier": {"rfq_id": rfq_id, "version": version, "file_role": file_role, "file_path": file_path},
            "label": f"Uploaded file — {file_role} ({Path(file_path).name})",
        }
        items.append((text, citation))
    return items


def build_cbom_content(rfq_id: str, version: int, tool_result: dict) -> list[tuple[str, dict]]:
    """Sourced from DuckDB cbom.cbom via db.versioned_key -- descriptive
    fields + which source was selected only. Prices/quantities are
    deliberately excluded (plan §8) -- chat reads those live via MCP tools,
    never from what Cognee remembers here."""
    key = config.db.versioned_key(rfq_id, version)
    items = []
    with _cbom_conn() as conn:
        rows = conn.execute(
            """
            SELECT cbom_item_id, volume_no, fg, cpn, final_mfg_name, final_supp_name
            FROM cbom
            WHERE rfq_id = ?
            """,
            [key],
        ).fetchall()
    for cbom_item_id, volume_no, fg, cpn, final_mfg_name, final_supp_name in rows:
        text = (
            f"RFQ {rfq_id} CBOM line — FG {fg}, CPN {cpn}, volume {volume_no}: "
            f"manufacturer {final_mfg_name or 'unspecified'}, selected supplier {final_supp_name or 'unspecified'}."
        )
        citation = {
            "sourceType": "cbom_row",
            "identifier": {"rfq_id": rfq_id, "cbom_item_id": str(cbom_item_id), "volume_no": volume_no, "fg": fg, "cpn": cpn},
            "label": f"CBOM row — CPN {cpn}, Volume {volume_no}",
        }
        items.append((text, citation))
    return items


def build_gerber_checklist_content(rfq_id: str, version: int, tool_result: dict) -> list[tuple[str, dict]]:
    """Sourced from DuckDB gerber_checklist -- includes the provenance
    column (system vs. human-corrected) as real, citable content, exactly
    the kind of narrative/decision context Cognee should hold (plan §8)."""
    items = []
    with _bom_storage_conn() as conn:
        rows = conn.execute(
            """
            SELECT field, value_text, value_num, value_bool, present, provenance, confidence
            FROM gerber_checklist
            WHERE rfq_id = ?
            """,
            [rfq_id],
        ).fetchall()
    for field, value_text, value_num, value_bool, present, provenance, confidence in rows:
        value = value_text if value_text is not None else (value_num if value_num is not None else value_bool)
        text = (
            f"RFQ {rfq_id} Gerber checklist field '{field}': "
            f"{'present, value=' + str(value) if present else 'absent'} (source: {provenance or 'system'})."
        )
        citation = {
            "sourceType": "gerber_checklist",
            "identifier": {"rfq_id": rfq_id, "field": field, "provenance": provenance},
            "label": f"Gerber checklist — {field}",
        }
        items.append((text, citation))
    return items


def build_alternates_content(rfq_id: str, version: int, tool_result: dict) -> list[tuple[str, dict]]:
    """Sourced from DuckDB update_alternatives -- which alternate was
    preferred, not the stock/price numbers backing that decision."""
    items = []
    with _bom_storage_conn() as conn:
        rows = conn.execute(
            "SELECT cpn, mpn, preferred_flag FROM update_alternatives WHERE rfq_id = ?",
            [rfq_id],
        ).fetchall()
    for cpn, mpn, preferred_flag in rows:
        text = (
            f"RFQ {rfq_id} alternates for CPN {cpn}: MPN {mpn} is "
            f"{'the preferred alternate' if preferred_flag else 'a considered, non-preferred alternate'}."
        )
        citation = {
            "sourceType": "bom_row",
            "identifier": {"rfq_id": rfq_id, "cpn": cpn, "mpn": mpn},
            "label": f"Alternates — CPN {cpn} / MPN {mpn}",
        }
        items.append((text, citation))
    return items


# tool_name -> (node_set tag, content builder). Extend this table as new
# stages are wired in (plan §2) -- this is the one dispatch point
# fastapi_router.py's /tool/execute hook and the upload/HITL hooks all
# funnel through via ingest_stage() below.
_DISPATCH = {
    "file_upload": ("file_upload", build_file_upload_content),
    "centum_reporting__cbom": ("cbom", build_cbom_content),
    "gerber__extract_features": ("gerber", build_gerber_checklist_content),
    "centum_intake__detect_alternates": ("alternates", build_alternates_content),
}


async def ingest_stage(rfq_id: str, version: int, source: str, tool_result: dict | None = None) -> dict:
    """The single entrypoint every trigger site calls (via the /internal/
    memory/ingest HTTP route). Re-validates the carried version is STILL
    the active one immediately before the Cognee write (plan §0.A) -- a
    stale job is a silent no-op, never a write, never an exception raised
    back to the (fire-and-forget) caller.
    """
    if not config.RFQ_MEMORY_ENABLED:
        return {"status": "disabled"}

    dispatch_entry = _DISPATCH.get(source)
    if dispatch_entry is None:
        logger.info("[MEMORY INGEST] rfq_id=%s source=%s: no content builder registered, skipping", rfq_id, source)
        return {"status": "skipped", "reason": "no_builder"}

    node_set, builder = dispatch_entry

    try:
        # First check: cheap early-exit before doing any DB reads at all.
        versioning.assert_current_version(rfq_id, version)

        items = builder(rfq_id, version, tool_result or {})
        if not items:
            logger.info("[MEMORY INGEST] rfq_id=%s source=%s: builder returned no content", rfq_id, source)
            return {"status": "empty"}

        # Second, authoritative check: immediately before the actual Cognee
        # write. This is the check that closes the real race (plan §0.A) --
        # an old-version job that was queued before a re-upload's prune must
        # never land after that prune completes.
        versioning.assert_current_version(rfq_id, version)

        dataset_name = config.dataset_name_for(rfq_id)
        rfq_tag = config.node_set_tag_for(rfq_id)
        for text, citation in items:
            # rfq_tag is the ACTUAL enforced isolation boundary at search
            # time (see node_set_tag_for's own docstring) -- node_set is
            # never a single shared value across RFQs. The content-type tag
            # (node_set, e.g. "cbom") rides alongside it on the same node;
            # that's safe at ADD time (a node can carry multiple tags), the
            # risk is only ever at SEARCH time if both were combined into
            # one node_name filter list (node_name_filter_operator defaults
            # to "OR", which would widen instead of narrow) -- query.py
            # never does that.
            await cognee.add(
                data=text,
                dataset_name=dataset_name,
                node_set=[rfq_tag, node_set],
            )
            # Citation integrity (plan §0.D): recorded HERE, at ingest time,
            # from the real row this text was built from -- never
            # reconstructed or guessed at retrieval time.
            citation_store.store_citation(text, rfq_id, citation)
        await cognee.cognify(datasets=[dataset_name])

        logger.info(
            "[MEMORY INGEST] rfq_id=%s version=%s source=%s: %d item(s) added+cognified",
            rfq_id, version, source, len(items),
        )
        return {"status": "ok", "items": len(items)}

    except versioning.StaleVersionError as e:
        logger.info("[MEMORY INGEST STALE] %s", e)
        return {"status": "stale_version_rejected"}
    except Exception:
        logger.exception("[MEMORY INGEST ERROR] rfq_id=%s source=%s", rfq_id, source)
        return {"status": "error"}
