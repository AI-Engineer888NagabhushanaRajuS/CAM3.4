# [BuLLMQuote-SRIM MIGRATION NOTE -- added on copy, updated after reporting_module migrated]
# UPDATE: reporting_module has been migrated to mcp-tools/reporting/superset/;
# the sys.path insert below now points there, so `import database`/
# `import final_selection`/`import config as reporting_config`/
# `import helpers as reporting_helpers` all resolve and import successfully --
# verified, including the config.py name-collision (this folder also has its
# own config.py; the insert order below makes reporting_module's win, which
# is what's needed here).
# STILL BROKEN at the point of actually USING them: reporting_module's config.py
# resolves DB paths relative to itself (`../database`), which from
# mcp-tools/reporting/superset/ does not reach this repo's `database/` (not yet
# migrated -- see database/README.md and
# mcp-tools/reporting/superset/config.py's own migration note). Endpoints here
# that call into reporting_database/final_selection will fail at the DB
# connection, not at import time, until database/ is migrated into this repo
# or REPORTING_DATABASE_DIR is set to point at `centum intake\database\` directly.
# [END MIGRATION NOTE]

import os
import re
import sys
import glob
import io
import json
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
import duckdb
import openpyxl
from typing import Any, Optional
from fastapi.middleware.cors import CORSMiddleware

import auth

# centum intake's reporting_module owns the cbom.duckdb connection pattern
# (ATTACH cbom_db / input_db onto reports.duckdb) -- reused here rather than
# opening cbom.duckdb with a bare duckdb.connect(), which would be missing
# the cbom_db schema alias final_selection.py's SQL expects.
_CENTUM_INTAKE_DIR = os.path.dirname(os.path.abspath(__file__))
# [BuLLMQuote-SRIM] Updated for the new layout -- see migration note above.
_REPORTING_MODULE_DIR = os.path.join(_CENTUM_INTAKE_DIR, "..", "mcp-tools", "reporting", "superset")
# mcp-tools/shared -- the single cross-export highlight color constant
# (MANUAL_EDIT_FILL_ARGB), also used by export_bom.py/quote_summary.py.
_MCP_SHARED_DIR = os.path.join(_CENTUM_INTAKE_DIR, "..", "mcp-tools", "shared")
for _dir in (_CENTUM_INTAKE_DIR, _REPORTING_MODULE_DIR, _MCP_SHARED_DIR):
    if _dir not in sys.path:
        sys.path.insert(0, _dir)

import database as reporting_database
import final_selection
import config as reporting_config
import helpers as reporting_helpers
from db import (
    get_active_version, versioned_key, get_routing_sequence,
    advance_skill_index_to_at_least, increment_skill_index, set_hitl_required,
    duckdb_file_lock, get_metadata_connection,
)
from highlight_style import MANUAL_EDIT_FILL_ARGB


def _resolve_cbom_key(rfq_id: str) -> str:
    """Every cbom_db.cbom query/update here must scope by the ACTIVE version's
    key, not the bare canonical rfq_id -- otherwise BOM preview/save/export
    would silently operate on whichever version happens to share that bare
    rfq_id string, rather than the one the user is currently looking at.

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


app = FastAPI()

# The final_* fields a reviewer may edit on the costed BOM preview --
# everything else in a preview row is context and stays read-only.
EDITABLE_FIELDS = [
    "final_mfg_name",
    "final_unit_of_measure",
    "final_price_conv",
    "final_price_original",
    "final_currency_original",
    "final_supp_name",
    "final_pkg_qty",
    "final_moq",
    "final_lead_time",
]

# RFQ_Flow's stage-7 preview equivalent of EDITABLE_FIELDS above -- unlike
# Standard_BOM_Flow's cbom.duckdb, processed_bom_items has no multi-source
# "final_*" concept, so both the raw intake fields (in case of a data-entry
# mistake caught this late) and the enrichment-stage distributor-selection
# fields (selected_supplier/selected_unit_price/selected_moq/
# selected_currency -- see enrichment.py's select_best_distributor_price(),
# the one place that value is normally set) are editable here.
RFQ_EDITABLE_FIELDS = [
    "fg",
    "parent_fg",
    "cpn",
    "mpn",
    "mfr",
    "description",
    "commodity",
    "bom_qty",
    "required_qty",
    "uom",
    "part_type",
    "selected_supplier",
    "selected_unit_price",
    "selected_moq",
    "selected_currency",
]

PREVIEW_COLUMNS = [
    "cbom_item_id", "bom_item_id", "volume_no", "fg", "cpn", "description", "commodity",
    "final_mfg_name", "mfg_part_number", "final_unit_of_measure", "part_qty",
    "final_price_conv", "final_price_original", "final_currency_original",
    "final_supp_name", "final_pkg_qty", "final_moq", "final_lead_time",
    "is_costed", "abc_classification", "price_control",
]

app.add_middleware(
      CORSMiddleware,
      allow_origins=["*"],
      allow_credentials=True,
      allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
      allow_headers=["*"],
      expose_headers=["*"],
  )


class TokenRequest(BaseModel):
    rfq_id: str | None = None
    # FDE Staging Pipeline's own claim -- mutually exclusive with rfq_id;
    # reuses this same endpoint/JWT scheme rather than a second one. See
    # auth.py's create_token()/claim_name for why one scheme covers both.
    project_id: str | None = None


@app.post("/auth/token")
def issue_token(body: TokenRequest):
    """Mints a 60-second JWT scoped to whichever subject the caller sent --
    rfq_id (production, the default/every existing caller) or project_id
    (FDE Staging Pipeline). The frontend/daemon call this immediately
    before every real request to duck_db_api.py/upload_server.py/
    hitl_router.py, since tokens are deliberately too short-lived to reuse
    across separate calls. See auth.py's own module docstring for the full
    contract."""
    if body.project_id is not None:
        return {"token": auth.create_token(body.project_id, claim_name="project_id")}
    if body.rfq_id is None:
        raise HTTPException(status_code=422, detail="Request body must include either rfq_id or project_id")
    return {"token": auth.create_token(body.rfq_id)}


@app.get("/api/bom/preview/{rfq_id}")
def get_preview_data(
    rfq_id: str,
    token: dict = Depends(auth.verify_token),
    volume_no: Optional[int] = None,
    cursor_fg: Optional[str] = None,
    cursor_cpn: Optional[str] = None,
    cursor_id: Optional[str] = None,
    limit: int = Query(default=200, le=1000),
):
    """FG-wise (ordered by fg, cpn) paginated costed BOM preview for one rfq_id +
    volume_no, read from centum intake's cbom.duckdb. Cursor is a 3-part tuple
    (fg, cpn, cbom_item_id) since the primary sort key is (fg, cpn), not
    cbom_item_id alone -- pass back the last row's fg/cpn/cbom_item_id as
    cursor_fg/cursor_cpn/cursor_id to fetch the next page.
    """
    cbom_key = _resolve_cbom_key(rfq_id)
    with duckdb_file_lock():
        con = reporting_database.connect()
        try:
            if volume_no is None:
                row = con.execute(
                    "SELECT MIN(volume_no) FROM cbom_db.cbom WHERE rfq_id = ?", [cbom_key]
                ).fetchone()
                volume_no = row[0] if row and row[0] is not None else 1

            columns_sql = ", ".join(PREVIEW_COLUMNS)

            if cursor_fg is not None and cursor_cpn is not None and cursor_id is not None:
                query = f"""
                    SELECT {columns_sql} FROM cbom_db.cbom
                    WHERE rfq_id = ? AND volume_no = ?
                      AND (fg, cpn, CAST(cbom_item_id AS VARCHAR)) > (?, ?, ?)
                    ORDER BY fg, cpn, cbom_item_id
                    LIMIT ?
                """
                params = [cbom_key, volume_no, cursor_fg, cursor_cpn, cursor_id, limit]
            else:
                query = f"""
                    SELECT {columns_sql} FROM cbom_db.cbom
                    WHERE rfq_id = ? AND volume_no = ?
                    ORDER BY fg, cpn, cbom_item_id
                    LIMIT ?
                """
                params = [cbom_key, volume_no, limit]

            try:
                rows = con.execute(query, params).fetchall()
                col_names = [d[0] for d in con.description]
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        finally:
            con.close()

    items = [dict(zip(col_names, row)) for row in rows]
    # Cast UUID/date-ish values to strings so this is trivially JSON-serializable
    # for the frontend -- it only ever displays/round-trips these, never
    # interprets their type.
    for item in items:
        for key, value in item.items():
            if not isinstance(value, (str, int, float, bool, type(None))):
                item[key] = str(value)

    last = items[-1] if items else None
    next_cursor = (
        {"cursor_fg": last["fg"], "cursor_cpn": last["cpn"], "cursor_id": last["cbom_item_id"]}
        if last and len(items) == limit
        else None
    )

    return {
        "success": True,
        "rfq_id": rfq_id,
        "volume_no": volume_no,
        "row_count": len(items),
        "data": items,
        "next_cursor": next_cursor,
    }


@app.put("/api/bom/batch-update/{rfq_id}")
def batch_update_bom(rfq_id: str, updates: list[dict[str, Any]], token: dict = Depends(auth.verify_token)):
    """Applies inline cell edits (full row snapshots, keyed by bom_item_id) to
    cbom.duckdb's final_* columns, then recomputes the derived columns
    (is_costed/scrap_percent/abc_classification/etc.) via
    final_selection.recompute_derived_columns -- the same function
    hitl_router.py already uses for the same purpose.
    """
    if not updates:
        raise HTTPException(status_code=400, detail="No rows provided for update.")

    cbom_key = _resolve_cbom_key(rfq_id)
    with duckdb_file_lock():
        con = reporting_database.connect()
        try:
            con.execute("BEGIN TRANSACTION")
            updated_count = 0
            for row in updates:
                bom_item_id = row.get("bom_item_id")
                volume_no = row.get("volume_no")
                if not bom_item_id:
                    continue

                set_clauses = []
                values = []
                for field in EDITABLE_FIELDS:
                    if field in row:
                        set_clauses.append(f"{field} = ?")
                        values.append(row[field])

                if not set_clauses:
                    continue

                where_clause = "bom_item_id = ? AND rfq_id = ?"
                values.extend([bom_item_id, cbom_key])
                if volume_no is not None:
                    where_clause += " AND volume_no = ?"
                    values.append(volume_no)

                con.execute(
                    f"UPDATE cbom_db.cbom SET {', '.join(set_clauses)} WHERE {where_clause}",
                    values,
                )
                updated_count += 1

            final_selection.recompute_derived_columns(con, cbom_key)
            con.execute("COMMIT")
        except Exception as e:
            con.execute("ROLLBACK")
            con.close()
            raise HTTPException(status_code=500, detail=str(e))

        con.close()
    return {"success": True, "rfq_id": rfq_id, "rows_updated": updated_count}


def _find_latest_export(cbom_key: str) -> Optional[str]:
    """Locates the most recently generated CBOM export workbook for a
    (version-resolved) cbom_key -- reuses reporting_module's own slugify() so
    the glob pattern always matches exactly how exporter.py names the file
    (CBOM_Report_<cbom_key>_<timestamp>.xlsx), rather than re-deriving that
    naming rule here. Takes the ALREADY-VERSIONED key (not a bare rfq_id):
    fastapi_router.py's /tool/execute rewrites export_reports' rfq_id argument
    to this same versioned key before calling exporter.export_excel(), so the
    exported filename is already based on it -- different versions of the
    same RFQ therefore never collide or get confused for one another on disk.
    """
    pattern = os.path.join(
        reporting_config.EXPORTS_DIR,
        f"CBOM_Report_{reporting_helpers.slugify(cbom_key)}_*.xlsx",
    )
    matches = glob.glob(pattern)
    if not matches:
        return None
    return max(matches, key=os.path.getmtime)


# distributor_pricing's export_bom() writes here (same directory as its own
# mcp_server.py) -- see export_bom.py's TEMPLATE_PATH/output_path. Filename
# convention: Distributor_Verification_Output_<rfq_slug>_<timestamp>.xlsx.
# [BuLLMQuote-SRIM MIGRATION NOTE -- fixed 2026-08-11] Was hardcoded to the
# old SRIM\Tools\I n D\distributor_pricing location -- export_bom.py now
# writes into this repo's own mcp-tools/distributor-pricing/, so this lookup
# was silently 404-ing on every RFQ_Flow export made through this repo.
_DISTRIBUTOR_PRICING_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "mcp-tools", "distributor-pricing"
)


def _find_latest_rfqflow_export(rfq_id: str) -> Optional[str]:
    """RFQ_Flow's own export lookup, parallel to _find_latest_export() but for
    distributor_pricing's own outputs instead of the old Standard_BOM_Flow's
    cbom_db-generated workbook -- the two pipelines write to entirely
    different files/schemas, so this never touches _find_latest_export or its
    cbom_key resolution.

    RFQ_Flow now has TWO export tools writing two different files:
    export_enriched_bom (Distributor_Verification_Output_<slug>_<ts>.xlsx,
    this directory) and export_quote_summary (Quote_Summary_<rfq_id>_<ts>.xlsx,
    quote_summary.py's own quote_exports/ subdirectory -- both single-source
    priced, but export_quote_summary additionally carries the hierarchical
    "Final Structured BoM" sheet and runs LAST in routing_sequence). Globs
    both and returns the overall most recent -- previously only the first
    pattern was checked at all, so this endpoint kept serving the older
    flat-template file even after export_quote_summary had already produced
    a newer, richer one for the same RFQ.
    """
    rfq_slug = re.sub(r"[^A-Za-z0-9_\-]+", "_", rfq_id).strip("_")
    patterns = [
        os.path.join(
            _DISTRIBUTOR_PRICING_DIR,
            f"Distributor_Verification_Output_{rfq_slug}_*.xlsx",
        ),
        # quote_summary.py's build_quote_summary() names its output from the
        # raw (stripped, not slugified) rfq_id -- matched here as-is rather
        # than via rfq_slug, which could differ for an rfq_id containing
        # characters slugification would rewrite.
        os.path.join(
            _DISTRIBUTOR_PRICING_DIR, "quote_exports", f"Quote_Summary_{rfq_id.strip()}_*.xlsx"
        ),
    ]
    matches = [m for pattern in patterns for m in glob.glob(pattern)]
    if not matches:
        return None
    return max(matches, key=os.path.getmtime)


def _find_latest_rfqflow_verification_export(rfq_id: str) -> Optional[str]:
    """Just the Distributor_Verification_Output_<slug>_<ts>.xlsx pattern --
    used by download_cbom_only_export() below, which needs RFQ_Flow's
    per-part consolidated/priced view specifically (its analog of
    Standard_BOM_Flow's single "CBOM" sheet), not whichever of the two
    RFQ_Flow export types happens to be newest (_find_latest_rfqflow_export()
    above deliberately returns either, for the "download the latest export,
    whatever it is" main button -- the wrong choice here, since
    export_quote_summary always runs after export_enriched_bom and would
    otherwise always win, silently serving the Quote summary instead of the
    consolidated BOM this specific button is for).
    """
    rfq_slug = re.sub(r"[^A-Za-z0-9_\-]+", "_", rfq_id).strip("_")
    pattern = os.path.join(
        _DISTRIBUTOR_PRICING_DIR,
        f"Distributor_Verification_Output_{rfq_slug}_*.xlsx",
    )
    matches = glob.glob(pattern)
    if not matches:
        return None
    return max(matches, key=os.path.getmtime)


def _find_latest_quote_summary_export(rfq_id: str) -> Optional[str]:
    """Just the Quote_Summary_<rfq_id>_<ts>.xlsx pattern (quote_summary.py's
    own output -- the "Quote" + "Final Structured BoM" workbook) -- the
    deterministic counterpart to _find_latest_rfqflow_verification_export()
    above, so a "download the final quote" button always gets that file
    specifically, never "whichever export happens to be newest."
    """
    pattern = os.path.join(
        _DISTRIBUTOR_PRICING_DIR, "quote_exports", f"Quote_Summary_{rfq_id.strip()}_*.xlsx"
    )
    matches = glob.glob(pattern)
    if not matches:
        return None
    return max(matches, key=os.path.getmtime)


@app.get("/api/bom/export-quote/{rfq_id}/download")
def download_quote_summary_export(rfq_id: str):
    """RFQ_Flow-only: always serves the Quote summary workbook specifically,
    as a deterministic counterpart to download_cbom_only_export() (always the
    consolidated BOM) -- the two download buttons StageExecutionOutput.tsx
    now renders side by side for RFQ_Flow's priceDecision/rfqBomPreview stage.

    Deliberately NOT gated by auth.verify_token (user's explicit decision,
    2026-09-02): App.tsx's Quote Readiness panel links to this endpoint via
    a plain `window.open(url)`, which cannot attach a custom Authorization
    header -- rather than rework that panel to fetch+blob+anchor-click (the
    pattern StageExecutionOutput.tsx's equivalent buttons use), this route
    and its two siblings below stay unauthenticated for every caller.
    """
    latest_path = _find_latest_quote_summary_export(rfq_id)
    if latest_path is None:
        raise HTTPException(status_code=404, detail=f"No quote summary export found for rfq_id={rfq_id!r}")

    return FileResponse(
        latest_path,
        filename=os.path.basename(latest_path),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.get("/api/bom/export/{rfq_id}")
def get_latest_export(rfq_id: str, token: dict = Depends(auth.verify_token)):
    """Metadata for the most recent generated report -- lets the frontend show
    a 'Download <filename>' link once export_reports has actually run, without
    guessing the filename/timestamp itself.

    Tries the old Standard_BOM_Flow cbom-based export first (unchanged
    behavior), then falls back to RFQ_Flow's own export_enriched_bom output --
    the two never coexist for the same rfq_id, so this is a safe either/or.
    """
    latest_path = _find_latest_export(_resolve_cbom_key(rfq_id)) or _find_latest_rfqflow_export(rfq_id)
    if latest_path is None:
        raise HTTPException(status_code=404, detail=f"No export found for rfq_id={rfq_id!r}")

    return {
        "success": True,
        "rfq_id": rfq_id,
        "filename": os.path.basename(latest_path),
        "generated_at": datetime.fromtimestamp(os.path.getmtime(latest_path)).isoformat(),
    }


def _export_artifact(path: Optional[str]) -> Optional[dict]:
    if path is None:
        return None
    return {
        "filename": os.path.basename(path),
        "generated_at": datetime.fromtimestamp(os.path.getmtime(path)).isoformat(),
    }


@app.get("/api/bom/export-status/{rfq_id}")
def get_export_status(rfq_id: str, token: dict = Depends(auth.verify_token)):
    """Reports existence/metadata for every known export artifact type for
    this rfq_id, without attempting a download -- lets the frontend show the
    right download button(s) any time an RFQ is opened/reopened, not just
    right after a live run finishes. Unlike get_latest_export/
    download_latest_export above, this always returns 200: "no export exists
    yet" is a normal, valid status for an RFQ that hasn't reached export, not
    an error to raise on.

    Standard_BOM_Flow and RFQ_Flow never coexist for the same rfq_id (same
    assumption get_latest_export makes above), but RFQ_Flow itself produces
    TWO distinct files (export_enriched_bom's Consolidated BOM and
    export_quote_summary's Final Quote) -- reported as separate fields so the
    frontend can offer both independently, exactly like
    download_cbom_only_export/download_quote_summary_export already serve
    them separately.
    """
    return {
        "success": True,
        "rfq_id": rfq_id,
        "cbom": _export_artifact(_find_latest_export(_resolve_cbom_key(rfq_id))),
        "consolidatedBom": _export_artifact(_find_latest_rfqflow_verification_export(rfq_id)),
        "quoteSummary": _export_artifact(_find_latest_quote_summary_export(rfq_id)),
    }


@app.get("/api/bom/export/{rfq_id}/download")
def download_latest_export(rfq_id: str):
    """Streams the same workbook get_latest_export() describes, as an actual
    file download (Content-Disposition: attachment).

    Deliberately NOT gated by auth.verify_token -- same reasoning as
    download_quote_summary_export above (App.tsx's Quote Readiness panel
    reaches this via window.open, which can't send an Authorization header).
    """
    latest_path = _find_latest_export(_resolve_cbom_key(rfq_id)) or _find_latest_rfqflow_export(rfq_id)
    if latest_path is None:
        raise HTTPException(status_code=404, detail=f"No export found for rfq_id={rfq_id!r}")

    return FileResponse(
        latest_path,
        filename=os.path.basename(latest_path),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.get("/api/bom/export-cbom/{rfq_id}/download")
def download_cbom_only_export(rfq_id: str):
    """Deliberately NOT gated by auth.verify_token -- same reasoning as
    download_quote_summary_export above (App.tsx's Quote Readiness panel
    reaches this via window.open, which can't send an Authorization header).

    Finalize Price (stage 7) shows a CBOM-only export, distinct from the
    full 16-report bundle Quote Readiness downloads. Rather than re-running
    any queries, this strips every sheet but "CBOM" out of the *already
    generated* combined workbook (same file _find_latest_export locates for
    the other two endpoints) -- in-memory only, no temp files on disk.

    RFQ_Flow has no "CBOM" sheet to strip down to (never had a
    Standard_BOM_Flow-style combined workbook at all) -- its own analog of
    this stage's "single consolidated view" is export_enriched_bom's
    Distributor_Verification_Output file, which is already single-purpose,
    so it's served as-is on fallback rather than sheet-stripped. Previously
    this endpoint had NO RFQ_Flow fallback at all, so it 404'd for every
    RFQ_Flow rfq_id -- confirmed: "No export found" even after
    export_enriched_bom had already produced a real file.
    """
    latest_path = _find_latest_export(_resolve_cbom_key(rfq_id))
    if latest_path is not None:
        wb = openpyxl.load_workbook(latest_path)
        if "CBOM" not in wb.sheetnames:
            raise HTTPException(status_code=404, detail="CBOM sheet not found in the generated report")

        for sheet_name in list(wb.sheetnames):
            if sheet_name != "CBOM":
                del wb[sheet_name]

        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)

        filename = os.path.basename(latest_path).replace(".xlsx", "_CBOM_ONLY.xlsx")
        return StreamingResponse(
            buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    rfqflow_path = _find_latest_rfqflow_verification_export(rfq_id)
    if rfqflow_path is None:
        raise HTTPException(status_code=404, detail=f"No export found for rfq_id={rfq_id!r}")

    return FileResponse(
        rfqflow_path,
        filename=os.path.basename(rfqflow_path),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ============================================================
# RFQ_Flow: distributor__detect_alternates review UI
#
# Backs the pre-built alternates/pricingSources grid in
# StageExecutionOutput.tsx (AlternateGroup/AlternateCandidate/AlternateSupplier
# types there) -- that UI predates this backend; the shapes below conform to
# what it already fetches/renders rather than the other way around. Lives on
# this service (not hitl_router.py) because that's what the frontend already
# calls (PYTHON_BRIDGE, not HITL_BRIDGE) for this specific grid.
#
# Data lives entirely in bom_storage.duckdb's update_alternatives/
# processed_bom_items tables, keyed by the bare rfq_id (no versioned_key() --
# see intake/bom_to_database.py and distributor_pricing/detect_alternates.py,
# neither of which version-scope their inserts).
# ============================================================

BOM_STORAGE_DB_PATH = os.environ.get("BOM_STORAGE_DB", r"C:\SRIM-DB-SETUP\Databases\bom_storage.duckdb")
_DETECT_ALTERNATES_TOOL = "distributor__detect_alternates"

# (our column prefix, display name shown in the Suppliers column)
_SUPPLIER_COLUMNS = [
    ("digikey", "DigiKey"),
    ("mouser", "Mouser"),
    ("element14", "Element14"),
]


def _advance_past_detect_alternates(rfq_id: str) -> int:
    """Mirrors hitl_router.py's _advance_past_resolve_final_selection, but for
    RFQ_Flow's detect_alternates position -- see that function's docstring
    for why a routing-sequence-relative advance is used instead of a blind +1.

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


def _clean(val):
    """pandas/duckdb NaN for an unmatched distributor field is not valid JSON
    (json.dumps raises ValueError: "Out of range float values are not JSON
    compliant: nan") -- normalize to None/absent instead."""
    if val is None:
        return None
    try:
        import math
        if isinstance(val, float) and math.isnan(val):
            return None
    except (TypeError, ValueError):
        pass
    return val


def _remaining_cpns(con, rfq_id: str) -> int:
    """A CPN counts as unresolved unless exactly one of its alternate MPN rows
    has preferred_flag=TRUE -- matches apply_alternatives.py's own
    all-or-nothing validation exactly."""
    row = con.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT cpn
            FROM update_alternatives
            WHERE rfq_id = ?
            GROUP BY cpn
            HAVING SUM(CASE WHEN preferred_flag THEN 1 ELSE 0 END) != 1
        )
        """,
        [rfq_id]
    ).fetchone()
    return row[0] if row else 0


@app.get("/api/bom/alternatives/{rfq_id}")
def get_alternatives(rfq_id: str, token: dict = Depends(auth.verify_token)):
    """Every alternate-MPN group for this rfq_id, each candidate carrying its
    real digikey_unit_price/digikey_stock/etc (already captured by
    distributor__enrich_bom) reshaped into the frontend's suppliers[] array."""
    con = duckdb.connect(BOM_STORAGE_DB_PATH, read_only=True)
    try:
        rows = con.execute(
            """
            SELECT
                ua.cpn, ua.mpn, ua.mfr, ua.bom_item_id, ua.preferred_flag,
                p.description, p.required_qty,
                p.digikey_unit_price, p.digikey_moq, p.digikey_lead_time, p.digikey_stock,
                p.mouser_unit_price, p.mouser_moq, p.mouser_lead_time, p.mouser_stock,
                p.element14_unit_price, p.element14_moq, p.element14_lead_time, p.element14_stock
            FROM update_alternatives ua
            LEFT JOIN processed_bom_items p
                ON p.rfq_id = ua.rfq_id AND p.cpn = ua.cpn AND p.mpn = ua.mpn
            WHERE ua.rfq_id = ?
            ORDER BY ua.cpn, ua.mpn
            """,
            [rfq_id]
        ).fetchall()
        col_names = [d[0] for d in con.description]
    except duckdb.CatalogException:
        # update_alternatives is created by distributor__detect_alternates; a profile without that step has none.
        rows, col_names = [], []
    finally:
        con.close()

    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        r = dict(zip(col_names, row))

        suppliers = []
        for prefix, label in _SUPPLIER_COLUMNS:
            price = _clean(r.get(f"{prefix}_unit_price"))
            stock = _clean(r.get(f"{prefix}_stock"))
            moq = _clean(r.get(f"{prefix}_moq"))
            lead_time = _clean(r.get(f"{prefix}_lead_time"))
            if price is None and stock is None:
                continue
            suppliers.append({"supplier": label, "price": price, "moq": moq, "lead_time": lead_time, "stock": stock})

        candidate = {
            "mpn": r["mpn"],
            "manufacturer": _clean(r.get("mfr")),
            "bom_item_id": str(r["bom_item_id"]) if r.get("bom_item_id") is not None else None,
            "is_preferred": bool(r["preferred_flag"]),
            "description": _clean(r.get("description")),
            "suppliers": suppliers,
        }

        group = groups.setdefault(r["cpn"], {"cpn": r["cpn"], "required_qty": None, "alternates": []})
        if group["required_qty"] is None:
            group["required_qty"] = _clean(r.get("required_qty"))
        group["alternates"].append(candidate)

    return {"success": True, "rfq_id": rfq_id, "data": list(groups.values())}


class AlternateSelectRequest(BaseModel):
    cpn: str
    mpn: str


@app.put("/api/bom/alternatives/{rfq_id}/select")
def select_alternative(rfq_id: str, request: AlternateSelectRequest, token: dict = Depends(auth.verify_token)):
    """Sets the chosen MPN as preferred for its CPN (clearing every other
    candidate in that same group), matching the frontend's instant-persist
    radio-select UX -- one call per click, not a batch submit. Once every CPN
    group for this rfq_id has exactly one preferred_flag=TRUE, advances
    rfq_process_stage past distributor__detect_alternates so a later
    GET /api/dify/start/{rfq_id} (triggered by "Clear & Resume Pipeline" via
    the daemon's hitl:submit-decision RPC) resumes into
    distributor__apply_alternatives instead of re-running detect_alternates."""
    con = duckdb.connect(BOM_STORAGE_DB_PATH, read_only=False)
    try:
        exists = con.execute(
            "SELECT COUNT(*) FROM update_alternatives WHERE rfq_id = ? AND cpn = ? AND mpn = ?",
            [rfq_id, request.cpn, request.mpn]
        ).fetchone()[0]
        if not exists:
            raise HTTPException(
                status_code=404,
                detail=f"No alternate row for rfq_id={rfq_id!r} cpn={request.cpn!r} mpn={request.mpn!r}"
            )

        con.execute("BEGIN TRANSACTION")
        try:
            con.execute(
                "UPDATE update_alternatives SET preferred_flag = FALSE, updated_at = CURRENT_TIMESTAMP WHERE rfq_id = ? AND cpn = ?",
                [rfq_id, request.cpn]
            )
            con.execute(
                "UPDATE update_alternatives SET preferred_flag = TRUE, updated_at = CURRENT_TIMESTAMP WHERE rfq_id = ? AND cpn = ? AND mpn = ?",
                [rfq_id, request.cpn, request.mpn]
            )
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise

        remaining = _remaining_cpns(con, rfq_id)
    finally:
        con.close()

    fully_approved = False
    if remaining == 0:
        _advance_past_detect_alternates(rfq_id)
        fully_approved = True

    return {"success": True, "rfq_id": rfq_id, "cpn": request.cpn, "mpn": request.mpn, "remaining": remaining, "fully_approved": fully_approved}


# ============================================================
# RFQ_Flow: stage 7 (priceDecision) -- review the finalized,
# deduplicated BOM after distributor__apply_alternatives, before
# distributor__export_enriched_bom runs. Deliberately its own endpoint
# rather than reusing /api/bom/preview/{rfq_id} above -- that one reads
# cbom_db.cbom (Standard_BOM_Flow's multi-source-reconciled 103-column CBOM),
# a completely different schema RFQ_Flow never populates. RFQ_Flow has no
# equivalent multi-source "final_*" concept -- each cpn has exactly one row
# left after apply_alternatives, but that row can still carry live prices
# from up to 3 suppliers at once, so "best_price"/"best_supplier" below is a
# deterministic (lowest-price) choice recomputed here for display, shown
# alongside the real, persisted selected_* columns (enrichment.py's own
# earlier pick -- see select_best_distributor_price()) which a reviewer can
# now override via PUT /api/bom/batch-update-rfq/{rfq_id} below, same as
# Standard_BOM_Flow's final_* columns.
# ============================================================

_APPLY_ALTERNATIVES_TOOL = "distributor__apply_alternatives"


def _advance_past_apply_alternatives(rfq_id: str) -> int:
    """Mirrors _advance_past_detect_alternates -- see that function's
    docstring. Called once the user approves the stage-7 preview, so a
    resumed Dify run proceeds into distributor__export_enriched_bom instead
    of re-running apply_alternatives."""
    try:
        routing_sequence = get_routing_sequence("RFQ_Flow")
        target_index = routing_sequence.index(_APPLY_ALTERNATIVES_TOOL) + 1
        new_stage = advance_skill_index_to_at_least(rfq_id, target_index)
        print(f"[RFQ PREVIEW] advanced past apply_alternatives (index {target_index - 1}) -- rfq_process_stage={new_stage}")
    except Exception as e:
        print(f"[RFQ PREVIEW ERROR] Could not resolve routing sequence, falling back to +1: {e}")
        new_stage = increment_skill_index(rfq_id)

    try:
        set_hitl_required(rfq_id, False)
    except Exception as e:
        print(f"[HITL STATE ERROR] Could not clear hitl_required: {e}")

    return new_stage


def _ensure_manually_edited_column(con):
    """Idempotent, additive -- same convention as bom_to_database.py's
    _ensure_structure_table(). manually_edited_fields is a JSON-encoded array
    of column names a human has EVER manually corrected on this row (sticky:
    never cleared just because a later edit happens to match the original
    value again) -- the single persisted source of truth every consumer
    (live grid reload, client-side download, the real pipeline exports)
    reads to decide what to highlight yellow."""
    existing = {
        row[0].lower()
        for row in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'processed_bom_items'"
        ).fetchall()
    }
    if "manually_edited_fields" not in existing:
        con.execute("ALTER TABLE processed_bom_items ADD COLUMN manually_edited_fields VARCHAR")


@app.get("/api/bom/rfq-preview/{rfq_id}")
def get_rfq_preview(rfq_id: str, token: dict = Depends(auth.verify_token)):
    """Every processed_bom_items row for this rfq_id, post-dedup (one row per
    cpn) -- the finalized, distributor-priced BOM RFQ_Flow actually produces,
    shown for review before export."""
    con = duckdb.connect(BOM_STORAGE_DB_PATH, read_only=False)
    try:
        _ensure_manually_edited_column(con)
        rows = con.execute(
            """
            SELECT
                bom_item_id, fg, parent_fg, cpn, mpn, mfr, description, commodity,
                bom_qty, required_qty, uom, part_type,
                digikey_unit_price, digikey_moq, digikey_lead_time, digikey_stock,
                mouser_unit_price, mouser_moq, mouser_lead_time, mouser_stock,
                element14_unit_price, element14_moq, element14_lead_time, element14_stock,
                selected_supplier, selected_unit_price, selected_moq, selected_currency,
                manually_edited_fields
            FROM processed_bom_items
            WHERE rfq_id = ?
            ORDER BY fg, cpn
            """,
            [rfq_id]
        ).fetchall()
        col_names = [d[0] for d in con.description]
    finally:
        con.close()

    data = []
    for row in rows:
        r = dict(zip(col_names, row))
        candidates = [
            (_clean(r.get(f"{prefix}_unit_price")), label, r.get(f"{prefix}_moq"), r.get(f"{prefix}_lead_time"))
            for prefix, label in _SUPPLIER_COLUMNS
        ]
        priced = [c for c in candidates if c[0] is not None]
        best_price, best_supplier, best_moq, best_lead_time = min(priced, key=lambda c: c[0]) if priced else (None, None, None, None)

        try:
            edited_fields = json.loads(r.get("manually_edited_fields") or "[]")
        except (json.JSONDecodeError, TypeError):
            edited_fields = []

        data.append({
            "bom_item_id": str(r["bom_item_id"]) if r.get("bom_item_id") is not None else None,
            "fg": _clean(r.get("fg")),
            "parent_fg": _clean(r.get("parent_fg")),
            "cpn": r["cpn"],
            "mpn": r["mpn"],
            "manufacturer": _clean(r.get("mfr")),
            "description": _clean(r.get("description")),
            "commodity": _clean(r.get("commodity")),
            "bom_qty": _clean(r.get("bom_qty")),
            "required_qty": _clean(r.get("required_qty")),
            "uom": _clean(r.get("uom")),
            "part_type": _clean(r.get("part_type")),
            "best_price": best_price,
            "best_supplier": best_supplier,
            "best_moq": _clean(best_moq),
            "best_lead_time": _clean(best_lead_time),
            "selected_supplier": _clean(r.get("selected_supplier")),
            "selected_unit_price": _clean(r.get("selected_unit_price")),
            "selected_moq": _clean(r.get("selected_moq")),
            "selected_currency": _clean(r.get("selected_currency")),
            "_edited_fields": edited_fields,
        })

    return {"success": True, "rfq_id": rfq_id, "data": data}


@app.put("/api/bom/batch-update-rfq/{rfq_id}")
def batch_update_rfq_preview(rfq_id: str, updates: list[dict[str, Any]], token: dict = Depends(auth.verify_token)):
    """RFQ_Flow's counterpart to batch_update_bom() above -- applies inline
    cell edits (full row snapshots, keyed by bom_item_id) to
    processed_bom_items' RFQ_EDITABLE_FIELDS columns. No recompute step
    afterwards: unlike cbom_db.cbom, processed_bom_items has no derived/
    computed columns depending on these fields.

    Also unions the touched field names into manually_edited_fields (sticky,
    dedup, never drops a previously-recorded field even across separate save
    actions) -- the persisted "which cells were manually edited" signal
    get_rfq_preview returns and every export reads."""
    if not updates:
        raise HTTPException(status_code=400, detail="No rows provided for update.")

    con = duckdb.connect(BOM_STORAGE_DB_PATH, read_only=False)
    try:
        _ensure_manually_edited_column(con)
        con.execute("BEGIN TRANSACTION")
        updated_count = 0
        for row in updates:
            bom_item_id = row.get("bom_item_id")
            if not bom_item_id:
                continue

            touched_fields = [field for field in RFQ_EDITABLE_FIELDS if field in row]
            if not touched_fields:
                continue

            existing_row = con.execute(
                "SELECT manually_edited_fields FROM processed_bom_items WHERE bom_item_id = ? AND rfq_id = ?",
                [bom_item_id, rfq_id],
            ).fetchone()
            try:
                existing_edited = json.loads(existing_row[0]) if existing_row and existing_row[0] else []
            except (json.JSONDecodeError, TypeError):
                existing_edited = []
            merged_edited = sorted(set(existing_edited) | set(touched_fields))

            set_clauses = [f"{field} = ?" for field in touched_fields]
            values = [row[field] for field in touched_fields]
            set_clauses.append("manually_edited_fields = ?")
            values.append(json.dumps(merged_edited))

            values.extend([bom_item_id, rfq_id])
            con.execute(
                f"UPDATE processed_bom_items SET {', '.join(set_clauses)} WHERE bom_item_id = ? AND rfq_id = ?",
                values,
            )
            updated_count += 1

        con.execute("COMMIT")
    except Exception as e:
        con.execute("ROLLBACK")
        con.close()
        raise HTTPException(status_code=500, detail=str(e))

    con.close()
    return {"success": True, "rfq_id": rfq_id, "rows_updated": updated_count}


@app.post("/api/bom/rfq-preview/{rfq_id}/approve")
def approve_rfq_preview(rfq_id: str, token: dict = Depends(auth.verify_token)):
    """User has reviewed the stage-7 preview and is ready for export --
    advances past apply_alternatives so the next /api/dify/start resume runs
    export_enriched_bom instead of re-halting at the same step."""
    new_stage = _advance_past_apply_alternatives(rfq_id)
    return {"success": True, "rfq_id": rfq_id, "rfq_process_stage": new_stage}


# ============================================================
# RFQ_Flow: optional Gerber ZIP feature-extraction preview --
# gerber_integration__extract_features (mcp-tools/gerber-integration/)
# writes gerber_geometry (one row per rfq_id) and gerber_checklist (up to 34
# rows per rfq_id) into bom_storage.duckdb, then returns hitl=1 so the DMR
# halts here for review. These 3 endpoints are RFQ_Flow's counterpart to
# the rfq-preview/apply_alternatives trio above, same reasoning: a bare
# resume would otherwise just re-run extract_features from scratch rather
# than advancing past it.
# ============================================================

_GERBER_EXTRACT_TOOL = "gerber_integration__extract_features"


def _advance_past_gerber_extract_features(rfq_id: str) -> int:
    """Mirrors _advance_past_apply_alternatives/_advance_past_detect_alternates
    -- see those functions' docstrings. Called once the user approves the
    Gerber preview, so a resumed Dify run proceeds into
    distributor__enrich_bom instead of re-running extract_features."""
    try:
        routing_sequence = get_routing_sequence("RFQ_Flow")
        target_index = routing_sequence.index(_GERBER_EXTRACT_TOOL) + 1
        new_stage = advance_skill_index_to_at_least(rfq_id, target_index)
        print(f"[GERBER PREVIEW] advanced past extract_features (index {target_index - 1}) -- rfq_process_stage={new_stage}")
    except Exception as e:
        print(f"[GERBER PREVIEW ERROR] Could not resolve routing sequence, falling back to +1: {e}")
        new_stage = increment_skill_index(rfq_id)

    try:
        set_hitl_required(rfq_id, False)
    except Exception as e:
        print(f"[HITL STATE ERROR] Could not clear hitl_required: {e}")

    return new_stage


# The checklist's own editable "value" column is polymorphic (value_text/
# value_num/value_bool, selected by value_type) -- rather than exposing 3
# separate ag-grid columns, the frontend sends back one plain string per
# edited cell and this re-derives the typed columns, mirroring the same
# tri-typed split gerber_tables.py's _split_value() used when the value was
# first extracted.
def _coerce_checklist_value(raw: Optional[str]):
    if raw is None or raw == "":
        return None, None, None, "null"
    if raw.strip().lower() in ("true", "false"):
        val = raw.strip().lower() == "true"
        return str(val), None, val, "bool"
    try:
        num = float(raw)
        return raw, num, None, "number"
    except (TypeError, ValueError):
        return raw, None, None, "text"


@app.get("/api/bom/gerber-preview/{rfq_id}")
def get_gerber_preview(rfq_id: str, token: dict = Depends(auth.verify_token)):
    """The extracted Gerber geometry (one row) + 34-row checklist for this
    rfq_id, read from bom_storage.duckdb's gerber_geometry/gerber_checklist
    tables (written by gerber_integration__extract_features)."""
    con = duckdb.connect(BOM_STORAGE_DB_PATH, read_only=True)
    try:
        geo_rows = con.execute("SELECT * FROM gerber_geometry WHERE rfq_id = ?", [rfq_id]).fetchall()
        geo_cols = [d[0] for d in con.description]

        chk_rows = con.execute(
            """
            SELECT field, category, label, value_text, value_num, value_bool, value_type,
                   present, provenance, confidence, source, note, pricing_fallback
            FROM gerber_checklist
            WHERE rfq_id = ?
            ORDER BY category, field
            """,
            [rfq_id],
        ).fetchall()
        chk_cols = [d[0] for d in con.description]
    finally:
        con.close()

    geometry = dict(zip(geo_cols, geo_rows[0])) if geo_rows else None
    if geometry:
        for key in ("detected_files", "warnings"):
            if isinstance(geometry.get(key), str):
                try:
                    geometry[key] = json.loads(geometry[key])
                except (json.JSONDecodeError, TypeError):
                    pass

    checklist = []
    for row in chk_rows:
        r = dict(zip(chk_cols, row))
        if r["value_type"] == "bool":
            r["value"] = r["value_bool"]
        elif r["value_type"] == "number":
            r["value"] = r["value_num"]
        else:
            r["value"] = r["value_text"]
        checklist.append(r)

    return {"success": True, "rfq_id": rfq_id, "geometry": geometry, "checklist": checklist}


@app.put("/api/bom/batch-update-gerber-checklist/{rfq_id}")
def batch_update_gerber_checklist(rfq_id: str, updates: list[dict[str, Any]], token: dict = Depends(auth.verify_token)):
    """Applies inline cell edits (keyed by `field`, the checklist row's own
    unique identifier -- there's no bom_item_id-style UUID here) to
    gerber_checklist. A manually-entered value is marked
    provenance='operator' (one of the documented provenance values) with
    confidence=1.0, same idea as CBOM/RFQ preview's batch-update endpoints
    but for a field-keyed table instead of a bom_item_id-keyed one."""
    if not updates:
        raise HTTPException(status_code=400, detail="No rows provided for update.")

    con = duckdb.connect(BOM_STORAGE_DB_PATH, read_only=False)
    try:
        con.execute("BEGIN TRANSACTION")
        updated_count = 0
        for row in updates:
            field = row.get("field")
            if not field:
                continue
            value_text, value_num, value_bool, value_type = _coerce_checklist_value(
                None if row.get("value") is None else str(row.get("value"))
            )
            con.execute(
                """
                UPDATE gerber_checklist
                SET value_text = ?, value_num = ?, value_bool = ?, value_type = ?,
                    present = ?, provenance = 'operator', confidence = 1.0
                WHERE rfq_id = ? AND field = ?
                """,
                [value_text, value_num, value_bool, value_type, value_type != "null", rfq_id, field],
            )
            updated_count += 1
        con.execute("COMMIT")
    except Exception as e:
        con.execute("ROLLBACK")
        con.close()
        raise HTTPException(status_code=500, detail=str(e))

    con.close()
    return {"success": True, "rfq_id": rfq_id, "rows_updated": updated_count}


@app.post("/api/bom/gerber-preview/{rfq_id}/approve")
def approve_gerber_preview(rfq_id: str, token: dict = Depends(auth.verify_token)):
    """User has reviewed the Gerber extraction preview and is ready to
    continue -- advances past gerber_integration__extract_features so the
    next /api/dify/start resume runs distributor__enrich_bom instead of
    re-halting at the same step."""
    new_stage = _advance_past_gerber_extract_features(rfq_id)
    return {"success": True, "rfq_id": rfq_id, "rfq_process_stage": new_stage}


_GERBER_CHECKLIST_COLUMNS = [
    "category", "label", "value_text", "value_num", "value_bool", "value_type",
    "present", "provenance", "confidence", "source", "note", "pricing_fallback",
]


@app.get("/api/bom/gerber-preview/{rfq_id}/export/download")
def download_gerber_report(rfq_id: str, token: dict = Depends(auth.verify_token)):
    """The first real Excel export for Gerber feature-extraction data --
    previously extraction only ever wrote to DuckDB, with no downloadable
    deliverable at all. A geometry summary block followed by the full
    34-row checklist table, yellow fill on the Value cell wherever
    provenance='operator' -- the SAME persisted signal the live grid and the
    client-side quick-download (StageExecutionOutput.tsx's
    downloadGerberChecklistExcel) both read, so all three agree on exactly
    which cells are highlighted."""
    con = duckdb.connect(BOM_STORAGE_DB_PATH, read_only=True)
    try:
        geo_rows = con.execute("SELECT * FROM gerber_geometry WHERE rfq_id = ?", [rfq_id]).fetchall()
        geo_cols = [d[0] for d in con.description]
        chk_rows = con.execute(
            f"SELECT field, {', '.join(_GERBER_CHECKLIST_COLUMNS)} FROM gerber_checklist WHERE rfq_id = ? ORDER BY category, field",
            [rfq_id],
        ).fetchall()
        chk_cols = ["field"] + _GERBER_CHECKLIST_COLUMNS
    finally:
        con.close()

    if not geo_rows and not chk_rows:
        raise HTTPException(status_code=404, detail=f"No Gerber feature data found for rfq_id={rfq_id!r}")

    geometry = dict(zip(geo_cols, geo_rows[0])) if geo_rows else {}
    yellow_fill = openpyxl.styles.PatternFill("solid", fgColor=MANUAL_EDIT_FILL_ARGB)
    header_fill = openpyxl.styles.PatternFill("solid", fgColor="2F5496")
    header_font = openpyxl.styles.Font(bold=True, color="FFFFFF")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Gerber Report"

    ws.append(["Board Geometry Summary"])
    ws["A1"].font = openpyxl.styles.Font(bold=True, size=14)
    geometry_fields = [
        ("Board Name", geometry.get("board_name")),
        ("Width (mm)", geometry.get("width_mm")),
        ("Height (mm)", geometry.get("height_mm")),
        ("Area (cm2)", geometry.get("area_cm2")),
        ("Layer Count", geometry.get("layer_count")),
        ("Confidence", geometry.get("confidence")),
        ("Outline", "Estimated" if geometry.get("is_outline_estimated") else "Exact"),
        ("Total Drill Holes", geometry.get("total_holes")),
    ]
    for label, value in geometry_fields:
        ws.append([label, value])
    ws.append([])

    checklist_headers = ["Category", "Field", "Value", "Present", "Provenance", "Confidence", "Source", "Note"]
    ws.append(checklist_headers)
    # Computed AFTER the append, not before -- the preceding ws.append([])
    # spacer row doesn't create any real cells, so ws.max_row doesn't
    # advance for it; pre-computing "max_row + 1" landed the header fill on
    # that blank row instead of the actual header row (confirmed live: the
    # fill showed up one row too early on a real download).
    header_row_idx = ws.max_row
    for c in range(1, len(checklist_headers) + 1):
        cell = ws.cell(row=header_row_idx, column=c)
        cell.fill = header_fill
        cell.font = header_font

    for row in chk_rows:
        r = dict(zip(chk_cols, row))
        if r["value_type"] == "bool":
            value = r["value_bool"]
        elif r["value_type"] == "number":
            value = r["value_num"]
        else:
            value = r["value_text"]
        row_idx = ws.max_row + 1
        ws.append([r["category"], r["label"], value, r["present"], r["provenance"], r["confidence"], r["source"], r["note"]])
        if r["provenance"] == "operator":
            ws.cell(row=row_idx, column=3).fill = yellow_fill

    for col_letter, width in zip("ABCDEFGH", [16, 24, 22, 12, 12, 12, 14, 30]):
        ws.column_dimensions[col_letter].width = width

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="Gerber_Report_{rfq_id}.xlsx"'},
    )


class ChatEvidenceRequest(BaseModel):
    question: str
    top_k: int = 12


@app.post("/api/rfq/{rfq_id}/chat/evidence")
def chat_evidence(rfq_id: str, body: ChatEvidenceRequest, token: dict = Depends(auth.verify_token)):
    """The RFQ assistant's grounding: this RFQ's own results (the latest exported workbook, with its stored values)
    and its live state, as citable chunks ranked against the question. See chat_evidence.py. Read-only."""
    import chat_evidence

    extra, warning = [], None
    try:
        with get_metadata_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT version, rfq_process_stage, hitl_required FROM rfq_process_tracking "
                        "WHERE rfq_id = %s AND is_active", (rfq_id,))
            tracking = cur.fetchone()
            cur.execute("SELECT file_role, file_path, scan_status FROM rfq_file_telemetry "
                        "WHERE rfq_id = %s AND is_active ORDER BY file_role", (rfq_id,))
            files = cur.fetchall()
        if tracking:
            extra.append(chat_evidence.state_chunk(rfq_id, tracking[0], tracking[1], tracking[2], files))
        else:
            warning = f"No RFQ named {rfq_id!r} is known to the pipeline."
    except Exception as e:  # the workbook may still answer
        print(f"[CHAT EVIDENCE] state lookup failed for {rfq_id}: {e}")

    path = _find_latest_export(_resolve_cbom_key(rfq_id)) or _find_latest_rfqflow_export(rfq_id)
    if path is None:
        warning = warning or "This RFQ has no exported results yet (the pipeline has not finished its export step)."
        index = {"chunks": [], "squashed": "", "workbook": None, "warning": None}
    else:
        index = chat_evidence.workbook_index(path)
    attachment_chunks, attachment_squashed = _attachment_evidence(rfq_id)   # released attachments are evidence too
    if attachment_chunks:
        extra += attachment_chunks
        index = {**index, "squashed": index["squashed"] + attachment_squashed}   # never mutate the cached index
    found = chat_evidence.retrieve(index, body.question, extra=extra, top_k=max(1, min(body.top_k, 30)), rfq_id=rfq_id)
    return {"rfq_id": rfq_id, "workbook": index["workbook"], "warning": warning or index.get("warning"), **found}


# ---- RFQ assistant attachments: twin-engine scan (scan_engines.py), released files become chat evidence ----------
# Layout: <inbox>/<rfq_id>/attachments/<sha256[:12]>-<safe name> plus audit.jsonl (one line per scanned/deleted file).
# Nothing that is not released by BOTH engines is ever written there; quarantined bytes are deleted.
import functools
import shutil
import tempfile
from fastapi import File, Request, UploadFile

ATTACHMENT_INBOX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "staged", "inbox")
MAX_ATTACHMENT_FILES = 10
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
MAX_ATTACHMENT_TOTAL = 60 * 1024 * 1024
_SAFE_RFQ_ID = re.compile(r"[A-Za-z0-9_\-]{1,64}")   # the intake service's _validate_id rule
_ATTACHMENT_FILE = re.compile(r"([0-9a-f]{12})-(.+)")


def _attachment_dir(rfq_id: str) -> str:
    # /auth/token mints a token for any rfq_id, so the id is untrusted path input
    if not _SAFE_RFQ_ID.fullmatch(rfq_id):
        raise HTTPException(status_code=400, detail="Invalid RFQ id")
    return os.path.join(ATTACHMENT_INBOX, rfq_id, "attachments")


def _audit(folder: str, record: dict) -> None:
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "audit.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"time": datetime.utcnow().isoformat() + "Z", **record}) + "\n")


def _released_files(folder: str):
    """[(attachment_id, name, path)] of what is stored now."""
    if not os.path.isdir(folder):
        return []
    found = []
    for entry in sorted(os.listdir(folder)):
        m = _ATTACHMENT_FILE.fullmatch(entry)
        if m and os.path.isfile(os.path.join(folder, entry)):
            found.append((m.group(1), m.group(2), os.path.join(folder, entry)))
    return found


@functools.lru_cache(maxsize=64)
def _attachment_chunks(path: str, mtime: float, attachment_id: str, name: str):
    import attachment_text
    import chat_evidence
    chunks = [{"text": c["text"],
               "citation": {"sourceType": "attachment", "label": c["label"],
                            "identifier": {"file": name, "attachment_id": attachment_id}},
               "tokens": chat_evidence._tokens(c["text"]), "always": False, "pinned": False}
              for c in attachment_text.chunks(path, name)]
    return chunks, chat_evidence._squash("\n".join(c["text"] for c in chunks))


def _attachment_evidence(rfq_id: str):
    """(chunks, squashed text) of every released attachment of this RFQ, parsed once per file version."""
    if not _SAFE_RFQ_ID.fullmatch(rfq_id):
        return [], ""
    chunks, squashed = [], []
    for attachment_id, name, path in _released_files(_attachment_dir(rfq_id)):
        try:
            c, s = _attachment_chunks(path, os.path.getmtime(path), attachment_id, name)
        except Exception as e:
            print(f"[ATTACHMENTS] could not read {path}: {e}")
            continue
        chunks += c
        squashed.append(s)
    return chunks, "".join(squashed)


def _queue_attachment_memory(rfq_id: str, attachment_id: str, name: str, path: str) -> None:
    try:
        import rfq_memory_client
        hook = getattr(rfq_memory_client, "queue_attachment_ingestion", None)
        if hook is None:
            return
        chunks, _ = _attachment_chunks(path, os.path.getmtime(path), attachment_id, name)
        hook(rfq_id, attachment_id, name, "\n".join(c["text"] for c in chunks)[:200000])
    except Exception as e:  # memory is best-effort; the scan result stands
        print(f"[ATTACHMENTS] memory ingestion not queued for {name}: {e}")


@app.post("/api/rfq/{rfq_id}/attachments/scan")
def scan_attachments(rfq_id: str, request: Request, files: list[UploadFile] = File(...),
                     token: dict = Depends(auth.verify_token)):
    """Scan files attached in the RFQ assistant with BOTH engines (BuLL*Sav ClamAV + Repel Shield). Released only
    when both say clean; a threat is quarantined (deleted), an engine error holds the file (deleted, not released)."""
    import scan_engines

    folder = _attachment_dir(rfq_id)
    if int(request.headers.get("content-length") or 0) > MAX_ATTACHMENT_TOTAL + 1024 * 1024:
        raise HTTPException(status_code=413, detail="Attachments are limited to 60 MB per request")
    if not files:
        raise HTTPException(status_code=400, detail="Attach at least one file")
    if len(files) > MAX_ATTACHMENT_FILES:
        raise HTTPException(status_code=400, detail=f"{len(files)} files sent; at most {MAX_ATTACHMENT_FILES} per request")
    quarantine = tempfile.mkdtemp(prefix="cam-quarantine-")
    try:
        items, total = [], 0
        for i, upload in enumerate(files):
            name = scan_engines.safe_name(upload.filename)
            qpath = os.path.join(quarantine, f"{i}{os.path.splitext(name)[1].lower()}")
            size = 0
            with open(qpath, "wb") as out:
                for block in iter(lambda: upload.file.read(1 << 20), b""):
                    size += len(block)
                    if size > MAX_ATTACHMENT_BYTES:
                        raise HTTPException(status_code=413, detail=f"{name} is larger than 25 MB")
                    out.write(block)
            if size == 0:
                raise HTTPException(status_code=400, detail=f"{name} is empty")
            total += size
            if total > MAX_ATTACHMENT_TOTAL:
                raise HTTPException(status_code=413, detail="Attachments are limited to 60 MB per request")
            items.append((qpath, upload.filename or name))

        results = []
        for (qpath, original), result in zip(items, scan_engines.scan_files(items)):
            result["attachment_id"] = None
            if result["decision"] == "released":
                os.makedirs(folder, exist_ok=True)
                attachment_id = result["sha256"][:12]
                dest = os.path.join(folder, f"{attachment_id}-{result['name']}")
                if not os.path.realpath(dest).startswith(os.path.realpath(folder) + os.sep):
                    raise HTTPException(status_code=400, detail="Invalid file name")
                for old_id, _, old_path in _released_files(folder):   # same bytes again: one copy
                    if old_id == attachment_id:
                        os.remove(old_path)
                shutil.move(qpath, dest)
                result["attachment_id"] = attachment_id
            _audit(folder, {"name": result["name"], "size": result["size"], "sha256": result["sha256"],
                            "attachment_id": result["attachment_id"], "clamav": result["clamav"],
                            "repel": {k: result["repel"][k] for k in ("verdict", "score", "flags")},
                            "decision": result["decision"], "reason": result["reason"]})
            if result["attachment_id"]:
                _queue_attachment_memory(rfq_id, result["attachment_id"], result["name"], dest)
            results.append(result)
        return {"rfq_id": rfq_id, "engines": [scan_engines.clamav_status(), scan_engines.repel_status()],
                "results": results}
    finally:
        shutil.rmtree(quarantine, ignore_errors=True)   # quarantined and held bytes never outlive the request


@app.get("/api/rfq/{rfq_id}/attachments")
def list_attachments(rfq_id: str, token: dict = Depends(auth.verify_token)):
    folder = _attachment_dir(rfq_id)
    audit = {}
    if os.path.isfile(os.path.join(folder, "audit.jsonl")):
        with open(os.path.join(folder, "audit.jsonl"), encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                if rec.get("decision") == "released":
                    audit[rec["attachment_id"]] = rec
    return [{"attachment_id": attachment_id, "name": name, "size": os.path.getsize(path),
             "sha256": audit.get(attachment_id, {}).get("sha256"),
             "released_at": audit.get(attachment_id, {}).get("time")}
            for attachment_id, name, path in _released_files(folder)]


@app.delete("/api/rfq/{rfq_id}/attachments/{attachment_id}")
def delete_attachment(rfq_id: str, attachment_id: str, token: dict = Depends(auth.verify_token)):
    folder = _attachment_dir(rfq_id)
    if not re.fullmatch(r"[0-9a-f]{12}", attachment_id):
        raise HTTPException(status_code=400, detail="Invalid attachment id")
    gone = [(name, path) for aid, name, path in _released_files(folder) if aid == attachment_id]
    if not gone:
        raise HTTPException(status_code=404, detail="No such attachment")
    for name, path in gone:
        os.remove(path)
        _audit(folder, {"name": name, "attachment_id": attachment_id, "decision": "deleted"})
    return {"rfq_id": rfq_id, "attachment_id": attachment_id, "deleted": True}


if __name__ == '__main__':
    import uvicorn
    # 0.0.0.0, not a single fixed LAN IP -- matches every other service in this
    # pipeline (upload_server, daemon, web_frontend). Binding to one specific
    # interface address means the process refuses connections on every OTHER
    # interface (e.g. the NetBird virtual adapter) regardless of firewall
    # rules, since the OS never even hands it those packets.
    uvicorn.run(app, host="0.0.0.0", port=3110)