"""[BuLLMQuote-SRIM MIGRATION NOTE -- added on copy, updated after reporting_module migrated]
UPDATE: reporting_module has been migrated to mcp-tools/reporting/superset/;
the sys.path insert below now points there and `import database`/
`import final_selection` resolve and import successfully -- verified.
STILL BROKEN, though, at the point of actually USING them: reporting_module's
own config.py resolves its DB paths relative to itself (`../database`), which
from mcp-tools/reporting/superset/ does not reach this repo's `database/`
(not yet migrated -- see database/README.md and
mcp-tools/reporting/superset/config.py's own migration note). Any endpoint
here that actually calls into reporting_database/final_selection will fail at
the DB connection, not at import time, until either database/ is migrated
into this repo or REPORTING_DATABASE_DIR is set to point at
`centum intake\\database\\` directly.
[END MIGRATION NOTE]

Human-review endpoints for the resolve_final_selection HITL gate.

Reads/writes Postgres logic_db.final_selection_conflicts directly -- this is
workflow/review state, not analytical CBOM data (see
reporting_module/final_selection.py's module docstring for the full
reasoning). Only the chosen resolution's field values are ever written into
cbom.duckdb's final_* columns; the in-progress conflict list itself never
touches DuckDB.

NOTE / open item: unified_quote_package.approved_by (logic_db) was the
originally planned "light sign-off marker" once every conflict for an rfq_id
is resolved. It isn't wired up here -- unified_quote_package.rfq_id and
rfq_master.rfq_id are both UUID, keyed off rfq_master.rfq_number, and no
rfq_master row exists for the VARCHAR-style rfq_id scheme ("CE-005570" etc.)
used everywhere else in this pipeline (rfq_process_tracking,
rfq_file_telemetry, final_selection_conflicts). Writing to
unified_quote_package would either fail (invalid UUID) or require inventing
an unreconciled mapping. The functionally critical behavior -- advancing
rfq_process_stage so the routing sequence can resume -- does not depend on
this and works correctly below. Revisit once the rfq_id <-> rfq_master
relationship is clarified.
"""

import os
import sys
from typing import List, Optional

import duckdb
import pandas as pd
from fastapi import Depends, FastAPI, HTTPException

import auth
import rfq_memory_client
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
# [BuLLMQuote-SRIM] Updated for the new layout -- reporting_module now lives
# at mcp-tools/reporting/superset/, a sibling of this fastmcp-router/ folder,
# not a subfolder of it. Inserted AFTER _THIS_DIR so it ends up FIRST in
# sys.path (last insert(0, ...) wins) -- required so `import database`/
# `import config` below resolve to reporting_module's own files, not this
# folder's same-named config.py (see config.py's own migration note for the
# name-collision this depends on).
_REPORTING_DIR = os.path.join(_THIS_DIR, "..", "mcp-tools", "reporting", "superset")
for _dir in (_THIS_DIR, _REPORTING_DIR):
    if _dir not in sys.path:
        sys.path.insert(0, _dir)

from db import (
    duckdb_file_lock,
    get_logic_connection, increment_skill_index, advance_skill_index_to_at_least,
    get_active_version, versioned_key, get_routing_sequence, set_hitl_required,
)

_RESOLVE_FINAL_SELECTION_TOOL = "centum_reporting__resolve_final_selection"


def _advance_past_resolve_final_selection(rfq_id: str) -> int:
    """Moves rfq_process_stage unambiguously past resolve_final_selection's own
    position in the live routing sequence -- see advance_skill_index_to_at_least()'s
    docstring in db.py for why a blind increment_skill_index() is not enough here.
    Falls back to the old blind +1 if the routing sequence can't be resolved for
    any reason (e.g. a Skills Settings misconfiguration) -- fail open, since a
    human has already explicitly approved and must not be re-blocked by an
    unrelated lookup failure.
    """
    try:
        routing_sequence = get_routing_sequence("Standard_BOM_Flow")
        target_index = routing_sequence.index(_RESOLVE_FINAL_SELECTION_TOOL) + 1
        new_stage = advance_skill_index_to_at_least(rfq_id, target_index)
        print(f"[FINAL-SELECTION] advanced past resolve_final_selection (index {target_index - 1}) -- rfq_process_stage={new_stage}")
        return new_stage
    except Exception as e:
        print(f"[FINAL-SELECTION ERROR] Could not resolve routing sequence, falling back to +1: {e}")
        return increment_skill_index(rfq_id)

# reporting_module.database.connect() is reused (not a raw duckdb.connect())
# because it sets up the cbom_db/input_db ATTACH aliases final_selection.py's
# SQL (cbom_db.cbom) expects -- a bare connection to cbom.duckdb has no such
# alias and every query would fail with "schema cbom_db does not exist".
import database as reporting_database
import final_selection

app = FastAPI(title="Centum HITL Router", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _resolve_cbom_key(rfq_id: str) -> str:
    """final_selection_conflicts (logic_db) is cbom_item_id-scoped to one
    specific version's cbom.duckdb rows, so every conflict-table query and
    every reporting_database/final_selection call must use the ACTIVE
    version's key, not the bare canonical rfq_id -- otherwise two versions
    of the same RFQ that both ran resolve_final_selection would collide in
    final_selection_conflicts under the same bare rfq_id.

    Fails open (falls back to the bare rfq_id) if this RFQ has no Postgres
    tracking row at all -- same philosophy as fastapi_router.py's
    /tool/execute, preserving today's behavior for RFQs that predate this
    versioning feature or were created outside the normal upload flow.
    """
    try:
        return versioned_key(rfq_id, get_active_version(rfq_id))
    except Exception as e:
        print(f"[VERSION RESOLUTION ERROR] Could not resolve active version for {rfq_id}: {e}")
        return rfq_id


class ResolutionItem(BaseModel):
    conflict_id: str
    resolved_source: str  # 'costing' | 'erp' | 'qw'
    resolved_by: str


class ResolveBatchRequest(BaseModel):
    resolutions: List[ResolutionItem]


@app.get("/api/rfq/{rfq_id}/final-selection/pending")
def get_pending_conflicts(rfq_id: str, cursor: Optional[str] = None, limit: int = 100, token: dict = Depends(auth.verify_token)):
    """Keyset/cursor-paginated retrieval of unresolved conflicts -- deliberately not
    OFFSET-based, which degrades at the row counts this needs to support (an RFQ can
    have thousands of conflicting rows). Pass the last item's conflict_id as `cursor`
    to fetch the next page.
    """
    limit = max(1, min(limit, 500))
    cbom_key = _resolve_cbom_key(rfq_id)

    with get_logic_connection() as conn:
        with conn.cursor() as cur:
            if cursor:
                cur.execute(
                    """
                    SELECT conflict_id, cbom_item_id, bom_item_id, volume_no, cpn, available_sources
                    FROM final_selection_conflicts
                    WHERE rfq_id = %s AND resolved_source IS NULL AND conflict_id > %s
                    ORDER BY conflict_id
                    LIMIT %s
                    """,
                    (cbom_key, cursor, limit)
                )
            else:
                cur.execute(
                    """
                    SELECT conflict_id, cbom_item_id, bom_item_id, volume_no, cpn, available_sources
                    FROM final_selection_conflicts
                    WHERE rfq_id = %s AND resolved_source IS NULL
                    ORDER BY conflict_id
                    LIMIT %s
                    """,
                    (cbom_key, limit)
                )
            rows = cur.fetchall()

    items = [
        {
            "conflict_id": r[0],
            "cbom_item_id": r[1],
            "bom_item_id": r[2],
            "volume_no": r[3],
            "cpn": r[4],
            "available_sources": r[5],
        }
        for r in rows
    ]

    return {
        "rfq_id": rfq_id,
        "items": items,
        "next_cursor": items[-1]["conflict_id"] if len(items) == limit else None,
    }


@app.get("/api/rfq/{rfq_id}/final-selection/summary")
def get_summary(rfq_id: str, token: dict = Depends(auth.verify_token)):
    """Lightweight counts only -- no row payload, safe to poll for a progress UI."""
    cbom_key = _resolve_cbom_key(rfq_id)
    with get_logic_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE resolved_source IS NOT NULL) AS resolved
                FROM final_selection_conflicts
                WHERE rfq_id = %s
                """,
                (cbom_key,)
            )
            total, resolved = cur.fetchone()

    return {
        "rfq_id": rfq_id,
        "total": total,
        "resolved": resolved,
        "remaining": total - resolved,
    }


def _signal_resolve_approved(rfq_id: str):
    """Tell the workflow parked at resolve_final_selection that the gate passed.

    Returns True/False once a signal was attempted, None when Temporal is off. A failed
    signal is non-fatal here: rfq_process_stage has already advanced.
    """
    if os.environ.get("CAM_USE_TEMPORAL", "true").lower() != "true":
        return None
    import asyncio as _asyncio
    import pathlib as _pathlib
    sys.path.insert(0, str(_pathlib.Path(__file__).parent.parent / "temporal_worker"))
    try:
        import client as temporal_client
        workflow_id = temporal_client.get_workflow_id(rfq_id)
        _asyncio.run(temporal_client.send_hitl_signal(workflow_id, {"action": "approve"}))
        print(f"[TEMPORAL SIGNAL] sent human_decision approve to workflow {workflow_id!r}")
        return True
    except Exception as sig_err:
        print(f"[TEMPORAL SIGNAL ERROR] {sig_err}")
        return False


@app.post("/api/rfq/{rfq_id}/final-selection")
def submit_resolutions(rfq_id: str, request: ResolveBatchRequest, token: dict = Depends(auth.verify_token)):
    """Batch/incremental resolution submission -- a reviewer can submit any subset of
    the pending conflicts at a time, repeatedly, not all-or-nothing. Updates Postgres,
    writes each resolved row's chosen source values into cbom.duckdb's final_*, and
    only once EVERY conflict for this rfq_id is resolved does it advance
    rfq_process_stage past the resolve_final_selection skill -- letting a later
    GET /api/dify/start/{rfq_id} (upload_server.py) resume the Dify run past the
    HITL gate.
    """
    cbom_key = _resolve_cbom_key(rfq_id)
    print(f"[FINAL-SELECTION] rfq_id={rfq_id!r} cbom_key={cbom_key!r} resolutions={request.resolutions!r}")

    if not request.resolutions:
        # Allowed as a no-op "confirm" ONLY when there's genuinely nothing
        # pending for this rfq_id already (e.g. only one pricing source was
        # uploaded, so resolve_final_selection halted with zero real
        # conflicts to reconcile -- see final_selection.py). Still rejected
        # when real conflicts are actually outstanding, same as before.
        with get_logic_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM final_selection_conflicts WHERE rfq_id = %s AND resolved_source IS NULL",
                    (cbom_key,)
                )
                remaining = cur.fetchone()[0]
        print(f"[FINAL-SELECTION] empty-resolutions branch: remaining={remaining} for cbom_key={cbom_key!r}")
        if remaining > 0:
            print(f"[FINAL-SELECTION] rejecting empty confirm -- {remaining} conflict(s) still unresolved")
            raise HTTPException(status_code=400, detail="resolutions list cannot be empty")
        try:
            new_stage = _advance_past_resolve_final_selection(rfq_id)
            print(f"[FINAL-SELECTION] advance succeeded -- new rfq_process_stage={new_stage}")
        except Exception as e:
            print(f"[FINAL-SELECTION ERROR] advance failed: {e}")
            raise
        return {
            "status": "success",
            "rfq_id": rfq_id,
            "resolved_count": 0,
            "remaining": 0,
            "fully_approved": True,
            "signal_delivered": _signal_resolve_approved(rfq_id),
        }

    resolved_rows = []

    with get_logic_connection() as conn:
        with conn.cursor() as cur:
            for item in request.resolutions:
                cur.execute(
                    """
                    UPDATE final_selection_conflicts
                    SET resolved_source = %s, resolved_by = %s, resolved_at = now()
                    WHERE conflict_id = %s AND rfq_id = %s AND resolved_source IS NULL
                    RETURNING cbom_item_id, available_sources
                    """,
                    (item.resolved_source, item.resolved_by, item.conflict_id, cbom_key)
                )
                row = cur.fetchone()
                if row is None:
                    # Already resolved (e.g. a retried request), or belongs to a
                    # different rfq_id -- not fatal, just nothing new to apply.
                    continue

                cbom_item_id, available_sources = row
                source_values = available_sources.get(item.resolved_source)
                if source_values is None:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"conflict_id={item.conflict_id}: '{item.resolved_source}' "
                            "is not one of its available_sources"
                        )
                    )
                resolved_rows.append((cbom_item_id, source_values))

            cur.execute(
                "SELECT COUNT(*) FROM final_selection_conflicts WHERE rfq_id = %s AND resolved_source IS NULL",
                (cbom_key,)
            )
            remaining = cur.fetchone()[0]

        conn.commit()

    print(f"[FINAL-SELECTION] resolutions branch: resolved_rows={len(resolved_rows)} remaining={remaining}")

    if resolved_rows:
        with duckdb_file_lock():
            duck_con = reporting_database.connect()
            try:
                duck_con.execute("BEGIN TRANSACTION")
                for cbom_item_id, source_values in resolved_rows:
                    final_selection.apply_resolved_conflict(duck_con, cbom_key, cbom_item_id, source_values)
                final_selection.recompute_derived_columns(duck_con, cbom_key)
                duck_con.execute("COMMIT")
            except Exception:
                duck_con.execute("ROLLBACK")
                duck_con.close()
                raise
            duck_con.close()

        # Best-effort Cognee ingestion trigger (RFQ chat memory feature) --
        # fire-and-forget, never allowed to affect this endpoint's own
        # response. Uses the JWT-VERIFIED rfq_id (token["rfq_id"]), not the
        # raw path param, per plan §0/§3's non-negotiable rule -- though
        # auth.verify_token already guarantees these are identical by the
        # time this line runs, or the request would have 401'd earlier.
        try:
            rfq_memory_client.queue_ingestion(
                rfq_id=token["rfq_id"],
                version=get_active_version(token["rfq_id"]),
                source="hitl_resolution",
                tool_result={"resolved_count": len(resolved_rows)},
            )
        except Exception as e:
            print(f"[MEMORY INGEST ERROR] {e}")

    fully_approved = False
    signal_delivered = None  # None = no signal attempted (gate not yet passed)
    if remaining == 0:
        try:
            new_stage = _advance_past_resolve_final_selection(rfq_id)
            print(f"[FINAL-SELECTION] advance succeeded -- new rfq_process_stage={new_stage}")
        except Exception as e:
            print(f"[FINAL-SELECTION ERROR] advance failed: {e}")
            raise
        fully_approved = True
        signal_delivered = _signal_resolve_approved(rfq_id)
    else:
        print(f"[FINAL-SELECTION] not advancing -- {remaining} conflict(s) still unresolved")

    return {
        "status": "success",
        "rfq_id": rfq_id,
        "resolved_count": len(resolved_rows),
        "remaining": remaining,
        "fully_approved": fully_approved,
        "signal_delivered": signal_delivered,
    }


# ============================================================
# RFQ_Flow: distributor__detect_alternates HITL gate
#
# Unlike final_selection_conflicts above (Postgres logic_db + cbom.duckdb,
# version-keyed), this data lives entirely in bom_storage.duckdb's
# update_alternatives/processed_bom_items tables, keyed by the bare rfq_id
# (no versioned_key() -- see intake/bom_to_database.py and
# distributor_pricing/detect_alternates.py, neither of which version-scope
# their inserts). rfq_process_stage advancement still goes through the same
# Postgres db.py helpers as final_selection, since that's shared runtime
# state regardless of which flow/profile an rfq_id is running.
# ============================================================

BOM_STORAGE_DB_PATH = r"C:\SRIM-DB-SETUP\Databases\bom_storage.duckdb"
_DETECT_ALTERNATES_TOOL = "distributor__detect_alternates"


def _advance_past_detect_alternates(rfq_id: str) -> int:
    """Mirrors _advance_past_resolve_final_selection above, but for RFQ_Flow's
    detect_alternates position -- see that function's docstring for why a
    routing-sequence-relative advance is used instead of a blind +1.

    Also explicitly clears hitl_required -- advance_skill_index_to_at_least()
    only ever touches rfq_process_stage, never hitl_required, so without this
    a resumed Dify run's "is this RFQ still HITL-pending" check would keep
    reading hitl_required=true even after every CPN has been resolved and the
    stage correctly advanced, aborting the resume."""
    try:
        routing_sequence = get_routing_sequence("RFQ_Flow")
        target_index = routing_sequence.index(_DETECT_ALTERNATES_TOOL) + 1
        new_stage = advance_skill_index_to_at_least(rfq_id, target_index)
        print(f"[ALTERNATES] advanced past detect_alternates (index {target_index - 1}) -- rfq_process_stage={new_stage}")
    except Exception as e:
        print(f"[ALTERNATES ERROR] Could not resolve routing sequence, falling back to +1: {e}")
        new_stage = increment_skill_index(rfq_id)

    try:
        set_hitl_required(rfq_id, False)
    except Exception as e:
        print(f"[HITL STATE ERROR] Could not clear hitl_required: {e}")

    return new_stage


def _unresolved_cpns(conn, rfq_id: str) -> list:
    """A CPN counts as unresolved unless exactly one of its alternate MPN
    rows has preferred_flag=TRUE -- matches apply_alternatives.py's own
    all-or-nothing validation exactly, so this endpoint's "fully_approved"
    can never disagree with what apply_alternatives would itself accept."""
    df = conn.execute(
        """
        SELECT cpn
        FROM update_alternatives
        WHERE rfq_id = ?
        GROUP BY cpn
        HAVING SUM(CASE WHEN preferred_flag THEN 1 ELSE 0 END) != 1
        ORDER BY cpn
        """,
        [rfq_id]
    ).fetchdf()
    return df["cpn"].tolist()


class AlternateSelection(BaseModel):
    cpn: str
    mpn: str


class ResolveAlternatesBatchRequest(BaseModel):
    selections: List[AlternateSelection]


@app.get("/api/rfq/{rfq_id}/alternates/pending")
def get_pending_alternates(rfq_id: str, cursor: Optional[str] = None, limit: int = 100, token: dict = Depends(auth.verify_token)):
    """Keyset-paginated (by cpn) unresolved alternate-part groups, each with
    every candidate MPN's real enrichment pricing/stock already captured by
    distributor__enrich_bom -- the review UI needs this to let a human pick
    a preferred MPN with real price/availability in view, not just names."""
    limit = max(1, min(limit, 500))

    with duckdb.connect(BOM_STORAGE_DB_PATH, read_only=True) as conn:
        all_cpns = _unresolved_cpns(conn, rfq_id)
        if cursor:
            all_cpns = [c for c in all_cpns if c > cursor]
        page_cpns = all_cpns[:limit]

        if not page_cpns:
            return {"rfq_id": rfq_id, "items": [], "next_cursor": None}

        placeholders = ",".join("?" * len(page_cpns))
        candidates_df = conn.execute(
            f"""
            SELECT
                ua.cpn, ua.mpn, ua.mfr, ua.preferred_flag,
                p.digikey_unit_price, p.digikey_stock,
                p.mouser_unit_price, p.mouser_stock,
                p.element14_unit_price, p.element14_stock
            FROM update_alternatives ua
            LEFT JOIN processed_bom_items p
                ON p.rfq_id = ua.rfq_id AND p.cpn = ua.cpn AND p.mpn = ua.mpn
            WHERE ua.rfq_id = ? AND ua.cpn IN ({placeholders})
            ORDER BY ua.cpn, ua.mpn
            """,
            [rfq_id] + page_cpns
        ).fetchdf()

    def _clean(val):
        # pandas/duckdb NaN for an unmatched distributor field is not valid
        # JSON (json.dumps raises ValueError: "Out of range float values are
        # not JSON compliant: nan") -- normalize to None, which the frontend
        # can render as "no match" the same way it already treats a missing
        # key.
        if val is None:
            return None
        try:
            if pd.isna(val):
                return None
        except (TypeError, ValueError):
            pass
        return val

    items_by_cpn = {}
    for _, row in candidates_df.iterrows():
        items_by_cpn.setdefault(row["cpn"], []).append({
            "mpn": row["mpn"],
            "mfr": _clean(row["mfr"]),
            "preferred_flag": bool(row["preferred_flag"]),
            "digikey_unit_price": _clean(row["digikey_unit_price"]),
            "digikey_stock": _clean(row["digikey_stock"]),
            "mouser_unit_price": _clean(row["mouser_unit_price"]),
            "mouser_stock": _clean(row["mouser_stock"]),
            "element14_unit_price": _clean(row["element14_unit_price"]),
            "element14_stock": _clean(row["element14_stock"]),
        })

    items = [{"cpn": cpn, "candidates": candidates} for cpn, candidates in items_by_cpn.items()]

    return {
        "rfq_id": rfq_id,
        "items": items,
        "next_cursor": page_cpns[-1] if len(page_cpns) == limit else None,
    }


@app.get("/api/rfq/{rfq_id}/alternates/summary")
def get_alternates_summary(rfq_id: str, token: dict = Depends(auth.verify_token)):
    """Lightweight counts only, safe to poll for a progress UI."""
    with duckdb.connect(BOM_STORAGE_DB_PATH, read_only=True) as conn:
        total_df = conn.execute(
            "SELECT COUNT(DISTINCT cpn) FROM update_alternatives WHERE rfq_id = ?",
            [rfq_id]
        ).fetchone()
        total = total_df[0] if total_df else 0
        remaining = len(_unresolved_cpns(conn, rfq_id))

    return {
        "rfq_id": rfq_id,
        "total": total,
        "resolved": total - remaining,
        "remaining": remaining,
    }


@app.post("/api/rfq/{rfq_id}/alternates")
def submit_alternates(rfq_id: str, request: ResolveAlternatesBatchRequest, token: dict = Depends(auth.verify_token)):
    """Batch/incremental preferred-MPN selection -- a reviewer can submit any
    subset of the pending CPN groups at a time. Only once EVERY CPN group for
    this rfq_id has exactly one preferred_flag=TRUE does this advance
    rfq_process_stage past distributor__detect_alternates, letting a later
    GET /api/dify/start/{rfq_id} resume the Dify run into
    distributor__apply_alternatives."""

    if not request.selections:
        # Allowed as a no-op "confirm" only when nothing is actually pending
        # (e.g. detect_alternates found zero duplicate CPNs, but hitl was
        # still raised because of a race/retry) -- same graceful-empty
        # pattern as final-selection's own empty-resolutions branch above.
        with duckdb.connect(BOM_STORAGE_DB_PATH, read_only=True) as conn:
            remaining = len(_unresolved_cpns(conn, rfq_id))
        if remaining > 0:
            raise HTTPException(status_code=400, detail="selections list cannot be empty")
        new_stage = _advance_past_detect_alternates(rfq_id)
        return {
            "status": "success",
            "rfq_id": rfq_id,
            "resolved_count": 0,
            "remaining": 0,
            "fully_approved": True,
        }

    with duckdb.connect(BOM_STORAGE_DB_PATH, read_only=False) as conn:
        conn.execute("BEGIN TRANSACTION")
        try:
            for sel in request.selections:
                conn.execute(
                    "UPDATE update_alternatives SET preferred_flag = FALSE, updated_at = CURRENT_TIMESTAMP WHERE rfq_id = ? AND cpn = ?",
                    [rfq_id, sel.cpn]
                )
                conn.execute(
                    "UPDATE update_alternatives SET preferred_flag = TRUE, updated_at = CURRENT_TIMESTAMP WHERE rfq_id = ? AND cpn = ? AND mpn = ?",
                    [rfq_id, sel.cpn, sel.mpn]
                )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        remaining = len(_unresolved_cpns(conn, rfq_id))

    # Best-effort Cognee ingestion trigger (RFQ chat memory feature) --
    # fire-and-forget, never allowed to affect this endpoint's own
    # response. Uses the JWT-verified rfq_id, per plan §0/§3.
    try:
        rfq_memory_client.queue_ingestion(
            rfq_id=token["rfq_id"],
            version=get_active_version(token["rfq_id"]),
            source="centum_intake__detect_alternates",
            tool_result={"resolved_count": len(request.selections)},
        )
    except Exception as e:
        print(f"[MEMORY INGEST ERROR] {e}")

    fully_approved = False
    signal_delivered = None  # None = no signal attempted (gate not yet passed)
    if remaining == 0:
        new_stage = _advance_past_detect_alternates(rfq_id)
        fully_approved = True

        # CAM 3.4: send Temporal signal when workflow is waiting at this HITL gate
        if os.environ.get("CAM_USE_TEMPORAL", "true").lower() == "true":
            import asyncio as _asyncio
            import pathlib as _pathlib
            sys.path.insert(0, str(_pathlib.Path(__file__).parent.parent / "temporal_worker"))
            try:
                import client as temporal_client
                _asyncio.run(temporal_client.send_hitl_approve(rfq_id, {
                    "gate": "detect_alternates",
                    "resolved_count": len(request.selections),
                }))
                print(f"[TEMPORAL SIGNAL] sent human_decision approve (detect_alternates) for rfq_id={rfq_id!r}")
                signal_delivered = True
            except Exception as sig_err:
                # Signal failure is non-fatal: rfq_process_stage already advanced above.
                print(f"[TEMPORAL SIGNAL ERROR] {sig_err}")
                signal_delivered = False

    return {
        "status": "success",
        "rfq_id": rfq_id,
        "resolved_count": len(request.selections),
        "remaining": remaining,
        "fully_approved": fully_approved,
        "signal_delivered": signal_delivered,
    }


class HITLDecisionRequest(BaseModel):
    approved: bool
    stage: str = "Intake"


@app.post("/api/rfq/{rfq_id}/hitl/decision")
def hitl_decision(rfq_id: str, request: HITLDecisionRequest):
    """Generic HITL approve/reject called by the daemon's hitl:submit-decision IPC.
    Sends the Temporal human_decision signal and clears the hitl_required flag.
    """
    use_temporal = os.environ.get("CAM_USE_TEMPORAL", "true").lower() == "true"
    if use_temporal:
        import asyncio as _asyncio
        import pathlib as _pathlib
        sys.path.insert(0, str(_pathlib.Path(__file__).parent.parent / "temporal_worker"))
        try:
            import client as temporal_client
            if request.approved:
                _asyncio.run(temporal_client.send_hitl_approve(rfq_id, {"gate": request.stage, "approved": True}))
            else:
                _asyncio.run(temporal_client.send_hitl_reject(rfq_id, f"Rejected at stage={request.stage}"))
            print(f"[TEMPORAL SIGNAL] hitl/decision approved={request.approved} for rfq_id={rfq_id!r}")
        except Exception as sig_err:
            print(f"[TEMPORAL SIGNAL ERROR] hitl/decision: {sig_err}")
            # The decision never reached the workflow: report it, do not answer "ok".
            raise HTTPException(status_code=502, detail=f"HITL decision not delivered to the workflow: {sig_err}")

    return {"status": "ok", "rfq_id": rfq_id, "approved": request.approved}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5102)
