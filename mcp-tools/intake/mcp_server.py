import ast
import json
import os
import re
import subprocess
import sys
import traceback


import magic
from fastmcp import FastMCP

from bom_to_database import process_bom_to_database, process_bom_structure_to_database
from bom_processing import process_bom
from tool_calling import call_tool
# from detect_alternates import detect_alternates as _detect_alternates
# from apply_alternatives import apply_alternatives as _apply_alternatives
# from distributor_pricing.enrichment import enrich_distributors, DigikeyClient

# Initialize the FastMCP server instance
mcp = FastMCP("Intake")

# Tool name for the Postgres metadata MCP server -- points at BuLLMQuote's
# own file_metadata_db_2 (registered in Bifrost as the
# Production_FileMetedata_DB client, backed by postgres-mcp with
# DATABASE_URI=...@host.docker.internal:5432/...). The un-suffixed original
# (postgres_metadata, still on MCP Jungle) points at CAM's shared
# file_metadata_db -- using it here caused this server to find CAM's own
# file records for a colliding rfq_id (e.g. RFQ-000003 existed in both
# systems with completely different uploaded files), silently processing
# the wrong BOM/Volume files.
TARGET_METADATA_TOOL = "Production_FileMetedata_DB-execute_sql"


def _validate_id(value: str) -> str:
    """Reject IDs that contain SQL-unsafe characters before interpolation."""
    if not re.fullmatch(r'[A-Za-z0-9_\-]+', value):
        raise ValueError(f"Invalid ID format: {value!r}")
    return value


@mcp.tool()
def scan_local_file(rfq_id) -> str:
    """
    Scans an array of local paths for malware using ClamAV and returns structural metrics.
    Stage Target: 1 (ANTIVIRUS_SCANNING)
    """
    rfq_id_str = _validate_id(str(rfq_id).strip())

    pending_files = []

    # ----------------------------------------------------------------------
    # STEP A: DYNAMICALLY FETCH FILE PATHS FROM DB BASED ON RFQ_ID
    # ----------------------------------------------------------------------
    try:
        fetch_sql = f"""
                SELECT
                    file_id::text AS file_id,
                    file_path
                FROM rfq_file_telemetry
                WHERE rfq_id = '{rfq_id_str}'
                AND scan_status = 'PENDING';
            """
        print(f"[DB READ] Querying paths for RFQ: {rfq_id_str}")

        db_response = call_tool(
            tool_name=TARGET_METADATA_TOOL,
            arguments={"sql": fetch_sql}
        )
        print("\n=== DB RESPONSE FROM POSTGRES MCP ===")
        print(json.dumps(db_response, indent=2))

        raw_text = None
        # Safely extract the text string wrapper out of the JSON-RPC dictionary response
        if isinstance(db_response, dict) and "result" in db_response:
            result_node = db_response["result"]
            if "content" in result_node and result_node["content"]:
                raw_text = result_node["content"][0].get("text")

        print(f"[DEBUG] Extracted raw text for parsing: {raw_text}")

        if raw_text:
            # Safely interpret stringified single-quoted Python representations from DB
            try:
                data_payload = json.loads(raw_text.replace("'", '"'))
            except Exception:
                data_payload = ast.literal_eval(raw_text)

            rows = []
            if isinstance(data_payload, list):
                rows = data_payload
            elif isinstance(data_payload, dict):
                rows = data_payload.get("rows") or data_payload.get("data") or []

            if rows:
                pending_files = [
                        {
                            "file_id": row["file_id"],
                            "file_path": row["file_path"]
                        }
                        for row in rows
                        if isinstance(row, dict)
                        and "file_id" in row
                        and "file_path" in row
                    ]
                print(f"[DB READ] Successfully pulled paths from database: {pending_files}")

    except Exception as read_err:
        print(f"Could not pull file paths from DB for RFQ {rfq_id_str}: {read_err}")

    if not pending_files:
        return json.dumps({
            "rfq_id": rfq_id_str,
            "rfq_process_stage": 1,
            "hitl_required": False,
            "message": "No files found with PENDING status.",
            "file_records": []
        })

    processed_files_telemetry = []
    global_hitl_tripped = False

    # ----------------------------------------------------------------------
    # STEP B: VIRUS SCANNING ENGINE LOOP (Processes the entire array)
    # ----------------------------------------------------------------------
    for file_record in pending_files:

        file_id = file_record["file_id"]
        path = file_record["file_path"]

        normalized_path = os.path.normpath(
            os.path.abspath(
                os.path.expanduser(
                    path.strip().strip('"').strip("'")
                )
            )
        )

        print(f"[SCAN] Running engine on: {normalized_path}")

        if not os.path.exists(normalized_path):
            global_hitl_tripped = True
            processed_files_telemetry.append({
                "file_id": file_id,
                "file_path": normalized_path,
                "file_type": "unknown",
                "scan_status": "FAILED",
                "logs": {"error": "File path not found on disk"}
            })
            continue

        try:
            result = subprocess.run(
                ["C:\\Program Files\\ClamAV\\clamscan.exe", "--no-summary", normalized_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )

            try:
                mime_type = magic.from_file(normalized_path, mime=True)
            except Exception:
                mime_type = "unknown/excel-or-binary"

            if result.returncode == 0:
                processed_files_telemetry.append({
                    "file_id": file_id,
                    "file_path": normalized_path,
                    "file_type": mime_type,
                    "scan_status": "CLEAN",
                    "logs": {"details": "No threats detected."}
                })

            elif result.returncode == 1:
                global_hitl_tripped = True
                processed_files_telemetry.append({
                    "file_id": file_id,
                    "file_path": normalized_path,
                    "file_type": mime_type,
                    "scan_status": "INFECTED",
                    "logs": {"threat_details": result.stdout.strip()}
                })

            else:
                global_hitl_tripped = True
                processed_files_telemetry.append({
                    "file_id": file_id,
                    "file_path": normalized_path,
                    "file_type": mime_type,
                    "scan_status": "FAILED",
                    "logs": {"engine_error": result.stderr.strip()}
                })

        except Exception as e:
            global_hitl_tripped = True
            processed_files_telemetry.append({
                "file_id": file_id,
                "file_path": normalized_path,
                "file_type": "unknown",
                "scan_status": "FAILED",
                "logs": {"wrapper_exception": str(e)}
            })

    # ----------------------------------------------------------------------
    # STEP C: DATABASE UPSERT STATES
    # ----------------------------------------------------------------------
    sql_hitl_value = str(global_hitl_tripped).lower()
    print(f"\n=== CONNECTING TO METADATA DB VIA: {TARGET_METADATA_TOOL} ===")

    try:
        parent_sql = f"""
        INSERT INTO rfq_process_tracking (rfq_id, rfq_process_stage, hitl_required, triggered_by)
        VALUES ('{rfq_id_str}', 1, {sql_hitl_value}, 'SYSTEM_API')
        ON CONFLICT (rfq_id) DO UPDATE SET
            rfq_process_stage = EXCLUDED.rfq_process_stage,
            hitl_required = EXCLUDED.hitl_required,
            triggered_by = EXCLUDED.triggered_by,
            updated_at = CURRENT_TIMESTAMP;
        """
        call_tool(tool_name=TARGET_METADATA_TOOL, arguments={"sql": parent_sql})

        if processed_files_telemetry:

            for f in processed_files_telemetry:

                escaped_logs_str = json.dumps(
                    f.get("logs", {})
                ).replace("'", "''")

                file_type = str(f["file_type"]).replace("'", "''")
                scan_status = str(f["scan_status"]).replace("'", "''")
                file_id = str(f["file_id"]).replace("'", "''")
                update_sql = f"""
                UPDATE rfq_file_telemetry
                SET
                    file_type = '{file_type}',
                    scan_status = '{scan_status}',
                    execution_logs = '{escaped_logs_str}'::jsonb,
                    processed_at = CURRENT_TIMESTAMP
                WHERE file_id = '{file_id}' AND rfq_id = '{rfq_id_str}';
                """

                call_tool(
                    tool_name=TARGET_METADATA_TOOL,
                    arguments={"sql": update_sql}
                )

            print("Successfully updated file scanning telemetry.")

    except Exception as db_err:
        print(f"Failed to write scan telemetry to Postgres MCP Server: {db_err}")

    return json.dumps({
        "rfq_id": rfq_id_str,
        "rfq_process_stage": 1,
        "hitl_required": global_hitl_tripped,
        "file_records": processed_files_telemetry
    })


@mcp.tool()
def import_bom(rfq_id) -> str:
    """
    Import BOM

    Performs:
    - Schema Mapping
    - Standardization
    - Volume Expansion
    - MM Conversion
    - Consolidation
    - Save To DuckDB
    """
    rfq_id_str = _validate_id(str(rfq_id).strip())

    print(f"\n=== CONNECTING TO METADATA DB VIA: {TARGET_METADATA_TOOL} ===")

   
    try:
        bom_sql = f"""
        SELECT file_path
        FROM rfq_file_telemetry
        WHERE rfq_id = '{rfq_id_str}'
        AND file_role = 'BOM';
        """
        bom_file_res = call_tool(tool_name=TARGET_METADATA_TOOL, arguments={"sql": bom_sql})

        vol_sql = f"""
        SELECT file_path
        FROM rfq_file_telemetry
        WHERE rfq_id = '{rfq_id_str}'
        AND file_role = 'VOLUME';
        """
        vol_file_res = call_tool(tool_name=TARGET_METADATA_TOOL, arguments={"sql": vol_sql})

        bom_file = ast.literal_eval(
            bom_file_res["result"]["content"][0]["text"]
        )[0]["file_path"]

        volume_file = ast.literal_eval(
            vol_file_res["result"]["content"][0]["text"]
        )[0]["file_path"]

        

    except Exception as db_err:
        print(f"Failed to fetch file paths from DB for RFQ {rfq_id_str}: {db_err}")
        return json.dumps({
            "status": "failed",
            "error": f"Could not retrieve file paths: {db_err}",
            "traceback": traceback.format_exc()
        })

    try:

        print("\nStarting BOM Import...")

        consolidated_df, duplicate_cpn_conflicts, expanded_df = process_bom(
            bom_file=bom_file,
            volume_file=volume_file
        )

        print(
            f"\nConsolidated Rows: "
            f"{len(consolidated_df)}"
        )

        print(
            "\nSaving To DuckDB..."
        )

        process_bom_to_database(
            rfq_id, bom_file, consolidated_df
        )

        # Per-occurrence structural rows (fg, bom_level, hierarchy_multiplier,
        # local bom_qty) consolidated_df no longer carries -- persisted
        # separately so a hierarchical BOM report can be built later without
        # re-parsing the source file. Purely additive: never read by
        # enrich_bom/detect_alternates/apply_alternatives/export_enriched_bom,
        # which all still work exclusively off processed_bom_items.
        process_bom_structure_to_database(
            rfq_id, bom_file, expanded_df
        )

        return json.dumps({
            "status": "success",
            "hitl": 0,
            "rows_after_consolidation": len(consolidated_df),
            "duplicate_cpn_conflicts": duplicate_cpn_conflicts
        })

    except Exception as e:

        return json.dumps({
            "status": "failed",
            "error": str(e),
            "traceback": traceback.format_exc()
        })


# @mcp.tool()
# def enrich_bom(
#     rfq_id: str
# ):
#     """
#     Enrich every row of processed_bom_items for this RFQ using:

#     - DigiKey
#     - Element14
#     - Mouser

#     Supplier pricing is fetched exactly once per part and written back
#     into processed_bom_items. This tool does not perform alternate
#     detection or user interaction.
#     """

#     try:

#         result = enrich_distributors(
#             rfq_id
#         )

#         return result

#     except Exception as e:

#         return {
#             "status": "failed",
#             "error": str(e),
#             "traceback": traceback.format_exc()
#         }



# @mcp.tool()
# def detect_alternates(rfq_id) -> str:
#     """
#     Detect alternate manufacturer parts (same CPN, different MPN) in an
#     already-enriched processed_bom_items and populate update_alternatives
#     for user review. Must run after distributor_pricing's enrich_bom, and
#     performs no supplier lookups itself.
#     """
#     rfq_id_str = _validate_id(str(rfq_id).strip())

#     try:
#         result = _detect_alternates(rfq_id_str)
#         return json.dumps(result)

#     except Exception as e:

#         return json.dumps({
#             "status": "failed",
#             "error": str(e),
#             "traceback": traceback.format_exc()
#         })


# @mcp.tool()
# def apply_alternatives(rfq_id) -> str:
#     """
#     Apply the user's preferred-alternate selections recorded in
#     update_alternatives: for each CPN, keep only the MPN flagged
#     preferred_flag=TRUE and remove every other alternate MPN from
#     processed_bom_items. Never calls DigiKey, Element14, or Mouser.
#     """
#     rfq_id_str = _validate_id(str(rfq_id).strip())

#     try:
#         result = _apply_alternatives(rfq_id_str)
#         return json.dumps(result)

#     except Exception as e:

#         return json.dumps({
#             "status": "failed",
#             "error": str(e),
#             "traceback": traceback.format_exc()
#         })


if __name__ == "__main__":
    mcp.run(transport="http", host=os.environ.get("CAM_BIND_HOST", "0.0.0.0"), port=8002)
