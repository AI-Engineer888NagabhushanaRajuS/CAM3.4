"""Python port of the PCB NRE & FAI Charge report (Laravel PHP).

Two layers, mirroring the PHP pipeline:
  1. fai_charge_rows() — port of BlockthreeController::faiCharge(): the
     per-CPN PCB NRE-charge rollup (header row, one row per costed PCB
     CPN+MPN pair, a placeholder row if none qualify, a trailing total row),
     matching the input/output JSON documented in pcb-nre-fai-charge-report.md.
  2. build_fai_charge_sheet() — port of app/Exports/FaiChargeExportExcelFormula.php:
     writes a 'PCB NRE & FAI Charge' worksheet whose Description/Commodity/
     Mfg Name/Mfg Part Number/NRE-Charge cells (columns B-F, data rows only)
     hold live Excel formulas referencing '7.0 CBOM VL-1' — not the JSON
     values computed by fai_charge_rows() — same live-formula pattern as
     A Class Parts (aclass_parts.py) and CBOM VL (cbom_vl_report.py).

# ponytail: reproduces two shipped quirks verbatim rather than fixing them
# (see pcb-nre-fai-charge-report.md "Cross-check notes"):
#   - Column F reads the converted NRE charge (CBOM column U), matching its label.

No DB access happens here — bom_details_json_data/rfqs are supplied by the
caller, and the DB write (`fai_charge_summary` table upsert) in the original
PHP is out of scope, consistent with every other port in this project.
"""

from openpyxl.styles import Border, Font, PatternFill, Side
from openpyxl.utils import column_index_from_string, get_column_letter

from currency import convert_currency

_HEADER_KEYS = ["Part Number", "Description", "Commodity", "Mfg Name", "Mfg Part Number", "NRE Charge (Conv.)"]

_CBOM_SHEET = "7.0 CBOM VL-1"
_CBOM_ROW_START = 27
_CBOM_ROW_END = 282

# column on this sheet -> (source column on _CBOM_SHEET, coerce to text?)
_FORMULA_COLUMNS = {
    "B": ("D", True),
    "C": ("E", True),
    "D": ("F", True),
    "E": ("G", True),
    "F": ("U", False),
}

_HEADER_FILL = PatternFill("solid", fgColor="2F5496")
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_DATA_FILL = PatternFill("solid", fgColor="F2F6FC")
_TOTAL_FILL = PatternFill("solid", fgColor="FFD966")
_TOTAL_FONT = Font(bold=True)
_THIN_SIDE = Side(style="thin", color="000000")
_THIN_BORDER = Border(left=_THIN_SIDE, right=_THIN_SIDE, top=_THIN_SIDE, bottom=_THIN_SIDE)


def fai_charge_rows(payload):
    """Port of BlockthreeController::faiCharge(): the PCB NRE/FAI charge rollup.

    payload: {"bom_details_json_data": [{"CPN":..., "Commodity":..., "MPN":...,
        "Description":..., "MFR":...}, ...],
        "rfqs": [{"cpn":..., "nre_charge":..., "currency":...}, ...]}
    returns: list of row dicts — header row, one row per costed PCB CPN+MPN
        pair (first occurrence wins), a placeholder row if none qualify, and
        a trailing total row.
    """
    scrub_items = payload.get("bom_details_json_data", [])
    rfqs = payload.get("rfqs", [])

    rfq_by_cpn = {}
    for r in rfqs:
        cpn = r.get("cpn")
        if cpn is not None and cpn not in rfq_by_cpn:
            rfq_by_cpn[cpn] = r

    entry_by_cpn = {}
    cpns = []
    for item in scrub_items:
        cpn = item.get("CPN")
        cpns.append(cpn)
        if cpn is not None and cpn not in entry_by_cpn:
            entry_by_cpn[cpn] = item

    rows = [dict(zip(_HEADER_KEYS, _HEADER_KEYS))]

    seen_pairs = set()
    total = 0.0
    has_data = False

    for cpn in cpns:
        entry = entry_by_cpn.get(cpn, {})
        commodity = str(entry.get("Commodity", "-")).lower()
        mpn = str(entry.get("MPN", "-")).strip()

        if commodity != "pcb":
            continue

        key = f"{cpn}::{mpn}"
        if key in seen_pairs:
            continue

        rfq = rfq_by_cpn.get(cpn)
        if not rfq or not rfq.get("nre_charge"):
            continue

        currency = rfq.get("currency", "USD")
        nre_charge = convert_currency(float(rfq["nre_charge"]), currency)
        if nre_charge <= 0:
            continue

        total += nre_charge
        has_data = True
        seen_pairs.add(key)

        rows.append({
            "Part Number": cpn,
            "Description": entry.get("Description", "-"),
            "Commodity": entry.get("Commodity", "-"),
            "Mfg Name": entry.get("MFR", "-"),
            "Mfg Part Number": mpn,
            "NRE Charge (Conv.)": round(nre_charge, 2),
        })

    if not has_data:
        rows.append({
            "Part Number": "-", "Description": "-", "Commodity": "-",
            "Mfg Name": "-", "Mfg Part Number": "-", "NRE Charge (Conv.)": 0.00,
        })

    rows.append({
        "Part Number": "", "Description": "", "Commodity": "", "Mfg Name": "",
        "Mfg Part Number": "Total FAI Charge", "NRE Charge (Conv.)": f"$ {total:,.2f}",
    })

    return rows


def _lookup_formula(cbom_col, part_cell, coerce_text, first_row, last_row):
    # IFERROR guards the MATCH-can't-find-the-part case (raw INDEX(range, #N/A) has
    # nothing to catch it otherwise and the #N/A leaks straight into the exported
    # cell) -- same fix already applied to this exact CBOM-lookup pattern in
    # aclass_parts.py. Falls back to "" (not the "-" aclass_parts.py uses) to match
    # this report's own blank convention from the outer IF(part_cell="","",...).
    match_expr = f"MATCH({part_cell}, '{_CBOM_SHEET}'!$C${first_row}:$C${last_row}, 0)"
    index_expr = f"INDEX('{_CBOM_SHEET}'!${cbom_col}${first_row}:${cbom_col}${last_row}, {match_expr})"
    value_expr = f'{index_expr}&""' if coerce_text else index_expr
    return f'=IF({part_cell}="","",IFERROR({value_expr},""))'


def build_fai_charge_sheet(wb, rows, cbom_bounds=None):
    """Port of FaiChargeExportExcelFormula: writes and styles the 'PCB NRE & FAI Charge' sheet.

    wb: an openpyxl.Workbook to append the sheet to.
    rows: the list of dicts produced by fai_charge_rows() — header row, data
        rows, trailing total row.
    """
    first_row, last_row = cbom_bounds or (_CBOM_ROW_START, _CBOM_ROW_END)
    ws = wb.create_sheet(title="PCB NRE & FAI Charge")

    for row in rows:
        ws.append([row[k] for k in _HEADER_KEYS])

    row_count = len(rows)
    col_count = len(_HEADER_KEYS)

    for col in range(1, col_count + 1):
        cell = ws.cell(row=1, column=col)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT

    data_row_start, data_row_end = 2, row_count - 1

    if row_count > 2:
        for r in range(data_row_start, data_row_end + 1):
            for col in range(1, col_count + 1):
                ws.cell(row=r, column=col).fill = _DATA_FILL

        for r in range(data_row_start, data_row_end + 1):
            part_cell = f"$A{r}"
            for col_letter, (cbom_col, coerce_text) in _FORMULA_COLUMNS.items():
                if column_index_from_string(col_letter) > col_count:
                    continue
                ws[f"{col_letter}{r}"] = _lookup_formula(cbom_col, part_cell, coerce_text, first_row, last_row)

    for col_letter in ("E", "F"):
        cell = ws[f"{col_letter}{row_count}"]
        cell.fill = _TOTAL_FILL
        cell.font = _TOTAL_FONT
        cell.border = _THIN_BORDER

    for col_letter in ("A", "B", "C", "D"):
        cell = ws[f"{col_letter}{row_count}"]
        cell.fill = PatternFill(fill_type=None)
        cell.font = _TOTAL_FONT
        cell.border = Border()

    if row_count > 1:
        for r in range(1, row_count):  # A1 through lastCol(rowCount-1) — excludes the total row
            for col in range(1, col_count + 1):
                ws.cell(row=r, column=col).border = _THIN_BORDER

    return ws


def _demo():
    import json
    from openpyxl import Workbook

    payload = {
        "bom_details_json_data": [
            {"CPN": "CPN-2001", "Commodity": "PCB", "MPN": "MPN-PCB-001", "Description": "PCB 4-layer", "MFR": "ACME"},
            {"CPN": "CPN-2002", "Commodity": "Passive", "MPN": "MPN-RES-001", "Description": "Resistor", "MFR": "Vendor-Y"},
        ],
        "rfqs": [
            {"cpn": "CPN-2001", "nre_charge": 450.00, "currency": "USD"},
            {"cpn": "CPN-2002", "nre_charge": 10.00, "currency": "USD"},
        ],
    }

    print("\n========== INPUT ==========")
    print(json.dumps(payload, indent=4))

    rows = fai_charge_rows(payload)

    print("\n========== OUTPUT ==========")
    print(json.dumps(rows, indent=4))

    assert rows[0]["Part Number"] == "Part Number"
    assert len(rows) == 3  # header + 1 qualifying PCB row (CPN-2002 is Passive, filtered out) + total
    assert rows[1]["Part Number"] == "CPN-2001" and rows[1]["NRE Charge (Conv.)"] == 450.00
    assert rows[-1]["Mfg Part Number"] == "Total FAI Charge"
    assert rows[-1]["NRE Charge (Conv.)"] == "$ 450.00"
    print("fai_charge_rows() self-check passed")

    empty_rows = fai_charge_rows({"bom_details_json_data": [], "rfqs": []})
    assert empty_rows[1]["Part Number"] == "-" and empty_rows[1]["NRE Charge (Conv.)"] == 0.00
    assert empty_rows[-1]["NRE Charge (Conv.)"] == "$ 0.00"
    print("fai_charge_rows() no-data placeholder self-check passed")

    wb = Workbook()
    if "Sheet" in wb.sheetnames:
        del wb["Sheet"]
    ws = build_fai_charge_sheet(wb, rows)

    assert ws.title == "PCB NRE & FAI Charge"
    assert ws["A1"].value == "Part Number"
    assert ws["B2"].value.startswith('=IF($A2="","",IFERROR(INDEX(\'7.0 CBOM VL-1\'!$D$27:$D$282')
    assert "$U$27:$U$282" in ws["F2"].value  # reads the converted NRE charge (column U)
    assert ws[f"E{len(rows)}"].fill.fgColor.rgb.endswith("FFD966")
    print("build_fai_charge_sheet() self-check passed")

    wb.save("PCB_NRE_FAI_Charge_Output.xlsx")
    print("\nExcel generated successfully.")
    print("File : PCB_NRE_FAI_Charge_Output.xlsx")


if __name__ == "__main__":
    _demo()
