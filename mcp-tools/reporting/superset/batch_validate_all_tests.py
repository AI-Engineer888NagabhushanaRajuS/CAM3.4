"""Bulk end-to-end validation across every test_N BOM folder under the project root.

Discovers every test_{x} folder, classifies its input files (Scrub BOM / QuoteWin /
Costing Sheet, if present), runs the full pipeline (input tables -> CBOM -> costing
enrichment [if applicable] -> final selection -> 16 report tables -> Excel export) once
or twice per folder (twice when a Costing Sheet is present: with and without it), runs a
validation suite against each run, and writes per-folder validation_summary.md /
issues_found.md plus one master_test_summary.md at the project root.

A failure at any stage for any one scenario is caught and recorded -- it never stops
the rest of that folder's scenarios or any other folder.
"""

import glob
import json
import os
import re
import shutil
import sys
import time
import traceback
from datetime import datetime, timezone

REPORTING_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(REPORTING_MODULE_DIR, ".."))
sys.path.insert(0, REPORTING_MODULE_DIR)

import database  # noqa: E402
import helpers  # noqa: E402
import queries  # noqa: E402
import reporting_pipeline  # noqa: E402
import exporter  # noqa: E402
from templates import excel_mappings as mappings  # noqa: E402

from scrub_bom_processing import process_scrub_bom_workbook  # noqa: E402
from scrub_bom_to_database import (  # noqa: E402
    process_scrub_bom_to_database, process_volume_to_database, process_batch_to_database,
)
from quote_win_processing import process_quote_win  # noqa: E402
from quote_win_to_database import process_quote_win_to_database  # noqa: E402
from costing_sheet_processing import process_costing_sheet  # noqa: E402
from costing_sheet_to_database import process_costing_sheet_to_database  # noqa: E402

import openpyxl  # noqa: E402
import duckdb  # noqa: E402


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def natural_key(path):
    m = re.search(r"test_(\d+)$", os.path.basename(path))
    return int(m.group(1)) if m else 10**9


def discover_test_folders():
    folders = [
        f for f in glob.glob(os.path.join(PROJECT_ROOT, "test_*"))
        if os.path.isdir(f) and re.match(r"test_\d+$", os.path.basename(f))
    ]
    return sorted(folders, key=natural_key)


_QW_KEYWORDS = ("qw", "quotewin", "quote win", "awards", "float")


def classify_files(folder):
    """Returns {"scrub": path|None, "quotewin": path|None, "costing": path|None}.

    Excludes this script's own output naming convention (CBOM_Report*.xlsx) -- outputs
    are written into the same folder as inputs (per spec), so a second run over an
    already-processed folder must not treat its own prior output as a candidate input
    file. Without this, "CBOM_Report_With_Costing.xlsx" (which contains the substring
    "costing") could even be misclassified as the real Costing Sheet on a re-run.
    """
    files = [
        f for f in os.listdir(folder)
        if f.lower().endswith((".xlsx", ".xls")) and not f.startswith("CBOM_Report")
    ]
    costing = None
    remaining = []
    for f in files:
        if "cost" in f.lower():
            costing = f
        else:
            remaining.append(f)
    quotewin = None
    for f in remaining:
        if any(k in f.lower() for k in _QW_KEYWORDS):
            quotewin = f
            break
    scrub = None
    for f in remaining:
        if f != quotewin:
            scrub = f
            break
    return {
        "scrub": os.path.join(folder, scrub) if scrub else None,
        "quotewin": os.path.join(folder, quotewin) if quotewin else None,
        "costing": os.path.join(folder, costing) if costing else None,
    }


def load_input_dataframes(files, issues):
    """Parses (not yet DB-writes) the Scrub BOM workbook, QuoteWin file, and Costing
    Sheet (if present) once per folder -- shared across both with/without-costing
    scenarios so the LLM-backed header mapping only runs once per file per folder.
    """
    scrub_result = process_scrub_bom_workbook(files["scrub"])
    quote_df = process_quote_win(files["quotewin"])
    costing_df = None
    if files["costing"]:
        costing_df = process_costing_sheet(files["costing"])
    return scrub_result, quote_df, costing_df


def clear_input_rows(rfq_id):
    # Each process_*_to_database() call opens/closes its own raw connection to
    # input_db.duckdb directly (see scrub_bom_to_database.py/quote_win_to_database.py/
    # costing_sheet_to_database.py) -- mirror that here for the pre-clear, rather than
    # going through database.connect() (which attaches input_db READ-ONLY).
    import config
    con = duckdb.connect(config.INPUT_DB_PATH)
    try:
        for tbl in ("scrub_bom_items", "quote_win", "volume", "batch", "costing_sheet"):
            con.execute(f"DELETE FROM {tbl} WHERE rfq_id = {helpers.sql_quote(rfq_id)}")
    finally:
        con.close()


def populate_input_tables(rfq_id, scrub_result, quote_df, costing_df):
    clear_input_rows(rfq_id)
    counts = {}
    r = process_scrub_bom_to_database(rfq_id, scrub_result["scrub_bom"])
    counts["scrub_bom_items"] = r.get("rows_inserted", len(scrub_result["scrub_bom"]))
    r = process_volume_to_database(rfq_id, scrub_result["volume"])
    counts["volume"] = r.get("rows_inserted", len(scrub_result["volume"]))
    r = process_batch_to_database(rfq_id, scrub_result["batch"])
    counts["batch"] = r.get("rows_inserted", len(scrub_result["batch"]))
    r = process_quote_win_to_database(rfq_id, quote_df)
    counts["quote_win"] = r.get("rows_inserted", len(quote_df))
    if costing_df is not None:
        r = process_costing_sheet_to_database(rfq_id, costing_df)
        counts["costing_sheet"] = r.get("rows_inserted", len(costing_df))
    return counts


def validate_run(rfq_id, input_counts, cbom_result, export_result, workbook_path, include_costing):
    """Runs the standard validation suite against one completed scenario. Returns
    (checks: dict[name -> {"pass": bool, "detail": str}], issues: list[dict]).
    """
    checks = {}
    issues = []
    con = database.connect()
    rfq_lit = helpers.sql_quote(rfq_id)
    try:
        # 1. Input tables populated -- volume/batch are legitimately optional (some real
        # Scrub BOM exports have no Settings/Batch sheet at all; detect_volumes() already
        # degrades that to a single implicit volume), so only scrub_bom_items/quote_win
        # (and costing_sheet, when this scenario includes one) are actually mandatory.
        mandatory_tables = {"scrub_bom_items", "quote_win"}
        if include_costing:
            mandatory_tables.add("costing_sheet")
        populated = all(input_counts.get(k, 0) > 0 for k in mandatory_tables)
        checks["input_tables_populated"] = {"pass": populated, "detail": json.dumps(input_counts)}
        if not populated:
            issues.append({"stage": "input tables", "severity": "Critical",
                            "detail": f"One or more mandatory input tables have zero rows: {input_counts}"})

        # 2. CBOM generated
        cbom_row_count = cbom_result.get("cbom_row_count", 0) if cbom_result else 0
        checks["cbom_generated"] = {"pass": cbom_row_count > 0, "detail": f"{cbom_row_count} rows"}
        if cbom_row_count == 0:
            issues.append({"stage": "cbom", "severity": "Critical", "detail": "CBOM generation produced 0 rows"})

        # 3. Row counts reasonable (cbom rows should be a positive multiple-ish of scrub rows)
        scrub_rows = input_counts.get("scrub_bom_items", 0)
        ratio_ok = cbom_row_count == 0 or scrub_rows == 0 or (0.3 <= cbom_row_count / max(scrub_rows, 1) <= 20)
        checks["row_counts_reasonable"] = {
            "pass": ratio_ok,
            "detail": f"cbom={cbom_row_count}, scrub_bom_items={scrub_rows}",
        }
        if not ratio_ok:
            issues.append({"stage": "cbom", "severity": "Major",
                            "detail": f"cbom row count ({cbom_row_count}) implausible vs scrub_bom_items ({scrub_rows})"})

        # 4. No duplicate-key issues
        dup_bom_item = con.execute(
            f"SELECT COUNT(*) FROM (SELECT bom_item_id FROM input_db.scrub_bom_items "
            f"WHERE rfq_id = {rfq_lit} GROUP BY bom_item_id HAVING COUNT(*) > 1)"
        ).fetchone()[0]
        dup_cbom = con.execute(
            f"SELECT COUNT(*) FROM (SELECT bom_item_id, volume_no FROM cbom_db.cbom "
            f"WHERE rfq_id = {rfq_lit} GROUP BY bom_item_id, volume_no HAVING COUNT(*) > 1)"
        ).fetchone()[0]
        no_dupes = dup_bom_item == 0 and dup_cbom == 0
        checks["no_duplicate_keys"] = {"pass": no_dupes, "detail": f"dup scrub bom_item_id={dup_bom_item}, dup cbom (bom_item_id,volume_no)={dup_cbom}"}
        if not no_dupes:
            issues.append({"stage": "cbom", "severity": "Major", "detail": f"Duplicate keys found: scrub={dup_bom_item}, cbom={dup_cbom}"})

        # 5. No orphaned rows (cbom rows with no matching scrub_bom_items row)
        orphaned = con.execute(
            f"SELECT COUNT(*) FROM cbom_db.cbom c "
            f"LEFT JOIN input_db.scrub_bom_items s ON s.bom_item_id = c.bom_item_id "
            f"WHERE c.rfq_id = {rfq_lit} AND COALESCE(c.is_assembly, FALSE) = FALSE AND s.bom_item_id IS NULL"
        ).fetchone()[0]
        checks["no_orphaned_rows"] = {"pass": orphaned == 0, "detail": f"{orphaned} orphaned cbom rows"}
        if orphaned > 0:
            issues.append({"stage": "cbom", "severity": "Major", "detail": f"{orphaned} cbom rows have no matching scrub_bom_items row"})

        # 6. No missing mandatory fields
        missing_fields = con.execute(
            f"SELECT COUNT(*) FROM cbom_db.cbom WHERE rfq_id = {rfq_lit} AND is_data = TRUE "
            f"AND (cpn IS NULL OR fg IS NULL)"
        ).fetchone()[0]
        checks["no_missing_mandatory_fields"] = {"pass": missing_fields == 0, "detail": f"{missing_fields} rows missing cpn/fg"}
        if missing_fields > 0:
            issues.append({"stage": "cbom", "severity": "Major", "detail": f"{missing_fields} is_data rows missing cpn or fg"})

        # 7. Multi-volume detection
        detected_volumes = queries.detect_volumes(con, rfq_lit)
        checks["multi_volume_detection"] = {"pass": len(detected_volumes) >= 1, "detail": f"volumes={detected_volumes}"}

        # 8. Export completed
        export_ok = bool(export_result) and export_result.get("status") == "success" and os.path.isfile(workbook_path or "")
        checks["export_completed"] = {"pass": export_ok, "detail": json.dumps({k: v for k, v in (export_result or {}).items() if k != "worksheet_names"})}
        if not export_ok:
            issues.append({"stage": "export", "severity": "Critical", "detail": f"Export did not complete successfully: {export_result}"})

        # 9. Workbook opens + RFQ filtering + multi-volume sheets
        if export_ok:
            try:
                wb = openpyxl.load_workbook(workbook_path, data_only=False, read_only=True)
                checks["workbook_opens"] = {"pass": True, "detail": f"{len(wb.sheetnames)} sheets"}

                cbom_sheet = wb["CBOM"] if "CBOM" in wb.sheetnames else None
                cbom_sheet_rows = (cbom_sheet.max_row - 1) if cbom_sheet else 0  # minus header
                checks["rfq_filtering"] = {
                    "pass": cbom_sheet_rows == cbom_row_count,
                    "detail": f"exported CBOM sheet rows={cbom_sheet_rows}, DB cbom rows for this rfq={cbom_row_count}",
                }
                if cbom_sheet_rows != cbom_row_count:
                    issues.append({"stage": "export", "severity": "Major",
                                    "detail": f"Exported CBOM sheet row count ({cbom_sheet_rows}) does not match DB cbom row count ({cbom_row_count}) for this rfq_id"})

                vl_sheets = [n for n in wb.sheetnames if n.startswith("7.0 CBOM VL-")]
                checks["multi_volume_reports"] = {
                    "pass": len(vl_sheets) == len(detected_volumes),
                    "detail": f"expected {len(detected_volumes)} VL sheets, found {len(vl_sheets)}",
                }
                if len(vl_sheets) != len(detected_volumes):
                    issues.append({"stage": "export", "severity": "Major",
                                    "detail": f"Expected {len(detected_volumes)} '7.0 CBOM VL-n' sheets, found {len(vl_sheets)}"})
                wb.close()
            except Exception as e:
                checks["workbook_opens"] = {"pass": False, "detail": str(e)}
                issues.append({"stage": "export", "severity": "Critical", "detail": f"openpyxl failed to open exported workbook: {e}"})
        else:
            checks["workbook_opens"] = {"pass": False, "detail": "export did not complete"}
            checks["rfq_filtering"] = {"pass": False, "detail": "skipped -- export did not complete"}
            checks["multi_volume_reports"] = {"pass": False, "detail": "skipped -- export did not complete"}

    finally:
        con.close()

    return checks, issues


def run_scenario(folder_name, rfq_id, output_name, scrub_result, quote_df, costing_df, include_costing, dest_dir):
    result = {
        "rfq_id": rfq_id, "output_name": output_name, "include_costing": include_costing,
        "started_at": _now(), "stages_completed": [], "status": "unknown",
        "checks": {}, "issues": [],
    }
    start = time.time()
    workbook_path = None
    try:
        input_counts = populate_input_tables(rfq_id, scrub_result, quote_df, costing_df if include_costing else None)
        result["input_counts"] = input_counts
        result["stages_completed"].append("input_tables")

        cbom_result = reporting_pipeline.run_cbom(rfq_id)
        result["cbom_result"] = cbom_result
        result["stages_completed"].append("cbom")

        if include_costing and costing_df is not None:
            costing_result = reporting_pipeline.run_costing_enrichment(rfq_id)
            result["costing_enrichment_result"] = costing_result
            result["stages_completed"].append("costing_enrichment")

        fs_result = reporting_pipeline.run_resolve_final_selection(rfq_id)
        result["final_selection_result"] = fs_result
        result["stages_completed"].append("final_selection")

        reports_result = reporting_pipeline.run_pipeline(rfq_id)
        result["reports_result"] = reports_result
        result["stages_completed"].append("16_report_tables")

        export_result = exporter.export_excel(rfq_id)
        result["export_result"] = export_result
        result["stages_completed"].append("export")

        src_path = export_result.get("workbook_path")
        workbook_path = os.path.join(dest_dir, output_name)
        shutil.copy2(src_path, workbook_path)
        if os.path.abspath(src_path) != os.path.abspath(workbook_path):
            os.remove(src_path)
        result["workbook_path"] = workbook_path

        checks, issues = validate_run(rfq_id, input_counts, cbom_result, export_result, workbook_path, include_costing)
        result["checks"] = checks
        result["issues"] = issues
        result["status"] = "PASS" if all(c["pass"] for c in checks.values()) and not any(i["severity"] == "Critical" for i in issues) else "FAIL"

    except Exception as e:
        result["status"] = "ERROR"
        result["error"] = str(e)
        result["traceback"] = traceback.format_exc()
        result["issues"].append({
            "stage": result["stages_completed"][-1] if result["stages_completed"] else "input_tables",
            "severity": "Critical",
            "detail": f"{type(e).__name__}: {e}",
        })

    result["duration_seconds"] = round(time.time() - start, 2)
    result["ended_at"] = _now()
    return result


def write_validation_summary(folder, folder_name, scenario_results):
    lines = [f"# Validation Summary -- {folder_name}", "", f"Generated: {_now()}", ""]
    for res in scenario_results:
        lines.append(f"## Scenario: {res['output_name']} (rfq_id={res['rfq_id']})")
        lines.append("")
        lines.append(f"- Costing Sheet used: {'Yes' if res['include_costing'] else 'No'}")
        lines.append(f"- Overall result: **{res['status']}**")
        lines.append(f"- Execution time: {res['duration_seconds']}s")
        lines.append(f"- Stages completed: {', '.join(res['stages_completed']) or '(none)'}")
        if "input_counts" in res:
            lines.append(f"- Input table row counts: {json.dumps(res['input_counts'])}")
        if "cbom_result" in res:
            lines.append(f"- CBOM row count: {res['cbom_result'].get('cbom_row_count')}, priced: {res['cbom_result'].get('priced_row_count')}, detected volumes: {res['cbom_result'].get('detected_volumes')}")
        if "reports_result" in res:
            lines.append(f"- 16 report table counts: {json.dumps(res['reports_result'].get('report_row_counts', {}))}")
        if "export_result" in res:
            er = res["export_result"]
            lines.append(f"- Export: status={er.get('status')}, worksheets={er.get('worksheet_count')}, time={er.get('execution_time_seconds')}s")
        if "workbook_path" in res:
            lines.append(f"- Workbook: `{os.path.basename(res['workbook_path'])}`")
        lines.append("")
        lines.append("### Validation checks")
        for name, c in res.get("checks", {}).items():
            mark = "PASS" if c["pass"] else "FAIL"
            lines.append(f"- [{mark}] {name}: {c['detail']}")
        if res.get("error"):
            lines.append("")
            lines.append(f"### Error\n\n```\n{res['error']}\n```")
        lines.append("")
    with open(os.path.join(folder, "validation_summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_issues_found(folder, folder_name, scenario_results):
    all_issues = []
    for res in scenario_results:
        for issue in res.get("issues", []):
            all_issues.append((res, issue))
    if not all_issues:
        path = os.path.join(folder, "issues_found.md")
        if os.path.exists(path):
            os.remove(path)
        return False
    lines = [f"# Issues Found -- {folder_name}", "", f"Generated: {_now()}", ""]
    for res, issue in all_issues:
        lines.append(f"## {res['output_name']} (rfq_id={res['rfq_id']}) -- {issue['stage']}")
        lines.append("")
        lines.append(f"- Test folder: {folder_name}")
        lines.append(f"- RFQ ID: {res['rfq_id']}")
        lines.append(f"- Date/time: {res['started_at']}")
        lines.append(f"- Pipeline stage: {issue['stage']}")
        lines.append(f"- Error/detail: {issue['detail']}")
        lines.append(f"- Severity: {issue['severity']}")
        lines.append(f"- Execution continued: {'Yes' if res['status'] != 'ERROR' or issue is not res.get('issues', [None])[-1] else 'No (fatal for this scenario)'}")
        lines.append(f"- Affected reports: {res['output_name']}")
        lines.append("")
    with open(os.path.join(folder, "issues_found.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return True


def main():
    overall_start = time.time()
    folders = discover_test_folders()
    print(f"Discovered {len(folders)} test folders: {[os.path.basename(f) for f in folders]}")

    master = {
        "started_at": _now(), "folders": [], "total_folders": len(folders),
        "with_costing": 0, "without_costing_only": 0, "total_scenarios": 0,
        "scenario_pass": 0, "scenario_fail": 0, "scenario_error": 0,
        "failed_folders": [], "all_issues": [],
    }

    for folder in folders:
        folder_name = os.path.basename(folder)
        print(f"\n=== {folder_name} ===")
        folder_entry = {"folder": folder_name, "scenarios": []}
        try:
            files = classify_files(folder)
            if not files["scrub"] or not files["quotewin"]:
                raise ValueError(f"Could not classify input files: {files}")
            print(f"  files: scrub={os.path.basename(files['scrub'])}, quotewin={os.path.basename(files['quotewin'])}, costing={os.path.basename(files['costing']) if files['costing'] else None}")

            scrub_result, quote_df, costing_df = load_input_dataframes(files, master["all_issues"])

            has_costing = files["costing"] is not None
            scenarios = []
            if has_costing:
                master["with_costing"] += 1
                scenarios = [
                    (f"{folder_name}_with_costing", "CBOM_Report_With_Costing.xlsx", True),
                    (f"{folder_name}_without_costing", "CBOM_Report_Without_Costing.xlsx", False),
                ]
            else:
                master["without_costing_only"] += 1
                scenarios = [(folder_name, "CBOM_Report.xlsx", False)]

            scenario_results = []
            for rfq_id, output_name, include_costing in scenarios:
                print(f"  running scenario: {output_name} (rfq_id={rfq_id}, include_costing={include_costing})")
                res = run_scenario(folder_name, rfq_id, output_name, scrub_result, quote_df, costing_df, include_costing, folder)
                print(f"    -> {res['status']} in {res['duration_seconds']}s")
                scenario_results.append(res)
                master["total_scenarios"] += 1
                if res["status"] == "PASS":
                    master["scenario_pass"] += 1
                elif res["status"] == "FAIL":
                    master["scenario_fail"] += 1
                else:
                    master["scenario_error"] += 1
                for issue in res.get("issues", []):
                    master["all_issues"].append({"folder": folder_name, "rfq_id": rfq_id, **issue})

            write_validation_summary(folder, folder_name, scenario_results)
            had_issues = write_issues_found(folder, folder_name, scenario_results)
            folder_entry["scenarios"] = [{"rfq_id": r["rfq_id"], "status": r["status"], "output_name": r["output_name"]} for r in scenario_results]
            folder_entry["had_issues"] = had_issues
            if any(r["status"] != "PASS" for r in scenario_results):
                master["failed_folders"].append(folder_name)

        except Exception as e:
            print(f"  FOLDER-LEVEL FAILURE: {e}")
            folder_entry["folder_level_error"] = f"{type(e).__name__}: {e}"
            folder_entry["traceback"] = traceback.format_exc()
            master["failed_folders"].append(folder_name)
            master["all_issues"].append({
                "folder": folder_name, "rfq_id": None, "stage": "file discovery/classification",
                "severity": "Critical", "detail": str(e),
            })
            try:
                with open(os.path.join(folder, "issues_found.md"), "w", encoding="utf-8") as f:
                    f.write(f"# Issues Found -- {folder_name}\n\nFolder-level failure before any scenario could run:\n\n```\n{traceback.format_exc()}\n```\n")
            except Exception:
                pass

        master["folders"].append(folder_entry)

    master["ended_at"] = _now()
    master["total_duration_seconds"] = round(time.time() - overall_start, 2)

    write_master_summary(master)
    print(f"\nDone in {master['total_duration_seconds']}s. Master summary written.")
    return master


def write_master_summary(master):
    lines = [
        "# Master Test Summary -- Reporting Module Bulk Validation", "",
        f"Generated: {master['ended_at']}", f"Total duration: {master['total_duration_seconds']}s", "",
        "## Overview", "",
        f"- Total test folders discovered: {master['total_folders']}",
        f"- Total test folders executed: {len(master['folders'])}",
        f"- Folders with Costing Sheet (2 runs each): {master['with_costing']}",
        f"- Folders without Costing Sheet (1 run each): {master['without_costing_only']}",
        f"- Total scenarios executed: {master['total_scenarios']}",
        f"- Scenarios PASS: {master['scenario_pass']}",
        f"- Scenarios FAIL: {master['scenario_fail']}",
        f"- Scenarios ERROR: {master['scenario_error']}",
        f"- Failed/problem folders: {', '.join(master['failed_folders']) if master['failed_folders'] else 'None'}",
        "",
        "## Per-folder results", "",
    ]
    for entry in master["folders"]:
        lines.append(f"### {entry['folder']}")
        if entry.get("folder_level_error"):
            lines.append(f"- **FOLDER-LEVEL FAILURE**: {entry['folder_level_error']}")
        else:
            for sc in entry["scenarios"]:
                lines.append(f"- {sc['output_name']} (rfq_id={sc['rfq_id']}): **{sc['status']}**")
            lines.append(f"- Issues documented: {'Yes (see issues_found.md)' if entry.get('had_issues') else 'No'}")
        lines.append("")

    lines.append("## All issues discovered (across every folder)")
    lines.append("")
    if master["all_issues"]:
        for issue in master["all_issues"]:
            lines.append(f"- **{issue['folder']}** / {issue.get('rfq_id')} / {issue['stage']} ({issue['severity']}): {issue['detail']}")
    else:
        lines.append("None.")
    lines.append("")

    lines.append("## Production readiness assessment")
    lines.append("")
    critical_count = sum(1 for i in master["all_issues"] if i["severity"] == "Critical")
    if master["scenario_error"] == 0 and critical_count == 0:
        lines.append("No critical issues or unhandled errors across any test folder/scenario. Module appears production-ready pending review of any Major/Minor issues listed above.")
    else:
        lines.append(f"{master['scenario_error']} scenario(s) errored and {critical_count} critical issue(s) were found -- review before considering the module production-ready. See per-folder issues_found.md files for detail.")

    with open(os.path.join(PROJECT_ROOT, "master_test_summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    result = main()
    with open(os.path.join(REPORTING_MODULE_DIR, "_batch_validate_raw_result.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
