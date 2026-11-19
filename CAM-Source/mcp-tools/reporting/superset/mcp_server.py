"""FastMCP server "cbom-reporting" -- the module's only public surface.

Exposes exactly six tools, each taking exactly one parameter (rfq_id) -- no database
paths, filenames, SQL, Excel internals, or validation logic are ever exposed to a caller.
Everything else in this folder is internal implementation the consuming application
never needs to know about. The six tools are independent stages, called in order:
`cbom` (regenerate CBOM structure + _qw columns from quote_win) -> `enrich_erp` (fill
_erp columns from erp master data -- currently unused in the active routing sequence,
kept for future use) -> `enrich_costing_sheet` (fill _costing columns from costing_sheet)
-> `resolve_final_selection` (the HITL gate: auto-resolves single-source rows, persists
multi-source conflicts to Postgres for human review -- see final_selection.py) ->
`generate_reports` (regenerate the 16 reports from whatever CBOM data currently exists)
-> `export_reports` (export to Excel, read-only). enrich_erp and enrich_costing_sheet are
independent of each other (either order, or either skipped) but both require `cbom` to
have already run for that rfq_id; resolve_final_selection also requires `cbom` first and
should run after whichever enrich_* stages apply.

Run directly (`python mcp_server.py`) for streamable-http transport on
192.168.1.27:8105 (registered in MCP Jungle as `centum_reporting` -- NOTE:
that MCP Jungle registration still points at the old :8005 and must be
updated separately, outside this repo, or routed tool calls will fail), or
import `mcp` for in-process testing via `fastmcp.Client(mcp)`.
"""

import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from fastmcp import FastMCP

import cached_values
from reports import forced_run, xlsx_rels
import exporter
import reporting_pipeline
from logging_utils import logger

# [BuLLMQuote-SRIM MIGRATION NOTE] db.py lives at this repo's fastmcp-router/
# (a sibling of mcp-tools/, not one level up from this file the way it is in
# centum intake's flat layout -- this file is at mcp-tools/reporting/superset/,
# 3 levels below the repo root). Appended, not inserted at 0, for the same
# reason as centum intake's own copy: this folder's own config.py must keep
# priority over anything on this path. See db.duckdb_file_lock()'s docstring
# for why every tool below needs it: DuckDB's embedded engine does not queue
# concurrent cross-process access to reports.duckdb/cbom.duckdb/input_db.duckdb
# the way it does for concurrent connections within one process -- python_bridge
# (duck_db_api.py) and hitl_router also open these same files, so this MCP
# server's own tool calls must take the same lock they do.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_THIS_DIR)))
_FASTMCP_ROUTER_DIR = os.path.join(_REPO_ROOT, "fastapi-router")
if _FASTMCP_ROUTER_DIR not in sys.path:
    sys.path.append(_FASTMCP_ROUTER_DIR)
import db
import currency

mcp = FastMCP("cbom-reporting")


@mcp.tool
def feasibility_risk(rfq_id: str) -> dict:
    """Feasibility & Risk (SKILL_03): a Can-Build / Cannot-Build verdict with reasons for every SCRUB BOM line (EOL, no price, long lead time, NRFND, NCNR,
    expired quotes), from the SCRUB BOM and the QuoteWin quotes. Machine constraints are not evaluated (no EMS capability template exists). Records that
    this RFQ ran the step: the export then carries the 'Feasibility & Risk' tab. Returns line, verdict and risk counts.
    """
    try:
        with db.duckdb_file_lock():
            return reporting_pipeline.run_feasibility(rfq_id)
    except Exception as e:
        logger.exception(f"feasibility_risk tool failed for rfq_id={rfq_id!r}")
        return {"status": "failed", "rfq_id": rfq_id, "error": str(e)}


@mcp.tool
def cbom(rfq_id: str) -> dict:
    """Regenerate only the CBOM table for one rfq_id, from the existing (read-only)
    input tables. Does not touch the 16 downstream reports. Returns row counts,
    execution time, and any warnings.
    """
    currency.clear_cache()  # long-lived server: pick up admin rate edits per call
    try:
        with db.duckdb_file_lock():
            return reporting_pipeline.run_cbom(rfq_id)
    except Exception as e:
        logger.exception(f"cbom tool failed for rfq_id={rfq_id!r}")
        return {"status": "failed", "rfq_id": rfq_id, "error": str(e)}


@mcp.tool
def enrich_erp(rfq_id: str) -> dict:
    """Fill the _erp columns on the existing CBOM rows for one rfq_id, from erp master
    data. Requires the `cbom` tool to have already run for this rfq_id. Independent of
    `enrich_costing_sheet` -- either order, or either skipped.
    """
    currency.clear_cache()  # long-lived server: pick up admin rate edits per call
    try:
        with db.duckdb_file_lock():
            return reporting_pipeline.run_erp_enrichment(rfq_id)
    except Exception as e:
        logger.exception(f"enrich_erp tool failed for rfq_id={rfq_id!r}")
        return {"status": "failed", "rfq_id": rfq_id, "error": str(e)}


@mcp.tool
def enrich_costing_sheet(rfq_id: str) -> dict:
    """Fill the _costing columns on the existing CBOM rows for one rfq_id, from
    costing_sheet data. Requires the `cbom` tool to have already run for this rfq_id.
    Independent of `enrich_erp` -- either order, or either skipped.
    """
    currency.clear_cache()  # long-lived server: pick up admin rate edits per call
    try:
        with db.duckdb_file_lock():
            return reporting_pipeline.run_costing_enrichment(rfq_id)
    except Exception as e:
        logger.exception(f"enrich_costing_sheet tool failed for rfq_id={rfq_id!r}")
        return {"status": "failed", "rfq_id": rfq_id, "error": str(e)}


@mcp.tool
def resolve_final_selection(rfq_id: str) -> dict:
    """Auto-resolve final_* for cbom rows where exactly one source (_costing/_erp/_qw)
    has data, and flag genuine multi-source conflicts for human review. Requires the
    `cbom` tool to have already run for this rfq_id.

    This is the HITL gate. Returns only a lightweight summary -- conflicting rows are
    never included in this response (an RFQ can have thousands; see
    hitl_router.py for how a human reviews/resolves them via paginated endpoints,
    not through this tool). When the response has "hitl": 1, the caller must not
    advance the routing sequence past this skill until every pending conflict for
    this rfq_id is resolved.
    """
    currency.clear_cache()  # long-lived server: pick up admin rate edits per call
    try:
        with db.duckdb_file_lock():
            return reporting_pipeline.run_resolve_final_selection(rfq_id)
    except Exception as e:
        logger.exception(f"resolve_final_selection tool failed for rfq_id={rfq_id!r}")
        return {"status": "failed", "rfq_id": rfq_id, "error": str(e)}


@mcp.tool
def generate_reports(rfq_id: str) -> dict:
    """Regenerate all 16 reports for one rfq_id, reading from whatever CBOM data
    currently exists (does not regenerate CBOM -- call the `cbom` tool first). Returns
    row counts, execution time, and any warnings/issues.
    """
    currency.clear_cache()  # long-lived server: pick up admin rate edits per call
    try:
        with db.duckdb_file_lock():
            return reporting_pipeline.run_pipeline(rfq_id)
    except Exception as e:
        logger.exception(f"generate_reports tool failed for rfq_id={rfq_id!r}")
        return {"status": "failed", "rfq_id": rfq_id, "error": str(e)}


@mcp.tool
def validate_reports(rfq_id: str) -> dict:
    """Run all per-tab business-rule validators for one rfq_id against the already-generated
    report tables. Read-only -- does not modify any data. Returns a summary with
    passed/failed counts and per-table check details. Call after generate_reports to
    confirm data quality without needing to export to Excel first.
    """
    currency.clear_cache()  # long-lived server: pick up admin rate edits per call
    try:
        with db.duckdb_file_lock():
            return reporting_pipeline.run_validate_reports(rfq_id)
    except Exception as e:
        logger.exception(f"validate_reports tool failed for rfq_id={rfq_id!r}")
        return {"status": "failed", "rfq_id": rfq_id, "error": str(e)}


def _engine_check(path: str) -> dict:
    """The CAM Formula Engine re-computes every formula of the finished workbook; where it disagrees with the value LibreOffice stored
    (array-style INDEX/MATCH, which LibreOffice stores as 0) its value is stored instead. Never fails the export. CAM_ENGINE_CHECK=0 turns it off."""
    if os.environ.get("CAM_ENGINE_CHECK", "1") == "0":
        return {"status": "skipped", "reason": "disabled (CAM_ENGINE_CHECK=0)"}
    try:
        shared = os.path.join(os.path.dirname(os.path.dirname(_THIS_DIR)), "shared")
        if shared not in sys.path:
            sys.path.insert(0, shared)
        import formula_verify
        r = formula_verify.correct(path)
        return {"status": "failed" if r["error"] else "ok", "complete": r["complete"], "formulas": r["totals"].get("formulas", 0), "exact": r["totals"].get("exact", 0),
                "corrected": r["corrected"], "different": r["totals"].get("different", 0), "diagnostics": len(r["diagnostics"]),
                "seconds": r["elapsed_seconds"], "error": r["error"]}
    except Exception as e:
        logger.warning("engine check failed for %s: %s", os.path.basename(path), e)
        return {"status": "failed", "error": f"{type(e).__name__}: {e}"[:300]}


def release_gate(result: dict) -> tuple[bool, list]:
    """Release-ready only when every report check passed, every CBOM line met its rules, and the engine checked every formula.
    Anything else is listed as a blocker (the workbook is still written; it is not labelled ready)."""
    validation = result.get("validation") or {}
    engine = result.get("engine_check") or {}
    engine_ok = engine.get("status") == "ok" and engine.get("complete") is True
    data_violations = result.get("data_violations") or []
    reasons = [f"line {v['row']} {v['part']}: {v['message']}" for v in data_violations][:20]
    reasons += [c["name"] + ": " + c["detail"] for c in validation.get("checks", []) if not c.get("passed")]
    if not validation.get("passed") and not validation.get("checks"):
        reasons.append("report validation did not run")
    if not engine_ok:
        reasons.append(f"engine check {engine.get('status')}: complete={engine.get('complete')}")
    if result.get("missing_required_inputs"):
        reasons.append("a required input is missing (see the Run Inputs tab): the run went ahead with missing values")
    return (not reasons), reasons


def _validation(rfq_id: str) -> dict:
    """The SQL report validator (validator.py) over the stored results of this RFQ. A check that could not run is a failure."""
    try:
        import validator
        import database
        with db.duckdb_file_lock():
            con = database.connect()
            try:
                return validator.validate_rfq(con, rfq_id)
            finally:
                con.close()
    except Exception as e:
        logger.exception(f"validation failed for rfq_id={rfq_id!r}")
        return {"rfq_id": rfq_id, "passed": False, "checks": [{"name": "validator", "passed": False, "detail": f"could not run: {e}"}]}


@mcp.tool
def export_reports(rfq_id: str) -> dict:
    """Export the already-generated CBOM + 16 reports for one rfq_id into a single
    consolidated Excel workbook. Does not regenerate any data -- reads whatever is
    currently stored for that rfq_id.
    """
    currency.clear_cache()  # long-lived server: pick up admin rate edits per call
    try:
        with db.duckdb_file_lock():
            result = exporter.export_excel(rfq_id)
        if result.get("status") == "success":
            # Outside the DuckDB lock: it takes seconds and needs no database. Stores each formula's value so
            # Protected View, previews and phones show numbers; never fails the export (see cached_values.py).
            result["cached_values"] = cached_values.add_cached_values(result["workbook_path"])
            result["engine_check"] = _engine_check(result["workbook_path"])
            # A forced run: each error cell gets its input problem as a hover comment. Saving drops the stored values, so the
            # values are stored again after the comments are in.
            result["forced_run"] = forced_run.annotate_error_cells(result["workbook_path"], rfq_id)
            if result["forced_run"].get("error_cells_commented") or result["forced_run"].get("blank_cells_commented"):
                result["cached_values"] = cached_values.add_cached_values(result["workbook_path"])
            # Last write: ExcelJS (the browser's workbook editor) cannot open openpyxl's absolute comment links.
            result["comment_parts_renamed"] = xlsx_rels.normalise_comment_parts(result["workbook_path"])
            result["validation"] = _validation(rfq_id)
            # The export still produces the workbook (the file is what the user needs to look at), but it says plainly whether it is
            # release-ready: only when the report validation passed for every check AND the engine checked every formula.
            result["release_ready"], result["release_blockers"] = release_gate(result)
        return result
    except Exception as e:
        logger.exception(f"export_reports tool failed for rfq_id={rfq_id!r}")
        return {"status": "failed", "rfq_id": rfq_id, "error": str(e)}


if __name__ == "__main__":
    # 0.0.0.0, not a single fixed LAN IP -- binding to one specific interface
    # address means the process refuses connections on every OTHER interface
    # (e.g. the NetBird virtual adapter) regardless of firewall rules.
    mcp.run(transport="http", host="0.0.0.0", port=8105)
