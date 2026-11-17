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

import asyncio
import logging
import os
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import httpx

# config MUST be imported before cognee -- it sets cognee's LLM/embedding/
# access-control env vars at import time (ENABLE_BACKEND_ACCESS_CONTROL
# etc.), which cognee reads once during its own module-level init.
import config
import cognee

import versioning
import citation_store

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent

# Same DuckDB files and env vars as the tool servers (mcp-tools/intake/config.py DB_PATH,
# mcp-tools/reporting/superset/config.py CBOM_DB_PATH). 3.3's mcp-tools/shared/db_config.py no longer
# exists, and `import config` from reporting/superset would return THIS service's config (already in
# sys.modules), so the paths are resolved here from the env the compose python-env anchor sets.
_DATABASE_DIR = os.environ.get("REPORTING_DATABASE_DIR", str(_REPO_ROOT / "database"))
BOM_STORAGE_DB_PATH = os.environ.get("BOM_STORAGE_DB", os.path.join(_DATABASE_DIR, "bom_storage.duckdb"))
CBOM_DB_PATH = os.environ.get("REPORTING_CBOM_DB", os.path.join(_DATABASE_DIR, "cbom.duckdb"))

logger = logging.getLogger("rfq_memory.ingest")

# One add+cognify at a time: local Ollama (qwen3:8b) is shared with the live RFQ pipeline, and parallel
# cognify runs are what made it hang mid-ingestion. ponytail: process-wide lock, per-RFQ queue if
# throughput ever matters (a cloud LLM via RFQ_MEMORY_LLM_PROVIDER removes the contention instead).
COGNIFY_LOCK = asyncio.Semaphore(1)

# Attachment text is split into pieces well below Cognee's chunk size, so each piece comes back from
# SearchType.CHUNKS verbatim and its sha256 still finds the citation stored for it (a longer text
# would be re-chunked by Cognee and every chunk would be dropped as uncited by query.py).
ATTACHMENT_PIECE_CHARS = 1200


def split_attachment_text(text: str, max_chars: int = ATTACHMENT_PIECE_CHARS) -> list[str]:
    """Paragraph-packed pieces of at most max_chars; an oversized paragraph is hard-cut."""
    pieces, current = [], ""
    for para in (p.strip() for p in text.split("\n")):
        if not para:
            continue
        while len(para) > max_chars:
            if current:
                pieces.append(current)
                current = ""
            pieces.append(para[:max_chars])
            para = para[max_chars:].strip()
        if current and len(current) + 1 + len(para) > max_chars:
            pieces.append(current)
            current = ""
        current = f"{current}\n{para}" if current else para
    if current:
        pieces.append(current)
    return pieces


def build_attachment_content(rfq_id: str, attachment_id: str, filename: str, text: str) -> list[tuple[str, dict]]:
    """Each piece is prefixed with the file and RFQ, which both tells the answering LLM where the text
    came from and makes the content hash unique per RFQ/file (rfq_memory_citations is keyed by hash)."""
    pieces = split_attachment_text(text)
    items = []
    for i, piece in enumerate(pieces, start=1):
        body = f"Attachment {filename} (RFQ {rfq_id}, part {i}/{len(pieces)}):\n{piece}"
        citation = {
            "sourceType": "file_telemetry",
            "identifier": {"rfq_id": rfq_id, "attachment_id": attachment_id, "filename": filename, "part": i},
            "label": f"Attachment — {filename}" + (f" (part {i}/{len(pieces)})" if len(pieces) > 1 else ""),
        }
        items.append((body, citation))
    return items


async def ingest_attachment(rfq_id: str, attachment_id: str, filename: str, text: str) -> dict:
    """Background job for POST /internal/memory/ingest-attachment. No version check: chat attachments
    are not versioned uploads (rfq_process_tracking has no row for them); a re-upload's prune of the
    RFQ dataset removes them along with everything else."""
    if not config.RFQ_MEMORY_ENABLED:
        return {"status": "disabled"}
    items = build_attachment_content(rfq_id, attachment_id, filename, text)
    if not items:
        return {"status": "empty"}
    dataset_name = config.dataset_name_for(rfq_id)
    rfq_tag = config.node_set_tag_for(rfq_id)
    started = time.monotonic()
    try:
        async with COGNIFY_LOCK:
            for body, citation in items:
                await cognee.add(data=body, dataset_name=dataset_name, node_set=[rfq_tag, "attachment"])
                citation_store.store_citation(body, rfq_id, citation)
            await cognee.cognify(datasets=[dataset_name])
        logger.info(
            "[MEMORY ATTACHMENT] rfq_id=%s file=%s: %d piece(s) added+cognified in %.1fs",
            rfq_id, filename, len(items), time.monotonic() - started,
        )
        return {"status": "ok", "items": len(items)}
    except Exception:
        logger.exception("[MEMORY ATTACHMENT ERROR] rfq_id=%s file=%s after %.1fs", rfq_id, filename, time.monotonic() - started)
        return {"status": "error"}


def _bom_storage_conn():
    return duckdb.connect(str(BOM_STORAGE_DB_PATH), read_only=True)


def _cbom_conn():
    return duckdb.connect(CBOM_DB_PATH, read_only=True)


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


BATCH_ROWS = max(1, int(os.environ.get("RFQ_MEMORY_BATCH_ROWS") or 25))
DAEMON_URL = os.environ.get("CAM_DAEMON_URL", "http://host.docker.internal:9334").rstrip("/")
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE = "https://openrouter.ai/api/v1"


FALLBACK_MODEL = os.environ.get("RFQ_MEMORY_FALLBACK_MODEL", "anthropic/claude-haiku-5.5")
# Models that answered the graph extraction as text, not as Cognee's structure. Remembered for the life of the process.
_BAD_MODELS: set[str] = set()


def _set_cloud(model: str) -> None:
    cognee.config.set_llm_provider("openai")
    cognee.config.set_llm_model(f"openai/{model}")
    cognee.config.set_llm_endpoint(OPENROUTER_BASE)
    cognee.config.set_llm_api_key(OPENROUTER_KEY)


def _use_client_llm() -> str:
    """Points Cognee's extraction at the model the client chose in the daemon (cloud, through OpenRouter), or at the Ollama
    default when no cloud choice exists. Called under COGNIFY_LOCK: one job at a time, so the setting is never shared mid-job.
    Embeddings stay on Ollama either way (OpenRouter has no embeddings endpoint)."""
    choice = {"provider": "ollama", "model": None}
    try:
        choice = httpx.get(f"{DAEMON_URL}/api/internal/memory-provider", timeout=3).json()
    except Exception as e:
        logger.warning("[MEMORY LLM] client choice unavailable, using the Ollama default: %s", e)
    if choice.get("provider") == "openrouter" and choice.get("model") and OPENROUTER_KEY:
        if choice["model"] in _BAD_MODELS:
            # Already known not to produce the graph structure: go straight to the fallback, no retry loop per job.
            _set_cloud(FALLBACK_MODEL)
            return f"openrouter:{FALLBACK_MODEL} (client model {choice['model']} does not extract graphs)"
        _set_cloud(choice["model"])
        return f"openrouter:{choice['model']}"
    cognee.config.set_llm_provider(config.LLM_PROVIDER)
    cognee.config.set_llm_model(config.LLM_MODEL)
    cognee.config.set_llm_endpoint(config.LLM_ENDPOINT)
    cognee.config.set_llm_api_key(config.LLM_API_KEY)
    return f"ollama:{config.LLM_MODEL}"


def _batched(items: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
    """Groups rows into documents of BATCH_ROWS. Cognee runs one LLM extraction per document: a 500-row CBOM as 500
    documents took hours on the local model. The citation of a group names its rows (row ids, in order) and its first and
    last label, so each citation still points at the real rows it was built from."""
    out = []
    for start in range(0, len(items), BATCH_ROWS):
        group = items[start:start + BATCH_ROWS]
        first, last = group[0][1], group[-1][1]
        # Each row keeps its own identity: the first identifier value of every row, in order (cbom_item_id, row number, ...).
        row_keys = ",".join(next((str(v) for v in c.get("identifier", {}).values()), "") for _, c in group)
        citation = {
            "sourceType": first["sourceType"],
            "identifier": {"rfq_id": str(first.get("identifier", {}).get("rfq_id", "")), "rows": len(group), "row_keys": row_keys[:900]},
            "label": f"{first['label']} to {last['label']} ({len(group)} rows)" if len(group) > 1 else first["label"],
        }
        out.append(("\n".join(text for text, _ in group), citation))
    return out


async def _cognify_with_fallback(dataset_name: str) -> str:
    """Cognifies one dataset with the client's model. A model that answers the graph extraction as text instead of Cognee's
    structure is remembered (_BAD_MODELS) and the work is retried once on the fallback; a local model, or a fallback that fails
    too, is a real error. Returns the label of the model that finished."""
    llm = _use_client_llm()
    try:
        await cognee.cognify(datasets=[dataset_name])
        return llm
    except Exception as first:
        failed_model = llm.split(":", 1)[1].split(" ")[0] if llm.startswith("openrouter:") else ""
        if not failed_model or failed_model == FALLBACK_MODEL:
            raise
        # Only a model that answered in the wrong shape is remembered. A rate limit or a timeout is transient: this job still
        # finishes on the fallback, but the client's model is tried again next time.
        structural = "ValidationError" in type(first).__name__ or "valid array" in str(first) or "validation error" in str(first).lower()
        if structural and failed_model not in _BAD_MODELS:
            logger.warning("[MEMORY LLM] %s answered the graph extraction in the wrong shape (%s); remembering it", llm, first)
            _BAD_MODELS.add(failed_model)
        else:
            logger.warning("[MEMORY LLM] %s failed this job (%s); finishing it on %s", llm, first, FALLBACK_MODEL)
        _set_cloud(FALLBACK_MODEL)
        await cognee.cognify(datasets=[dataset_name])
        return f"openrouter:{FALLBACK_MODEL} (after {failed_model} failed)"


RECENT_JOBS: deque = deque(maxlen=50)


def _emit(job: dict) -> None:
    """Publishes one job's state to the daemon (it broadcasts memory:job to the open admin pages) and keeps it for the status
    endpoint. Best effort: a missing daemon never fails an ingest."""
    # One entry per job: the end state replaces the running one, so the status list never shows both.
    for i, existing in enumerate(RECENT_JOBS):
        if existing.get("jobId") == job.get("jobId"):
            RECENT_JOBS[i] = job
            break
    else:
        RECENT_JOBS.appendleft(job)
    try:
        httpx.post(f"{DAEMON_URL}/api/internal/emit-memory-event", json=job, timeout=2)
    except Exception as e:
        logger.info("[MEMORY EVENT] not delivered: %s", e)


async def ingest_stage(rfq_id: str, version: int, source: str, tool_result: dict | None = None) -> dict:
    """One Cognee write, reported as it runs: a running entry when it starts, the outcome when it ends."""
    job = {"jobId": uuid.uuid4().hex, "rfqId": rfq_id, "version": version, "source": source, "state": "running", "startedAt": _now()}
    _emit(job)
    result = await _ingest_stage_inner(rfq_id, version, source, tool_result)
    job = {**job, "state": result.get("status", "error"), "finishedAt": _now(), "items": result.get("items"), "llm": result.get("llm")}
    _emit(job)
    return result


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


ADMIN_DATASET = "rfq_ADMIN-MASTERS"
ADMIN_TAG = "admin-masters"


async def ingest_admin_masters(sheets: list[dict]) -> dict:
    """The company masters (Organisation, Project, CAM Masters, Quote): one document per row group of each tab, in the
    ADMIN_DATASET with the ADMIN_TAG node set. Rows come from the browser, which parses the shipped workbooks; a row is
    cited by its master, tab and row number."""
    job = {"jobId": uuid.uuid4().hex, "rfqId": "ADMIN-MASTERS", "version": 0, "source": "admin_masters", "state": "running", "startedAt": _now()}
    _emit(job)
    items: list[tuple[str, dict]] = []
    for sheet in sheets:
        master, tab = str(sheet["master"]), str(sheet["tab"])
        columns = [str(c) for c in sheet["columns"]]
        for n, row in enumerate(sheet["rows"], start=1):
            fields = [f"{col}: {val}" for col, val in zip(columns, row) if val not in (None, "")]
            if not fields:
                continue
            items.append((
                f"{master} · {tab}, row {n}: " + "; ".join(fields),
                {"sourceType": "admin_master", "identifier": {"master": master, "tab": tab, "row": n}, "label": f"{master} · {tab}, row {n}"},
            ))
    if not items:
        job = {**job, "state": "empty", "finishedAt": _now(), "items": 0}
        _emit(job)
        return {"status": "empty", "items": 0}
    try:
        groups = _batched(items)
        async with COGNIFY_LOCK:
            for body, citation in groups:
                await cognee.add(data=body, dataset_name=ADMIN_DATASET, node_set=[ADMIN_TAG])
                citation_store.store_citation(body, ADMIN_DATASET, citation)
            llm = await _cognify_with_fallback(ADMIN_DATASET)
        result = {"status": "ok", "items": len(items), "documents": len(groups), "llm": llm}
    except Exception:
        logger.exception("[MEMORY MASTERS ERROR] %d rows", len(items))
        result = {"status": "error", "items": len(items)}
    job = {**job, "state": result["status"], "finishedAt": _now(), "items": len(items), "llm": result.get("llm")}
    _emit(job)
    return result


async def _ingest_stage_inner(rfq_id: str, version: int, source: str, tool_result: dict | None = None) -> dict:
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
        items = _batched(items)

        # Second, authoritative check: immediately before the actual Cognee
        # write. This is the check that closes the real race (plan §0.A) --
        # an old-version job that was queued before a re-upload's prune must
        # never land after that prune completes.
        versioning.assert_current_version(rfq_id, version)

        dataset_name = config.dataset_name_for(rfq_id)
        rfq_tag = config.node_set_tag_for(rfq_id)
        async with COGNIFY_LOCK:
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
            llm = await _cognify_with_fallback(dataset_name)

        logger.info(
            "[MEMORY INGEST] rfq_id=%s version=%s source=%s: %d document(s) added+cognified with %s",
            rfq_id, version, source, len(items), llm,
        )
        return {"status": "ok", "items": len(items), "llm": llm}

    except versioning.StaleVersionError as e:
        logger.info("[MEMORY INGEST STALE] %s", e)
        return {"status": "stale_version_rejected"}
    except Exception:
        logger.exception("[MEMORY INGEST ERROR] rfq_id=%s source=%s", rfq_id, source)
        return {"status": "error"}
