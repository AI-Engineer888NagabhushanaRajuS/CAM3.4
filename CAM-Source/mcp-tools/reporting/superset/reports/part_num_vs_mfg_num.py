"""Python port of the Part Num Vs Mfg Num report (Laravel PHP).

Two layers, mirroring the PHP pipeline:
  1. part_num_vs_mfg_num() — port of BlockthreeController::cpnvsmpn_json():
     computes the CPN -> MPN / in-scrub-BOM rows from bom_details_json_data/
     rfqs, matching the input/output JSON documented in
     part-num-vs-mfg-num-report.md.
  2. build_part_num_vs_mfg_num_sheet() — port of app/Exports/BomDetailsExport.php:
     writes a 'Part Num Vs Mfg Num' worksheet from those rows.

No DB access happens here — bom_details_json_data/rfqs are supplied by the
caller, and the DB write (`part_number_vs_mpn` table upsert) in the original
PHP is out of scope, consistent with every other port in this project.
"""

from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HEADER_LABELS = ["Part Number", "MPN", "In Scrub BOM"]

_HEADER_FILL = PatternFill("solid", fgColor="2F5496")
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_HEADER_ALIGN = Alignment(horizontal="center", vertical="center")
_DATA_FILL = PatternFill("solid", fgColor="F2F6FC")
_FALSE_FILL = PatternFill("solid", fgColor="FF0000")
_FALSE_FONT = Font(color="FFFFFF")
_THIN_SIDE = Side(style="thin", color="000000")
_THIN_BORDER = Border(left=_THIN_SIDE, right=_THIN_SIDE, top=_THIN_SIDE, bottom=_THIN_SIDE)


def part_num_vs_mfg_num(payload):
    """Port of BlockthreeController::cpnvsmpn_json(): CPN -> MPN / in-scrub-BOM rows.

    payload: {"bom_details_json_data": [{"CPN": ..., "MPN": ...}, ...],
              "rfqs": [{"cpn": ..., "is_L1": bool, "MPN": ...}, ...]}
    returns: list of {"part_number", "mpn", "in_scrub_bom"} dicts, deduped on
        part_number+mpn, preserving first-occurrence order.
    """
    scrub_items = payload.get("bom_details_json_data", [])
    rfqs = payload.get("rfqs", [])

    # Step 1: always load all CPNs from Scrub BOM (with empty fields).
    json_cpns = [item.get("CPN") for item in scrub_items]
    rows = [{"part_number": cpn, "mpn": "", "in_scrub_bom": ""} for cpn in json_cpns]

    # Step 2: if RFQ has L1 data, update corresponding fields.
    if rfqs:
        rfqs_cpns = []
        seen_cpns = set()
        for r in rfqs:
            if r.get("is_L1") is not True:
                continue
            cpn = r.get("cpn")
            if cpn is None or cpn in seen_cpns:
                continue
            seen_cpns.add(cpn)
            rfqs_cpns.append(cpn)

        if scrub_items:
            json_map = {}
            for item in scrub_items:
                cpn = item.get("CPN")
                if cpn is not None and cpn not in json_map:
                    json_map[cpn] = item
            json_mpn_keys = {item.get("MPN") for item in scrub_items}

            for row in rows:
                if row["part_number"] not in rfqs_cpns:
                    continue
                entry = json_map.get(row["part_number"])
                row["mpn"] = (entry.get("MPN") if entry else None) or "-"
                mpn = entry.get("MPN") if entry else None
                row["in_scrub_bom"] = "true" if mpn in json_mpn_keys else "false"

    # Step 3: ensure uniqueness on part_number+mpn, preserving first occurrence.
    deduped = []
    seen_keys = set()
    for row in rows:
        key = f"{row['part_number']}|{row['mpn']}"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(row)

    return deduped


def build_part_num_vs_mfg_num_sheet(wb, rows):
    """Port of BomDetailsExport: styles the Part Num Vs Mfg Num rows into a sheet.

    wb: an openpyxl.Workbook to append the sheet to.
    rows: the list of dicts produced by part_num_vs_mfg_num().
    """
    ws = wb.create_sheet(title="Part Num Vs Mfg Num")

    ws.append(list(HEADER_LABELS))
    for row in rows:
        ws.append([row["part_number"], row["mpn"], row["in_scrub_bom"]])

    last_col = len(HEADER_LABELS)
    last_row = 1 + len(rows)

    for col in range(1, last_col + 1):
        cell = ws.cell(row=1, column=col)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = _HEADER_ALIGN
        cell.border = _THIN_BORDER

    for row_idx in range(2, last_row + 1):
        scrub_val = str(ws.cell(row=row_idx, column=3).value or "").strip().upper()
        is_false = scrub_val == "FALSE"
        for col in range(1, last_col + 1):
            cell = ws.cell(row=row_idx, column=col)
            cell.border = _THIN_BORDER
            if is_false:
                cell.fill = _FALSE_FILL
                cell.font = _FALSE_FONT
            else:
                cell.fill = _DATA_FILL

    # ponytail: no native auto-size in openpyxl; approximate from content length
    for col_idx, label in enumerate(HEADER_LABELS, start=1):
        max_len = max([len(label)] + [len(str(ws.cell(row=r, column=col_idx).value or "")) for r in range(2, last_row + 1)])
        ws.column_dimensions[get_column_letter(col_idx)].width = max_len + 4

    return ws


def _demo():
    import json
    from openpyxl import Workbook

    payload = {
        "bom_upload_id": 123,
        "bom_details_json_data": [
            {"CPN": "CPN-1001", "MPN": "MPN-ABC-123"},
            {"CPN": "CPN-1002", "MPN": "MPN-DEF-456"},
            {"CPN": "CPN-1003", "MPN": "MPN-XYZ-789"},
            {"CPN": "CPN-1004", "MPN": "MPN-GHI-000"},
        ],
        "rfqs": [
            {"cpn": "CPN-1001", "is_L1": True, "MPN": "MPN-ABC-123"},
            {"cpn": "CPN-1003", "is_L1": True, "MPN": "MPN-XYZ-789"},
            {"cpn": "CPN-1004", "is_L1": True, "MPN": "MPN-OTHER-999"},
        ],
    }

    print("\n========== INPUT ==========")
    print(json.dumps(payload, indent=4))

    result = part_num_vs_mfg_num(payload)

    print("\n========== OUTPUT ==========")
    print(json.dumps(result, indent=4))

    wb = Workbook()
    if "Sheet" in wb.sheetnames:
        del wb["Sheet"]

    build_part_num_vs_mfg_num_sheet(wb, result)

    wb.save("Part_Num_Vs_Mfg_Num_Output.xlsx")

    print("\nExcel generated successfully.")
    print("File : Part_Num_Vs_Mfg_Num_Output.xlsx")


if __name__ == "__main__":
    _demo()
