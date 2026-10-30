"""Top-level orchestrator for the six independent stages behind the MCP tools (see
mcp_server.py): run_cbom(rfq_id) is what the `cbom` tool calls, run_erp_enrichment(rfq_id)
and run_costing_enrichment(rfq_id) are what the `enrich_erp`/`enrich_costing_sheet` tools
call, run_resolve_final_selection(rfq_id) is what the `resolve_final_selection` tool
(the HITL gate) calls, run_pipeline(rfq_id) is what the `generate_reports` tool calls.
All are independent -- run_erp_enrichment/run_costing_enrichment/
run_resolve_final_selection require cbom rows to already exist (raise ValueError
otherwise); run_pipeline does NOT generate CBOM, it only (re)generates the 16 reports
from whatever CBOM data already exists for that rfq_id, raising if there isn't any yet.
"""

import os
import sys
import time

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import cbom_generator
import database
import enrichment
import final_selection
import helpers
import report_generator
import validator
from logging_utils import logger


def _emit_posthog_tab_failures(rfq_id: str, result: dict) -> None:
    """Fire-and-forget PostHog event when per-tab validation fails.
    No-op if POSTHOG_API_KEY is not set (dev/test environments).
    Uses httpx instead of the posthog SDK to avoid a new dependency.
    """
    api_key = os.environ.get("POSTHOG_API_KEY", "")
    if not api_key:
        return
    failed_tabs = [t for t in result.get("details", []) if not t.get("passed", True)]
    if not failed_tabs:
        return
    try:
        import httpx
        httpx.post(
            "https://app.posthog.com/capture/",
            json={
                "api_key": api_key,
                "event": "rfq_tab_validation_failed",
                "distinct_id": f"cam-server-{rfq_id}",
                "properties": {
                    "rfq_id": rfq_id,
                    "failed_count": result.get("failed", len(failed_tabs)),
                    "total_count": result.get("total", 0),
                    "failed_tabs": [t.get("table", "unknown") for t in failed_tabs[:10]],
                },
            },
            timeout=5,
        )
    except Exception as e:
        logger.warning(f"[PostHog] event emit failed (non-fatal): {e}")


def run_validate_reports(rfq_id):
    """Run all per-tab business-rule validators for one rfq_id against already-generated
    report tables. Read-only: does not modify any data. Returns a summary with
    passed/failed counts and per-table details.
    """
    start = time.time()
    con = database.connect()
    try:
        result = validator.validate_all_reports(con, rfq_id)
    finally:
        con.close()
    result["execution_time_seconds"] = round(time.time() - start, 3)
    logger.info(
        f"run_validate_reports rfq_id={rfq_id!r} "
        f"passed={result['passed']}/{result['total']} failed={result['failed']}"
    )
    _emit_posthog_tab_failures(rfq_id, result)
    return result


def run_cbom(rfq_id):
    """Regenerates only the CBOM table for one rfq_id, in its own transaction. Does not
    touch the 16 downstream reports.
    """
    start = time.time()
    con = database.connect()
    try:
        con.execute("BEGIN TRANSACTION")
        cbom_generator.clear_cbom_rfq(con, rfq_id)
        cbom_result = cbom_generator.generate_cbom(con, rfq_id)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        con.close()
        logger.exception(f"run_cbom FAILED for rfq_id={rfq_id!r}")
        raise
    con.close()

    duration = time.time() - start
    warnings = []
    if cbom_result["priced_row_count"] < cbom_result["row_count"]:
        warnings.append(
            f"{cbom_result['row_count'] - cbom_result['priced_row_count']} of {cbom_result['row_count']} "
            "cbom rows have no resolved final price (expected until final_* columns are "
            "populated for this rfq_id)"
        )

    summary = {
        "status": "success",
        "rfq_id": rfq_id,
        "execution_time_seconds": round(duration, 3),
        "cbom_row_count": cbom_result["row_count"],
        "priced_row_count": cbom_result["priced_row_count"],
        "detected_volumes": cbom_result["detected_volumes"],
        "warnings": warnings,
    }
    logger.info(
        f"run_cbom rfq_id={rfq_id!r} duration={duration:.3f}s "
        f"cbom_rows={cbom_result['row_count']} warnings={warnings}"
    )
    return summary


def run_erp_enrichment(rfq_id):
    """Fills _erp columns on the already-existing cbom rows for one rfq_id, in its own
    transaction. Requires run_cbom(rfq_id) to have already run for this rfq_id -- raises
    ValueError otherwise.
    """
    start = time.time()
    con = database.connect()
    try:
        con.execute("BEGIN TRANSACTION")
        result = enrichment.enrich_erp(con, rfq_id)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        con.close()
        logger.exception(f"run_erp_enrichment FAILED for rfq_id={rfq_id!r}")
        raise
    con.close()

    duration = time.time() - start
    summary = {
        "status": "success",
        "rfq_id": rfq_id,
        "execution_time_seconds": round(duration, 3),
        "cbom_row_count": result["row_count"],
        "rows_matched_erp": result["rows_matched_erp"],
    }
    logger.info(
        f"run_erp_enrichment rfq_id={rfq_id!r} duration={duration:.3f}s "
        f"rows_matched_erp={result['rows_matched_erp']}"
    )
    return summary


def run_costing_enrichment(rfq_id):
    """Fills _costing columns on the already-existing cbom rows for one rfq_id, in its
    own transaction. Requires run_cbom(rfq_id) to have already run for this rfq_id --
    raises ValueError otherwise.
    """
    start = time.time()
    con = database.connect()
    try:
        con.execute("BEGIN TRANSACTION")
        result = enrichment.enrich_costing_sheet(con, rfq_id)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        con.close()
        logger.exception(f"run_costing_enrichment FAILED for rfq_id={rfq_id!r}")
        raise
    con.close()

    duration = time.time() - start
    summary = {
        "status": "success",
        "rfq_id": rfq_id,
        "execution_time_seconds": round(duration, 3),
        "cbom_row_count": result["row_count"],
        "rows_matched_costing": result["rows_matched_costing"],
    }
    logger.info(
        f"run_costing_enrichment rfq_id={rfq_id!r} duration={duration:.3f}s "
        f"rows_matched_costing={result['rows_matched_costing']}"
    )
    return summary


def run_resolve_final_selection(rfq_id):
    """Auto-resolves single-source cbom rows and persists multi-source conflicts to
    Postgres logic_db for human review, in its own transaction. Requires run_cbom(rfq_id)
    to have already run for this rfq_id -- raises ValueError otherwise. This is the HITL
    gate: when the returned summary has hitl=1, the caller (fastapi_router.py) must NOT
    advance rfq_process_stage past this skill until a human resolves every pending
    conflict via hitl_router.py.
    """
    start = time.time()
    con = database.connect()
    rfq_lit = helpers.sql_quote(rfq_id)

    cbom_row_count = con.execute(f"SELECT COUNT(*) FROM cbom_db.cbom WHERE rfq_id = {rfq_lit}").fetchone()[0]
    if cbom_row_count == 0:
        con.close()
        raise ValueError(f"No cbom rows found for rfq_id={rfq_id!r} -- call the cbom tool first")

    try:
        con.execute("BEGIN TRANSACTION")
        result = final_selection.resolve_final_selection(con, rfq_id)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        con.close()
        logger.exception(f"run_resolve_final_selection FAILED for rfq_id={rfq_id!r}")
        raise
    con.close()

    duration = time.time() - start
    result["execution_time_seconds"] = round(duration, 3)
    logger.info(
        f"run_resolve_final_selection rfq_id={rfq_id!r} duration={duration:.3f}s "
        f"hitl={result['hitl']} pending_conflicts={result['pending_conflicts']}"
    )
    return result


def run_pipeline(rfq_id):
    """Regenerates all 16 reports for one rfq_id, reading from the already-generated
    `cbom` table -- does NOT generate CBOM itself. Call run_cbom(rfq_id) (the `cbom`
    tool) first; raises ValueError if no cbom rows exist yet for this rfq_id.
    """
    start = time.time()
    issues = []
    con = database.connect()
    rfq_lit = helpers.sql_quote(rfq_id)

    cbom_row_count = con.execute(f"SELECT COUNT(*) FROM cbom_db.cbom WHERE rfq_id = {rfq_lit}").fetchone()[0]
    if cbom_row_count == 0:
        con.close()
        raise ValueError(f"No cbom rows found for rfq_id={rfq_id!r} -- call the cbom tool first")
    priced_row_count = con.execute(
        f"SELECT COUNT(*) FROM cbom_db.cbom WHERE rfq_id = {rfq_lit} AND final_price_conv IS NOT NULL"
    ).fetchone()[0]

    try:
        con.execute("BEGIN TRANSACTION")
        report_generator.clear_reports_rfq(con, rfq_id)
        reports_result = report_generator.generate_reports(con, rfq_id)
        if reports_result["issues"]:
            # Fail the whole reports transaction rather than leave a partial set of
            # 16 tables committed -- no partially generated reports should remain.
            raise RuntimeError(f"{len(reports_result['issues'])} report(s) failed: {reports_result['issues']}")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        con.close()
        logger.exception(f"run_pipeline FAILED during report generation for rfq_id={rfq_id!r}")
        raise
    con.close()

    duration = time.time() - start
    warnings = []
    if priced_row_count < cbom_row_count:
        warnings.append(
            f"{cbom_row_count - priced_row_count} of {cbom_row_count} cbom rows have no "
            "resolved final price (expected until final_* columns are populated for this rfq_id)"
        )

    summary = {
        "status": "success" if not issues else "completed_with_issues",
        "rfq_id": rfq_id,
        "execution_time_seconds": round(duration, 3),
        "cbom_row_count": cbom_row_count,
        "report_row_counts": reports_result["counts"],
        "validation_summary": {
            "priced_row_count": priced_row_count,
        },
        "warnings": warnings,
        "issues": issues,
    }
    logger.info(
        f"run_pipeline rfq_id={rfq_id!r} duration={duration:.3f}s "
        f"cbom_rows={cbom_row_count} reports={reports_result['counts']} "
        f"warnings={warnings} issues={issues}"
    )
    return summary
