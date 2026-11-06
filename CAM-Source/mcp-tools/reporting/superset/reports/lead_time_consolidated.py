"""Python port of the Lead Time Consolidated report (Laravel PHP).

Three layers, mirroring the PHP pipeline:
  1. lead_time_consolidated_rows() — port of
     BlockthreeController::lead_time_consolidate(): the BOM-wide lead-time
     rollup (no FG grouping, unlike Lead Time (FG Wise)), matching the
     input/output JSON documented in lead-time-consolidated-report.md. This
     is the exact shape persisted to lead_time_cons_json.json_desc.
  2. lead_time_consolidated_sheet_rows() — port of
     LeadTimeConsolidatedExportExcelFormula::array(): header row, one row
     per lead-time bucket (count literal, percentage left for a live
     formula), and a trailing Grand Total row whose count is a live SUM()
     and whose percentage cells are all self-referential IF() formulas
     against the Grand Total's own row — note that row number equals
     len(output) itself (count($output) in PHP), not len(output) - 1, a
     detail that was easy to get wrong (see the .md's "corrected during
     review" note).
  3. build_lead_time_consolidated_sheet() — port of the same class's
     registerEvents(): header/data/Grand-Total row coloring (the Grand Total
     scan stops at the first match, mirroring the PHP's `break`), percentage
     number formatting, borders, and column auto-sizing.

No DB access happens here — bom_details_json_data/rfqs are supplied by the
caller, and the DB write (`lead_time_cons_json` table upsert) in the
original PHP is out of scope, consistent with every other port in this
project.
"""

import re

from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

_HEADER_FILL = PatternFill("solid", fgColor="2F5496")
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_HEADER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
_DATA_FILL = PatternFill("solid", fgColor="F2F6FC")
_DATA_ALIGN = Alignment(vertical="center", wrap_text=True)
_TOTAL_FILL = PatternFill("solid", fgColor="FFD966")
_TOTAL_FONT = Font(bold=True)
_THIN_SIDE = Side(style="thin", color="000000")
_THIN_BORDER = Border(left=_THIN_SIDE, right=_THIN_SIDE, top=_THIN_SIDE, bottom=_THIN_SIDE)


def _natural_key(value):
    """Mirrors PHP's ksort(..., SORT_NATURAL) for lead-time-week labels."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", str(value))]


def lead_time_consolidated_rows(payload):
    """Port of BlockthreeController::lead_time_consolidate(): the BOM-wide lead-time rollup.

    payload: {"bom_details_json_data": [{"CPN":...}, ...],
              "rfqs": [{"cpn":..., "is_L1": bool, "lead_times":..., "volume_no":...}, ...]}
    returns: list of {"lead_time_weeks", "count_of_part_number", "percentage"}
        dicts — the exact shape persisted to lead_time_cons_json.json_desc.
    """
    scrub_items = payload.get("bom_details_json_data", [])
    rfqs = payload.get("rfqs", [])

    bom_cpns = {entry.get("CPN", "") for entry in scrub_items if entry.get("CPN")}

    rfq_cpns_all = set()
    rfq_has_l1 = set()
    rfq_has_valid_l1_lead = set()
    for rfq in rfqs:
        cpn = str(rfq.get("cpn", ""))
        rfq_cpns_all.add(cpn)
        lead_time = str(rfq.get("lead_times") or "").strip()
        if rfq.get("is_L1"):
            rfq_has_l1.add(cpn)
            if lead_time not in ("", "0"):
                rfq_has_valid_l1_lead.add(cpn)

    l1_rfqs = sorted((r for r in rfqs if r.get("is_L1")), key=lambda r: r.get("volume_no", 0))
    cpn_lead_map = {}
    for rfq in l1_rfqs:
        cpn = str(rfq.get("cpn", ""))
        lead_time = str(rfq.get("lead_times") or "").strip()
        if lead_time in ("", "0"):
            continue
        cpn_lead_map.setdefault(cpn, lead_time)

    lead_time_counts = {}
    total_occurrences = 0
    for cpn, lead_time in cpn_lead_map.items():
        if cpn not in bom_cpns:
            continue
        lead_time_counts[lead_time] = lead_time_counts.get(lead_time, 0) + 1
        total_occurrences += 1

    summary = []
    for lt in sorted(lead_time_counts, key=_natural_key):
        count = lead_time_counts[lt]
        percentage = (count / total_occurrences) * 100 if total_occurrences > 0 else 0
        summary.append({
            "lead_time_weeks": lt,
            "count_of_part_number": count,
            "percentage": f"{percentage:.3f}%",
        })

    missing_count = sum(
        1 for cpn in bom_cpns
        if cpn not in rfq_cpns_all or cpn not in rfq_has_l1 or cpn not in rfq_has_valid_l1_lead
    )
    if missing_count > 0:
        summary.insert(0, {"lead_time_weeks": "", "count_of_part_number": missing_count, "percentage": ""})

    return summary


def lead_time_consolidated_sheet_rows(rows):
    """Port of LeadTimeConsolidatedExportExcelFormula::array(): header + data
    rows (count literal, percentage blank) + a Grand Total row with live
    SUM()/self-referential percentage formulas.
    """
    output = [["LT in weeks", "Count of Part Number", "In %"]]

    for row in rows:
        if "lead_time_weeks" not in row or "count_of_part_number" not in row:
            continue
        output.append([row["lead_time_weeks"], int(row["count_of_part_number"]), None])

    output.append(["Grand Total", None, None])

    grand_total_row_index = len(output)  # == the Grand Total row's own Excel row number

    sum_formula = f"=SUM(B2:B{grand_total_row_index - 1})" if grand_total_row_index > 2 else "=0"
    output[grand_total_row_index - 1][1] = sum_formula

    if grand_total_row_index > 2:
        for i in range(1, grand_total_row_index - 1):
            excel_row = i + 1
            output[i][2] = f"=IF($B${grand_total_row_index}=0,0,B{excel_row}/$B${grand_total_row_index})"

    output[grand_total_row_index - 1][2] = (
        f"=IF($B${grand_total_row_index}=0,0,B{grand_total_row_index}/$B${grand_total_row_index})"
    )

    return output


def build_lead_time_consolidated_sheet(wb, rows):
    """Port of LeadTimeConsolidatedExportExcelFormula: writes and styles the
    'Lead Time Consolidated' sheet.

    wb: an openpyxl.Workbook to append the sheet to.
    rows: the list of dicts produced by lead_time_consolidated_rows().
    """
    ws = wb.create_sheet(title="Lead Time Consolidated")

    sheet_rows = lead_time_consolidated_sheet_rows(rows)
    for row in sheet_rows:
        ws.append(row)

    highest_row = len(sheet_rows)

    for col in range(1, 4):
        cell = ws.cell(row=1, column=col)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = _HEADER_ALIGN

    for r in range(2, highest_row + 1):
        cell_value = ws.cell(row=r, column=1).value
        is_grand_total = isinstance(cell_value, str) and cell_value.strip().lower() == "grand total"
        for col in range(1, 4):
            cell = ws.cell(row=r, column=col)
            cell.fill = _TOTAL_FILL if is_grand_total else _DATA_FILL
            if is_grand_total:
                cell.font = _TOTAL_FONT
            cell.alignment = _DATA_ALIGN
        if is_grand_total:
            break

    for r in range(2, highest_row + 1):
        ws.cell(row=r, column=3).number_format = "0.00%"

    for col_idx in range(1, 4):
        max_len = max(len(str(row[col_idx - 1])) for row in sheet_rows if col_idx - 1 < len(row))
        ws.column_dimensions[get_column_letter(col_idx)].width = max_len + 4

    for r in range(1, highest_row + 1):
        for col in range(1, 4):
            ws.cell(row=r, column=col).border = _THIN_BORDER

    return ws


def _demo():
    import json
    from openpyxl import Workbook

    payload = {
        "bom_details_json_data": [{"CPN": f"CPN-100{i}"} for i in range(1, 9)],
        "rfqs": [
            {"cpn": "CPN-1001", "is_L1": True, "lead_times": "8", "volume_no": 1},
            {"cpn": "CPN-1002", "is_L1": True, "lead_times": "8", "volume_no": 1},
            {"cpn": "CPN-1003", "is_L1": True, "lead_times": "8", "volume_no": 1},
            {"cpn": "CPN-1004", "is_L1": True, "lead_times": "8", "volume_no": 1},
            {"cpn": "CPN-1005", "is_L1": True, "lead_times": "8", "volume_no": 1},
            {"cpn": "CPN-1006", "is_L1": True, "lead_times": "12", "volume_no": 1},
            {"cpn": "CPN-1007", "is_L1": True, "lead_times": "12", "volume_no": 1},
            {"cpn": "CPN-1008", "is_L1": True, "lead_times": "12", "volume_no": 1},
        ],
    }

    print("\n========== INPUT ==========")
    print(json.dumps(payload, indent=4))

    rows = lead_time_consolidated_rows(payload)

    print("\n========== OUTPUT ==========")
    print(json.dumps(rows, indent=4))

    assert rows[0] == {"lead_time_weeks": "8", "count_of_part_number": 5, "percentage": "62.500%"}
    assert rows[1] == {"lead_time_weeks": "12", "count_of_part_number": 3, "percentage": "37.500%"}
    print("lead_time_consolidated_rows() self-check passed")

    payload_missing = dict(payload)
    payload_missing["bom_details_json_data"] = payload["bom_details_json_data"] + [{"CPN": "CPN-1009"}]
    rows_missing = lead_time_consolidated_rows(payload_missing)
    assert rows_missing[0]["lead_time_weeks"] == "" and rows_missing[0]["count_of_part_number"] == 1
    print("lead_time_consolidated_rows() missing-count self-check passed")

    sheet_rows = lead_time_consolidated_sheet_rows(rows)
    assert sheet_rows[0] == ["LT in weeks", "Count of Part Number", "In %"]
    assert sheet_rows[-1][0] == "Grand Total"
    assert sheet_rows[-1][1] == "=SUM(B2:B3)"
    assert sheet_rows[-1][2] == "=IF($B$4=0,0,B4/$B$4)"
    assert sheet_rows[1][2] == "=IF($B$4=0,0,B2/$B$4)"
    print("lead_time_consolidated_sheet_rows() self-check passed")

    empty_sheet_rows = lead_time_consolidated_sheet_rows([])
    assert empty_sheet_rows[-1][1] == "=0"
    print("lead_time_consolidated_sheet_rows() empty-input self-check passed")

    wb = Workbook()
    if "Sheet" in wb.sheetnames:
        del wb["Sheet"]
    ws = build_lead_time_consolidated_sheet(wb, rows)
    assert ws.title == "Lead Time Consolidated"
    assert ws["A1"].fill.fgColor.rgb.endswith("2F5496")
    assert ws["A4"].value == "Grand Total" and ws["A4"].fill.fgColor.rgb.endswith("FFD966")
    print("build_lead_time_consolidated_sheet() self-check passed")

    wb.save("Lead_Time_Consolidated_Output.xlsx")
    print("\nExcel generated successfully.")
    print("File : Lead_Time_Consolidated_Output.xlsx")


if __name__ == "__main__":
    _demo()
