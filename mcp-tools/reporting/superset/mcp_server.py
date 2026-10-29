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
_FASTMCP_ROUTER_DIR = os.path.join(_REPO_ROOT, "fastmcp-router")
if _FASTMCP_ROUTER_DIR not in sys.path:
    sys.path.append(_FASTMCP_ROUTER_DIR)
import db

mcp = FastMCP("cbom-reporting")


@mcp.tool
def cbom(rfq_id: str) -> dict:
    """Regenerate only the CBOM table for one rfq_id, from the existing (read-only)
    input tables. Does not touch the 16 downstream reports. Returns row counts,
    execution time, and any warnings.
    """
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
    try:
        with db.duckdb_file_lock():
            return reporting_pipeline.run_validate_reports(rfq_id)
    except Exception as e:
        logger.exception(f"validate_reports tool failed for rfq_id={rfq_id!r}")
        return {"status": "failed", "rfq_id": rfq_id, "error": str(e)}


@mcp.tool
def export_reports(rfq_id: str) -> dict:
    """Export the already-generated CBOM + 16 reports for one rfq_id into a single
    consolidated Excel workbook. Does not regenerate any data -- reads whatever is
    currently stored for that rfq_id.
    """
    try:
        with db.duckdb_file_lock():
            return exporter.export_excel(rfq_id)
    except Exception as e:
        logger.exception(f"export_reports tool failed for rfq_id={rfq_id!r}")
        return {"status": "failed", "rfq_id": rfq_id, "error": str(e)}


if __name__ == "__main__":
    # 0.0.0.0, not a single fixed LAN IP -- binding to one specific interface
    # address means the process refuses connections on every OTHER interface
    # (e.g. the NetBird virtual adapter) regardless of firewall rules.
    mcp.run(transport="http", host="0.0.0.0", port=8105)
