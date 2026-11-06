"""[BuLLMQuote-SRIM MIGRATION NOTE, containerization Phase 2, 2026-10-29]
Migrated from CAM's root scrub_mcp_server.py (registered in MCP Jungle as
`centum_intake`, :8004) along with its full dependency set (scrub_bom_*,
quote_win_*, erp_*, costing_sheet_*, analytics_*, db.py, tool_calling.py,
config.py) -- this service is NOT self-contained the way the other already-
migrated mcp-tools/* services are; it's CAM's whole intake-processing
subsystem, copied as one unit.

Stays on the ORIGINAL MCP Jungle session-handshake tool_calling.py, not the
Bifrost pattern the other mcp-tools/* services use -- `Standard_BOM_Flow`
(this service's own flow) still routes through MCP Jungle, and Bifrost has no
registered client for `postgres_metadata` (the Postgres MCP server this
service's TARGET_METADATA_TOOL calls), so there is no equivalent to migrate
to yet. Confirmed not a shortcut: this matches how `Standard_BOM_Flow` is
documented as still-unmigrated everywhere else in this repo.

Required environment, beyond what's in .env.example:
  LOGIC_DB_URL, FILE_METADATA_DB_URL -- MUST point at Centum's own
    logic_db_2/file_metadata_db_2 (db.py raises if unset -- CAM's original
    hardcoded fallback pointed at CAM's own logic_db/file_metadata_db and was
    removed here for exactly that reason).
  CENTUM_INPUT_DB -- must point at the SAME input_db.duckdb file
    reporting_mcp_server reads from (this repo's shared database/ folder from
    Phase 0), or scrub and reporting silently operate on two different files.
  OLLAMA_HOST=127.0.0.1:11434 -- CAM's manage_backend.py sets this per-service
    to override a machine-wide OLLAMA_HOST=0.0.0.0:11434 that's valid for the
    Ollama *server* but not for this service's own *client* connections; set
    the same way here (this repo's own env, not inherited from CAM's).
Not yet runtime-verified end-to-end (no live Ollama/Postgres wiring test
performed as part of this migration) -- structurally complete and adapted,
but treat as untested until a real scrub run is exercised against it.
"""

import ast
import json
import re
import time
import traceback

from fastmcp import FastMCP

import analytics_events
import analytics_posthog_client

from scrub_bom_processing import process_scrub_bom_workbook
from scrub_bom_to_database import (
    process_scrub_bom_to_database,
    process_volume_to_database,
    process_batch_to_database,
)
from quote_win_processing import process_quote_win
from quote_win_to_database import process_quote_win_to_database
from erp_processing import process_erp
from erp_to_database import process_erp_to_database
from costing_sheet_processing import process_costing_sheet
from costing_sheet_to_database import process_costing_sheet_to_database
from tool_calling import call_tool, create_session
from db import versioned_key, duckdb_file_lock

# Initialize the FastMCP server instance
mcp = FastMCP("ScrubIntake")

# Tool name for the Postgres metadata MCP server
TARGET_METADATA_TOOL = "postgres_metadata__execute_sql"


def _validate_id(value: str) -> str:
    """Reject IDs that contain SQL-unsafe characters before interpolation."""
    if not re.fullmatch(r'[A-Za-z0-9_\-]+', value):
        raise ValueError(f"Invalid ID format: {value!r}")
    return value


def _fetch_file_path(session, rfq_id_str, version, file_role):
    """Look up the registered file path for an RFQ's given (version, file_role).

    version is REQUIRED (passed down from fastapi_router.py's active-version
    resolution) -- filters by (rfq_id, version, file_role, is_active) so a
    re-upload that creates a new version can never accidentally pick up an
    older version's file_path. Also fixes a latent bug: previously this had
    no is_active/ordering filter at all, and several real rfq_ids already
    have 2-3 duplicate rfq_file_telemetry rows, making file-path resolution
    silently non-deterministic (whichever row Postgres happened to return
    first). ORDER BY processed_at DESC LIMIT 1 is a defensive tie-break on
    top of the is_active filter, not the primary correctness mechanism.

    Returns None if no row exists -- callers decide whether that's a hard
    failure (BOM/QUOTEWIN, always required) or a gracefully skippable case
    (COSTING_SHEET/ERP, optional).
    """
    sql = f"""
    SELECT file_path
    FROM rfq_file_telemetry
    WHERE rfq_id = '{rfq_id_str}'
    AND version = {int(version)}
    AND file_role = '{file_role}'
    AND is_active = TRUE
    ORDER BY processed_at DESC
    LIMIT 1;
    """
    res = call_tool(session=session, tool_name=TARGET_METADATA_TOOL, arguments={"sql": sql})

    rows = ast.literal_eval(
        res["result"]["content"][0]["text"]
    )

    if not rows:
        return None

    return rows[0]["file_path"]


@mcp.tool()
def standardize_scrub_bom(rfq_id, version=1) -> str:
    """
    Standardize a SCRUB BOM workbook and store each sheet's standardized
    rows in DuckDB:

    - "SCRUB BOM" sheet  -> scrub_bom_items
    - "Settings" sheet   -> volume
    - "Batch" sheet      -> batch

    Performs schema mapping + standardization only. Does not perform
    volume expansion, consolidation, or duplicate-CPN detection — those
    are out of scope for this tool.

    version: the rfq_process_tracking version this run applies to (resolved
    by fastapi_router.py before calling this tool). DuckDB rows are written
    under the versioned key f"{rfq_id}__v{version}" so each version's data is
    fully isolated -- see db.versioned_key(). Defaults to 1 (bare rfq_id key)
    so a caller that invokes this tool without going through
    fastapi_router.py's /tool/execute (and therefore doesn't know about
    per-version resolution at all) still gets correct, backward-compatible
    single-version behavior instead of a missing-argument error.
    """
    rfq_id_str = _validate_id(str(rfq_id).strip())
    version_int = int(version)
    key = versioned_key(rfq_id_str, version_int)
    session = create_session()

    print(f"\n=== CONNECTING TO METADATA DB VIA: {TARGET_METADATA_TOOL} ===")

    try:
        bom_file = _fetch_file_path(session, rfq_id_str, version_int, "BOM")

    except Exception as db_err:
        analytics_posthog_client.capture("upload_processing_failed", {
            "file_role": "BOM",
            "failure_category": analytics_events.classify_upload_processing_error(message=f"Could not retrieve file path: {db_err}"),
        })
        print(f"Failed to fetch BOM file path from DB for RFQ {rfq_id_str}: {db_err}")
        return json.dumps({
            "status": "failed",
            "error": f"Could not retrieve file path: {db_err}",
            "traceback": traceback.format_exc()
        })

    if bom_file is None:
        analytics_posthog_client.capture("upload_processing_failed", {
            "file_role": "BOM",
            "failure_category": "file_not_found",
        })
        return json.dumps({
            "status": "failed",
            "error": f"No BOM file uploaded for rfq_id={rfq_id_str}"
        })

    analytics_posthog_client.capture("upload_processing_started", {"file_role": "BOM"})
    _start_time = time.monotonic()

    try:

        print("\nStarting SCRUB BOM Workbook Standardization...")

        standardized = process_scrub_bom_workbook(
            bom_file
        )

        print(
            "\nSaving To DuckDB..."
        )

        # See db.duckdb_file_lock()'s docstring -- this writes input_db.duckdb,
        # which reporting_mcp_server/python_bridge/hitl_router also open
        # (read-only) via reporting_module/database.py's connect().
        with duckdb_file_lock():
            scrub_bom_result = process_scrub_bom_to_database(
                key, standardized["scrub_bom"]
            )
            volume_result = process_volume_to_database(
                key, standardized["volume"]
            )
            batch_result = process_batch_to_database(
                key, standardized["batch"]
            )

        table_results = {
            "scrub_bom_items": scrub_bom_result,
            "volume": volume_result,
            "batch": batch_result,
        }

        overall_status = (
            "success"
            if all(r["status"] == "success" for r in table_results.values())
            else "failed"
        )

        response = {
            "status": overall_status,
            **table_results
        }

        # Intake HITL gate: on a FRESH success, halt the pipeline here
        # (fastapi_router.py's /tool/execute won't advance skill_index while
        # hitl is truthy) so the frontend can pause and let the user upload
        # QuoteWin/Costing Sheet before continuing -- see
        # RfqErpQuoteWinUploadModal.tsx, which resumes the run via GET
        # /api/dify/start/{rfq_id} once both uploads succeed.
        #
        # NOT re-asserted when every table's rows already existed
        # (already_processed) -- Dify's own workflow unconditionally re-calls
        # this tool on every resume trigger regardless of whether it already
        # ran, and by the time that happens the pipeline may have already
        # progressed well past this checkpoint (quote_win/cbom/etc. already
        # succeeded). Re-pausing here on a no-op re-run would wrongly stall an
        # already-advancing pipeline right back at the start.
        already_processed = all(r.get("already_processed") for r in table_results.values())
        if overall_status == "success" and not already_processed:
            response["hitl"] = 1

        if overall_status == "success":
            analytics_posthog_client.capture("upload_processing_completed", {
                "file_role": "BOM",
                "row_count_bucket": analytics_events.bucket_row_count(len(standardized["scrub_bom"])),
                "duration_bucket": analytics_events.bucket_duration_seconds(time.monotonic() - _start_time),
                "already_processed": already_processed,
            })
        else:
            # Reached when one of the 3 per-table writes (scrub_bom_items,
            # volume, batch) came back "failed" without raising -- inspect
            # whichever table(s) failed for the real cause.
            failure_text = "; ".join(
                str(r.get("error")) for r in table_results.values() if r.get("status") == "failed" and r.get("error")
            ) or "generic_error"
            analytics_posthog_client.capture("upload_processing_failed", {
                "file_role": "BOM",
                "failure_category": analytics_events.classify_upload_processing_error(message=failure_text),
            })

        return json.dumps(response)

    except Exception as e:
        analytics_posthog_client.capture("upload_processing_failed", {
            "file_role": "BOM",
            "failure_category": analytics_events.classify_upload_processing_error(exc=e),
        })

        return json.dumps({
            "status": "failed",
            "error": str(e),
            "traceback": traceback.format_exc()
        })


@mcp.tool()
def standardize_quote_win(rfq_id, version=1) -> str:
    """
    Standardize a QuoteWin (Awards Part Number Listing) report and store
    the standardized rows in DuckDB's quote_win table.

    Performs schema mapping + standardization only.

    version: see standardize_scrub_bom's docstring -- same versioned-key
    isolation and default-value rationale apply here.
    """
    rfq_id_str = _validate_id(str(rfq_id).strip())
    version_int = int(version)
    key = versioned_key(rfq_id_str, version_int)
    session = create_session()

    print(f"\n=== CONNECTING TO METADATA DB VIA: {TARGET_METADATA_TOOL} ===")

    try:
        quote_win_file = _fetch_file_path(session, rfq_id_str, version_int, "QUOTEWIN")

    except Exception as db_err:
        analytics_posthog_client.capture("upload_processing_failed", {
            "file_role": "QUOTEWIN",
            "failure_category": analytics_events.classify_upload_processing_error(message=f"Could not retrieve file path: {db_err}"),
        })
        print(f"Failed to fetch QuoteWin file path from DB for RFQ {rfq_id_str}: {db_err}")
        return json.dumps({
            "status": "failed",
            "error": f"Could not retrieve file path: {db_err}",
            "traceback": traceback.format_exc()
        })

    if quote_win_file is None:
        analytics_posthog_client.capture("upload_processing_failed", {
            "file_role": "QUOTEWIN",
            "failure_category": "file_not_found",
        })
        return json.dumps({
            "status": "failed",
            "error": f"No QuoteWin file uploaded for rfq_id={rfq_id_str}"
        })

    analytics_posthog_client.capture("upload_processing_started", {"file_role": "QUOTEWIN"})
    _start_time = time.monotonic()

    try:

        print("\nStarting QuoteWin Standardization...")

        standardized_df = process_quote_win(
            quote_win_file
        )

        print(
            f"\nStandardized Rows: "
            f"{len(standardized_df)}"
        )

        print(
            "\nSaving To DuckDB..."
        )

        with duckdb_file_lock():
            result = process_quote_win_to_database(
                key, standardized_df
            )

        if result.get("status") == "success":
            analytics_posthog_client.capture("upload_processing_completed", {
                "file_role": "QUOTEWIN",
                "row_count_bucket": analytics_events.bucket_row_count(len(standardized_df)),
                "duration_bucket": analytics_events.bucket_duration_seconds(time.monotonic() - _start_time),
                "already_processed": bool(result.get("already_processed", False)),
            })
        else:
            analytics_posthog_client.capture("upload_processing_failed", {
                "file_role": "QUOTEWIN",
                "failure_category": analytics_events.classify_upload_processing_error(message=result.get("error")),
            })

        return json.dumps({
            **result,
            "rows_standardized": len(standardized_df)
        })

    except Exception as e:
        analytics_posthog_client.capture("upload_processing_failed", {
            "file_role": "QUOTEWIN",
            "failure_category": analytics_events.classify_upload_processing_error(exc=e),
        })

        return json.dumps({
            "status": "failed",
            "error": str(e),
            "traceback": traceback.format_exc()
        })


@mcp.tool()
def standardize_erp(rfq_id, version=1) -> str:
    """
    Standardize an ERP purchase-history export and store the
    standardized rows in DuckDB's erp table.

    Performs schema mapping + standardization only. The erp table is a
    standing reference table (not scoped to a single RFQ), so rows are
    appended rather than gated by an rfq_id existence check.

    ERP has no upload path in the current product (see upload_server.py
    — its endpoint was repurposed for Costing Sheet), so this always
    returns "skipped" today. Kept fully working for when ERP uploads
    are reintroduced. version accepted for signature symmetry with the
    other standardize_* tools -- unused since this tool is not part of the
    versioned pipeline today (not in system_skills_registry's active set).
    """
    rfq_id_str = _validate_id(str(rfq_id).strip())
    version_int = int(version)
    session = create_session()

    print(f"\n=== CONNECTING TO METADATA DB VIA: {TARGET_METADATA_TOOL} ===")

    try:
        erp_file = _fetch_file_path(session, rfq_id_str, version_int, "ERP")

    except Exception as db_err:
        print(f"Failed to fetch ERP file path from DB for RFQ {rfq_id_str}: {db_err}")
        return json.dumps({
            "status": "failed",
            "error": f"Could not retrieve file path: {db_err}",
            "traceback": traceback.format_exc()
        })

    if erp_file is None:
        return json.dumps({
            "status": "skipped",
            "reason": f"no ERP file uploaded for rfq_id={rfq_id_str}"
        })

    try:

        print("\nStarting ERP Standardization...")

        standardized_df = process_erp(
            erp_file
        )

        print(
            f"\nStandardized Rows: "
            f"{len(standardized_df)}"
        )

        print(
            "\nSaving To DuckDB..."
        )

        with duckdb_file_lock():
            result = process_erp_to_database(
                standardized_df
            )

        return json.dumps({
            **result,
            "rows_standardized": len(standardized_df)
        })

    except Exception as e:

        return json.dumps({
            "status": "failed",
            "error": str(e),
            "traceback": traceback.format_exc()
        })


@mcp.tool()
def standardize_costing_sheet(rfq_id, version=1) -> str:
    """
    Standardize a Costing Sheet report and store the standardized rows
    in DuckDB's costing_sheet table.

    Performs schema mapping + standardization only. Costing Sheet is an
    optional upload -- if none was provided for this rfq_id, this
    returns a "skipped" status rather than failing (same treatment ERP
    previously had).

    version: see standardize_scrub_bom's docstring -- same versioned-key
    isolation applies here.
    """
    rfq_id_str = _validate_id(str(rfq_id).strip())
    version_int = int(version)
    key = versioned_key(rfq_id_str, version_int)
    session = create_session()

    print(f"\n=== CONNECTING TO METADATA DB VIA: {TARGET_METADATA_TOOL} ===")

    try:
        costing_sheet_file = _fetch_file_path(session, rfq_id_str, version_int, "COSTING_SHEET")

    except Exception as db_err:
        analytics_posthog_client.capture("upload_processing_failed", {
            "file_role": "COSTING_SHEET",
            "failure_category": analytics_events.classify_upload_processing_error(message=f"Could not retrieve file path: {db_err}"),
        })
        print(f"Failed to fetch Costing Sheet file path from DB for RFQ {rfq_id_str}: {db_err}")
        return json.dumps({
            "status": "failed",
            "error": f"Could not retrieve file path: {db_err}",
            "traceback": traceback.format_exc()
        })

    if costing_sheet_file is None:
        analytics_posthog_client.capture("upload_processing_skipped", {"file_role": "COSTING_SHEET"})
        return json.dumps({
            "status": "skipped",
            "reason": f"no Costing Sheet uploaded for rfq_id={rfq_id_str}"
        })

    analytics_posthog_client.capture("upload_processing_started", {"file_role": "COSTING_SHEET"})
    _start_time = time.monotonic()

    try:

        print("\nStarting Costing Sheet Standardization...")

        standardized_df = process_costing_sheet(
            costing_sheet_file
        )

        print(
            f"\nStandardized Rows: "
            f"{len(standardized_df)}"
        )

        print(
            "\nSaving To DuckDB..."
        )

        with duckdb_file_lock():
            result = process_costing_sheet_to_database(
                key, standardized_df
            )

        if result.get("status") == "success":
            analytics_posthog_client.capture("upload_processing_completed", {
                "file_role": "COSTING_SHEET",
                "row_count_bucket": analytics_events.bucket_row_count(len(standardized_df)),
                "duration_bucket": analytics_events.bucket_duration_seconds(time.monotonic() - _start_time),
                "already_processed": bool(result.get("already_processed", False)),
            })
        else:
            analytics_posthog_client.capture("upload_processing_failed", {
                "file_role": "COSTING_SHEET",
                "failure_category": analytics_events.classify_upload_processing_error(message=result.get("error")),
            })

        return json.dumps({
            **result,
            "rows_standardized": len(standardized_df)
        })

    except Exception as e:
        analytics_posthog_client.capture("upload_processing_failed", {
            "file_role": "COSTING_SHEET",
            "failure_category": analytics_events.classify_upload_processing_error(exc=e),
        })

        return json.dumps({
            "status": "failed",
            "error": str(e),
            "traceback": traceback.format_exc()
        })


if __name__ == "__main__":
    # 0.0.0.0, not a single fixed LAN IP -- binding to one specific interface
    # address means the process refuses connections on every OTHER interface
    # (e.g. the NetBird virtual adapter) regardless of firewall rules.
    mcp.run(transport="http", host="0.0.0.0", port=8004)
