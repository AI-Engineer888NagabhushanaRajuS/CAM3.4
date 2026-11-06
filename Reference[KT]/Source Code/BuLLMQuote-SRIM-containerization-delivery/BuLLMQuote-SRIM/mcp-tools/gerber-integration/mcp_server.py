import ast
import json
import re
import traceback

from fastmcp import FastMCP

from extraction_pipeline import run_geometry_and_checklist
from gerber_tables import save_gerber_checklist, save_gerber_geometry
from tool_calling import call_tool

mcp = FastMCP("Gerber-Integration")

# Production_FileMetedata_DB-execute_sql -- BuLLMQuote's own file_metadata_db_2,
# same tool name intake/mcp_server.py already uses (both registered in Bifrost,
# replacing MCP Jungle's postgres_metadata_2__execute_sql). NOT the un-suffixed
# postgres_metadata__execute_sql (still on MCP Jungle), which points at CAM's
# shared file_metadata_db (see mcp-tools/intake/mcp_server.py's own comment on
# this -- the RFQ-000003 bug this platform already hit once from getting this
# wrong).
TARGET_METADATA_TOOL = "Production_FileMetedata_DB-execute_sql"


def _validate_id(value: str) -> str:
    """Reject IDs that contain SQL-unsafe characters before interpolation."""
    if not re.match(r'^[A-Za-z0-9_\-]+$', value):
        raise ValueError(f"Invalid ID format: {value!r}")
    return value


def _extract_result_json(response):
    """A tools/call response's real payload lives in content[0].text --
    confirmed empirically for BOTH the postgres-mcp tool (a Python-repr
    string, single-quoted -- ast.literal_eval) and the Gerber server's own
    tools (real JSON, double-quoted -- json.loads). Deliberately does NOT
    trust `structuredContent`: for Production_FileMetedata_DB-execute_sql it comes
    back as a generic wrapper `{"result": [{"text": "...", ...}]}`, not the
    parsed rows -- reading it first silently produced empty results and made
    extract_features wrongly report "skipped" even with a real Gerber file
    present. content[0].text is what intake/mcp_server.py's own
    scan_local_file already relies on exclusively -- same convention here."""
    if not isinstance(response, dict):
        raise ValueError(f"Unexpected MCP response shape: {response!r}")
    result = response.get("result")
    if not isinstance(result, dict):
        raise ValueError(f"No 'result' in MCP response: {response!r}")

    content = result.get("content")
    if content and isinstance(content, list):
        raw_text = content[0].get("text")
        if raw_text:
            try:
                return json.loads(raw_text)
            except (json.JSONDecodeError, TypeError):
                return ast.literal_eval(raw_text)

    raise ValueError(f"Could not find content[0].text in: {result!r}")


def _fetch_active_gerber_path(rfq_id_str: str):
    """Returns the staged GERBER_ZIP file_path for this rfq_id, or None if no
    active Gerber upload exists -- the presence check the whole "optional
    input, graceful skip if absent" contract hinges on (same pattern as the
    dormant ERP tool / costing_sheet's own optional-input handling)."""
    fetch_sql = f"""
        SELECT file_path
        FROM rfq_file_telemetry
        WHERE rfq_id = '{rfq_id_str}'
          AND file_role = 'GERBER_ZIP'
          AND is_active = TRUE
        LIMIT 1;
    """
    db_response = call_tool(tool_name=TARGET_METADATA_TOOL, arguments={"sql": fetch_sql})
    try:
        rows = _extract_result_json(db_response)
    except ValueError:
        return None
    if isinstance(rows, dict):
        rows = rows.get("rows") or rows.get("data") or []
    if not rows:
        return None
    first = rows[0]
    return first.get("file_path") if isinstance(first, dict) else None


@mcp.tool()
def extract_features(rfq_id) -> str:
    """
    Gerber feature extraction for RFQ_Flow's optional Gerber ZIP input.

    Position: RFQ_Flow's routing_sequence, immediately after
    intake__import_bom, before distributor__enrich_bom.

    If no active GERBER_ZIP file exists for this rfq_id (the common case --
    Gerber upload is optional), this returns immediately with hitl=0 and no
    extraction/DB write, so the pipeline advances straight to
    distributor__enrich_bom. When a Gerber file IS present, it runs Gerber
    geometry + checklist extraction locally (extraction_pipeline.py -- ported
    from the formerly-separate PCBA-FE MCP server, no external process/MCP
    hop involved anymore), writes both results into gerber_geometry/
    gerber_checklist in bom_storage.duckdb, and returns hitl=1 to pause for
    the Gerber HITL review grid.
    """
    rfq_id_str = _validate_id(str(rfq_id).strip())

    # STEP A: presence check -- the whole "always in the sequence, no-op
    # when nothing to do" contract.
    try:
        gerber_path = _fetch_active_gerber_path(rfq_id_str)
    except Exception as e:
        return json.dumps({
            "status": "failed",
            "error": f"Could not check for a Gerber upload: {e}",
            "traceback": traceback.format_exc(),
        })

    if not gerber_path:
        return json.dumps({
            "status": "skipped",
            "hitl": 0,
            "rfq_id": rfq_id_str,
            "message": "No Gerber ZIP uploaded for this RFQ -- feature extraction not applicable.",
        })

    # STEP B: extraction -- geometry and checklist both come from the same
    # archive_path in one local call now (see extraction_pipeline.py's own
    # module docstring for exactly which slice of the original PCBA-FE
    # pipeline this replicates, and why the rest is deliberately excluded).
    try:
        geometry, checklist = run_geometry_and_checklist(gerber_path)
    except Exception as e:
        return json.dumps({
            "status": "failed",
            "error": f"Gerber extraction failed: {e}",
            "traceback": traceback.format_exc(),
        })

    if not geometry.get("success", True) and geometry.get("error_message"):
        return json.dumps({
            "status": "failed",
            "error": f"Gerber geometry extraction failed: {geometry.get('error_message')}",
        })
    if checklist.get("success") is False:
        return json.dumps({
            "status": "failed",
            "error": f"Gerber checklist extraction failed: {checklist.get('error_message')}",
        })

    # STEP C: persist -- this platform's own tables, NOT the Gerber server's
    # own quote_runs/checklist_records (which are only reachable via its
    # pricing pipeline -- see this session's investigation notes).
    try:
        save_gerber_geometry(rfq_id_str, geometry)
        save_gerber_checklist(rfq_id_str, checklist.get("fields") or [])
    except Exception as e:
        return json.dumps({
            "status": "failed",
            "error": f"Could not save extracted Gerber data: {e}",
            "traceback": traceback.format_exc(),
        })

    return json.dumps({
        "status": "success",
        "hitl": 1,
        "rfq_id": rfq_id_str,
        "geometry_summary": {
            "width_mm": geometry.get("width_mm"),
            "height_mm": geometry.get("height_mm"),
            "layer_count": geometry.get("layer_count"),
            "confidence": geometry.get("confidence"),
        },
        "checklist_summary": {
            "total": checklist.get("total"),
            "extracted": checklist.get("extracted"),
            "absent": checklist.get("absent"),
        },
    })


if __name__ == "__main__":
    # Bound to this machine's NetBird mesh IP (user's explicit choice), same
    # as the Gerber PCBA-FE server -- reachable by MCP Jungle over that mesh.
    # Unlike PCBA-FE's SDK (mcp.server.fastmcp), this fastmcp package (v3.4.2)
    # has no Host-header/DNS-rebinding allowlist or fail-closed-without-token
    # behavior, so no equivalent transport_security fix is needed here.
    mcp.run(transport="http", host="100.121.36.255", port=8007)
