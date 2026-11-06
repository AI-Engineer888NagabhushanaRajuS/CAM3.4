"""Python port of the Mech & EM NRE report (Laravel PHP).

Two layers, mirroring the PHP pipeline:
  1. mech_em_nre_rows() — port of BlockthreeController::nrecharge(): the
     per-CPN Mechanical/Electromechanical NRE-charge rollup, matching the
     input/output JSON documented in mech-em-nre-report.md. This is the exact
     shape persisted to nre_charge_data.json_desc and the only shape
     NreChargeExportExcelFormula::array() actually consumes correctly (see
     the "Cross-check notes" in the .md for two call sites that get this
     wrong by pre-formatting the data before handing it to that class).
  2. build_mech_em_nre_sheet() — port of app/Exports/NreChargeExportExcelFormula.php:
     writes a 'Mech & EM NRE' worksheet — grand-total row first, header row
     second, data rows third — whose Description/Commodity/Mfg Name/Mfg Part
     Number/NRE-Charge cells (columns B-F, data rows only) hold live Excel
     formulas referencing '7.0 CBOM VL-1', same live-formula pattern as
     PCB NRE & FAI Charge (pcb_nre_fai_charge_report.py).

# ponytail: reproduces two shipped quirks verbatim rather than fixing them
# (see mech-em-nre-report.md "Cross-check notes"):
#   - Column F is labeled "NRE Charge (Conv.)" but its formula sources CBOM
#     column T ("NRE Charge", raw) instead of column U ("NRE Charge (Conv.)")
#     — identical bug to the PCB NRE & FAI Charge report.
#   - The lookup always targets '7.0 CBOM VL-1' and a fixed row range
#     (27-282), never the dynamic per-volume AK1/AL1 bounds used elsewhere.

No DB access happens here — bom_details_json_data/rfqs are supplied by the
caller, and the DB write (`nre_charge_data` table upsert) in the original PHP
is out of scope, consistent with every other port in this project.
"""

from openpyxl.styles import Border, Font, PatternFill, Side

from currency import convert_currency

_HEADER = ["Part Number", "Description", "Commodity", "Mfg Name", "Mfg Part Number", "NRE Charge (Conv.)"]

_CBOM_SHEET = "7.0 CBOM VL-1"
_CBOM_ROW_START = 27
_CBOM_ROW_END = 282

# column on this sheet -> (source column on _CBOM_SHEET, coerce to text?)
_FORMULA_COLUMNS = {
    "B": ("D", True),
    "C": ("E", True),
    "D": ("F", True),
    "E": ("G", True),
    "F": ("T", False),
}

_HEADER_FILL = PatternFill("solid", fgColor="2F5496")
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_DATA_FILL = PatternFill("solid", fgColor="F2F6FC")
_TOTAL_FILL = PatternFill("solid", fgColor="FFD966")
_TOTAL_FONT = Font(bold=True)
_THIN_SIDE = Side(style="thin", color="000000")
_THIN_BORDER = Border(left=_THIN_SIDE, right=_THIN_SIDE, top=_THIN_SIDE, bottom=_THIN_SIDE)


def mech_em_nre_rows(payload):
    """Port of BlockthreeController::nrecharge(): the Mechanical/EM NRE charge rollup.

    payload: {"bom_details_json_data": [{"CPN":..., "Commodity":..., "MPN":...,
        "Description":..., "MFR":...}, ...],
        "rfqs": [{"cpn":..., "nre_charge":..., "currency":...}, ...]}
    returns: list of {"cpn", "description", "commodity", "mfg_name",
        "mfg_part_number", "nre_charge_usd"} dicts — one per costed
        MECHANICAL/ELECTROMECHANICAL CPN+MPN pair (first occurrence wins).
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

    rows = []
    seen_pairs = set()

    for cpn in cpns:
        entry = entry_by_cpn.get(cpn, {})
        commodity = str(entry.get("Commodity", "")).strip().upper()
        mpn = str(entry.get("MPN", "-")).strip()

        if commodity not in ("MECHANICAL", "ELECTROMECHANICAL"):
            continue

        pair_key = f"{cpn}::{mpn}"
        if pair_key in seen_pairs:
            continue

        rfq = rfq_by_cpn.get(cpn)
        if not rfq or not rfq.get("nre_charge"):
            continue

        currency = rfq.get("currency", "USD")
        nre_charge = convert_currency(float(rfq["nre_charge"]), currency)
        if nre_charge <= 0:
            continue

        seen_pairs.add(pair_key)

        rows.append({
            "cpn": cpn,
            "description": entry.get("Description", "-"),
            "commodity": commodity,
            "mfg_name": entry.get("MFR", "-"),
            "mfg_part_number": mpn,
            "nre_charge_usd": round(nre_charge, 2),
        })

    return rows


def mech_em_nre_sheet_rows(rows):
    """Port of NreChargeExportExcelFormula::array(): grand-total row first,
    header row second, formatted data rows third — before the formula
    overwrite applied by build_mech_em_nre_sheet().
    """
    total = sum(r.get("nre_charge_usd", 0) for r in rows)
    sheet_rows = [["", "", "", "", "", f"$ {total:,.2f}"], list(_HEADER)]
    for r in rows:
        sheet_rows.append([
            r.get("cpn", ""),
            r.get("description", ""),
            r.get("commodity", ""),
            r.get("mfg_name", ""),
            r.get("mfg_part_number", ""),
            f"$ {r.get('nre_charge_usd', 0):,.2f}",
        ])
    return sheet_rows


def _lookup_formula(cbom_col, part_cell, coerce_text):
    # IFERROR guards the MATCH-can't-find-the-part case (raw INDEX(range, #N/A) has
    # nothing to catch it otherwise and the #N/A leaks straight into the exported
    # cell) -- same fix already applied to this exact CBOM-lookup pattern in
    # aclass_parts.py. Falls back to "" (not the "-" aclass_parts.py uses) to match
    # this report's own blank convention from the outer IF(part_cell="","",...).
    match_expr = f"MATCH({part_cell}, '{_CBOM_SHEET}'!$C${_CBOM_ROW_START}:$C${_CBOM_ROW_END}, 0)"
    index_expr = f"INDEX('{_CBOM_SHEET}'!${cbom_col}${_CBOM_ROW_START}:${cbom_col}${_CBOM_ROW_END}, {match_expr})"
    value_expr = f'{index_expr}&""' if coerce_text else index_expr
    return f'=IF({part_cell}="","",IFERROR({value_expr},""))'


def build_mech_em_nre_sheet(wb, rows):
    """Port of NreChargeExportExcelFormula: writes and styles the 'Mech & EM NRE' sheet.

    wb: an openpyxl.Workbook to append the sheet to.
    rows: the list of dicts produced by mech_em_nre_rows().
    """
    ws = wb.create_sheet(title="Mech & EM NRE")

    sheet_rows = mech_em_nre_sheet_rows(rows)
    for row in sheet_rows:
        ws.append(row)

    total_rows = len(sheet_rows)  # matches PHP's $totalRows = count($this->data) + 2

    for r in range(1, total_rows + 1):
        for col in range(1, 7):
            ws.cell(row=r, column=col).border = _THIN_BORDER

    ws["F1"].fill = _TOTAL_FILL
    ws["F1"].font = _TOTAL_FONT

    for col in range(1, 7):
        cell = ws.cell(row=2, column=col)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT

    data_row_start, data_row_end = 3, total_rows
    if data_row_end >= data_row_start:
        for r in range(data_row_start, data_row_end + 1):
            for col in range(1, 7):
                ws.cell(row=r, column=col).fill = _DATA_FILL

        for r in range(data_row_start, data_row_end + 1):
            part_cell = f"$A{r}"
            for col_letter, (cbom_col, coerce_text) in _FORMULA_COLUMNS.items():
                ws[f"{col_letter}{r}"] = _lookup_formula(cbom_col, part_cell, coerce_text)

    return ws


def _demo():
    import json
    from openpyxl import Workbook

    payload = {
        "bom_details_json_data": [
            {"CPN": "CPN-3001", "Commodity": "MECHANICAL", "MPN": "MPN-BRK-001", "Description": "Bracket", "MFR": "ACME"},
            {"CPN": "CPN-3002", "Commodity": "ELECTROMECHANICAL", "MPN": "MPN-MH-002", "Description": "Motor Housing", "MFR": "Vendor-Y"},
            {"CPN": "CPN-3003", "Commodity": "Passive", "MPN": "MPN-RES-003", "Description": "Resistor", "MFR": "ACME"},
        ],
        "rfqs": [
            {"cpn": "CPN-3001", "nre_charge": 320.50, "currency": "USD"},
            {"cpn": "CPN-3002", "nre_charge": 175.00, "currency": "USD"},
            {"cpn": "CPN-3003", "nre_charge": 12.00, "currency": "USD"},
        ],
    }

    print("\n========== INPUT ==========")
    print(json.dumps(payload, indent=4))

    rows = mech_em_nre_rows(payload)

    print("\n========== OUTPUT ==========")
    print(json.dumps(rows, indent=4))

    assert len(rows) == 2  # CPN-3003 is Passive, filtered out
    assert rows[0]["cpn"] == "CPN-3001" and rows[0]["nre_charge_usd"] == 320.50
    assert rows[1]["cpn"] == "CPN-3002" and rows[1]["commodity"] == "ELECTROMECHANICAL"
    print("mech_em_nre_rows() self-check passed")

    sheet_rows = mech_em_nre_sheet_rows(rows)
    assert sheet_rows[0] == ["", "", "", "", "", "$ 495.50"]
    assert sheet_rows[1] == _HEADER
    assert sheet_rows[2][0] == "CPN-3001"
    print("mech_em_nre_sheet_rows() self-check passed")

    wb = Workbook()
    if "Sheet" in wb.sheetnames:
        del wb["Sheet"]
    ws = build_mech_em_nre_sheet(wb, rows)

    assert ws.title == "Mech & EM NRE"
    assert ws["F1"].value == "$ 495.50"
    assert ws["A2"].value == "Part Number"
    assert ws["B3"].value.startswith('=IF($A3="","",IFERROR(INDEX(\'7.0 CBOM VL-1\'!$D$27:$D$282')
    assert "$T$27:$T$282" in ws["F3"].value  # preserves the shipped "Conv." mislabel bug
    assert ws["F1"].fill.fgColor.rgb.endswith("FFD966")
    print("build_mech_em_nre_sheet() self-check passed")

    wb.save("Mech_EM_NRE_Output.xlsx")
    print("\nExcel generated successfully.")
    print("File : Mech_EM_NRE_Output.xlsx")


if __name__ == "__main__":
    _demo()
