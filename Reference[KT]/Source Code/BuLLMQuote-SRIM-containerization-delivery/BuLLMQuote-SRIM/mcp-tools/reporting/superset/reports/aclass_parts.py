"""Python port of the A Class Parts report (Laravel PHP).

Two layers, mirroring the PHP pipeline:
  1. aclass_parts() — port of BlockthreeController::aclass_json(): computes
     the per-CPN ABC cost rollup from bom_details_json_data/bom_data/rfqs/
     suppliers, matching the input/output JSON documented in aclass_parts.md.
  2. build_aclass_parts_sheet() — port of app/Exports/PartsDetailsExportExcelFormula.php:
     writes an 'A CLASS PARTS' worksheet whose cells hold live Excel formulas
     referencing the '7.0 CBOM VL-1' sheet, rather than the static JSON values.

No DB access happens here — bom_details_json_data/bom_data/rfqs/suppliers are
supplied by the caller, and the DB write (`aclass_json` table upsert) in the
original PHP is out of scope, consistent with every other port in this project.
"""

from openpyxl.styles import Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from currency import convert_currency

HEADER_LABELS = [
    "Part Number", "Description", "Commodity", "Mfg Name", "Mfg Part Number", "Part Qty",
    "Ext Vol (Splits) #1", "Cost #1", "Ext Price (Splits) #1 (Conv.)", "X",
    "Ext Vol Cost (Splits) #1", "Supp Name", "Pkg Qty", "MOQ", "Lead Time",
    "ABC Classification", "MOQ turns", "Average MOQ turns in days", "Price control", "Remarks",
]


def _is_numeric(value):
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        try:
            float(value.strip())
            return True
        except ValueError:
            return False
    return False


def _coalesce(d, key, default):
    """Mirrors PHP's `$d->key ?? $default`: null/missing -> default, falsy-but-set values pass through."""
    if not d:
        return default
    value = d.get(key)
    return default if value is None else value


def aclass_parts(payload):
    """Port of BlockthreeController::aclass_json(): per-CPN ABC cost rollup.

    payload: {"bom_details_json_data": [...], "bom_data": [...], "rfqs": [...], "suppliers": [...]}
    returns: list of row dicts, one per unique Part Number (first occurrence wins).
    """
    scrub_items = payload.get("bom_details_json_data", [])
    bom_data = payload.get("bom_data", [])
    rfqs = payload.get("rfqs", [])
    suppliers = payload.get("suppliers", [])

    rfq_l1_by_cpn = {}
    rfq_any_by_cpn = {}
    for r in rfqs:
        cpn = r.get("cpn")
        if cpn is None:
            continue
        rfq_any_by_cpn.setdefault(cpn, r)
        if r.get("is_L1") is True:
            rfq_l1_by_cpn.setdefault(cpn, r)

    bom_by_cpn = {}
    for row in bom_data:
        cpn = row.get("CPN")
        if cpn is not None and cpn not in bom_by_cpn:
            bom_by_cpn[cpn] = row

    suppliers_by_id = {s.get("id"): s for s in suppliers}

    total_ext_price = 0.0
    for item in scrub_items:
        rfq_entry = rfq_l1_by_cpn.get(item.get("CPN"))
        if rfq_entry and _is_numeric(rfq_entry.get("vol_pricing")) and _is_numeric(rfq_entry.get("total_part_qty")):
            total_ext_price += float(rfq_entry["vol_pricing"]) * float(rfq_entry["total_part_qty"])

    rows_by_part_number = {}
    for item in scrub_items:
        cpn = item.get("CPN", "-")
        bom_row = bom_by_cpn.get(cpn)
        rfq_entry = rfq_l1_by_cpn.get(cpn)
        any_rfq_entry = rfq_any_by_cpn.get(cpn)

        description = _coalesce(bom_row, "Description", "-")
        commodity = _coalesce(bom_row, "Commodity", "-")
        mfg_name = _coalesce(any_rfq_entry, "manufacturer_name", "-")
        mpn = _coalesce(any_rfq_entry, "MPN", "-")
        part_qty = _coalesce(any_rfq_entry, "total_part_qty", 0)
        vol_qty = _coalesce(rfq_entry, "vol_qty", 0)
        vol_price = _coalesce(rfq_entry, "vol_pricing", 0)  # original, pre-currency-conversion

        ext_val = float(part_qty) * float(vol_price) if _is_numeric(part_qty) and _is_numeric(vol_price) else 0
        ext_price = f"$ {ext_val:,.2f}" if ext_val > 0 else "-"

        x = f"{(ext_val / total_ext_price) * 100:.2f}%" if ext_val > 0 and total_ext_price > 0 else "-"

        ext_vol_cost_val = float(vol_qty) * float(vol_price) if _is_numeric(vol_qty) and _is_numeric(vol_price) else 0
        ext_vol_cost = f"$ {ext_vol_cost_val:,.2f}" if ext_vol_cost_val > 0 else "-"

        # Currency conversion happens AFTER Ext Price/X/Ext Vol Cost are computed —
        # those three use the raw un-converted price; Cost/ABC/Avg MOQ turns below
        # use the converted price. This asymmetry is in the original PHP, preserved.
        # Target currency is the admin-configured default quote currency (Settings ->
        # Currencies), not hardcoded USD -- convert_currency() is a no-op when
        # currency already matches, so no guard is needed.
        if rfq_entry and rfq_entry.get("currency"):
            currency = rfq_entry["currency"]
            vol_price = convert_currency(float(vol_price), currency)

        cost_str = f"{float(vol_price):,.2f}" if _is_numeric(vol_price) else "-"
        cost_field = f"$ {cost_str}" if cost_str != "-" else "-"

        supplier_name = "-"
        supplier_id = rfq_entry.get("supplier_id") if rfq_entry else None
        if supplier_id:
            supplier_name = _coalesce(suppliers_by_id.get(supplier_id), "supplier_name", "-")

        vol_price_num = float(vol_price) if _is_numeric(vol_price) else 0.0

        moq = _coalesce(rfq_entry, "vol_moq", 1)
        part_qty_num = float(part_qty) if _is_numeric(part_qty) else 0.0
        moq_num = float(moq) if _is_numeric(moq) else 0.0
        moq_turns = part_qty_num / moq_num if moq_num > 0 and part_qty_num > 0 else 0.0
        avg_moq_turn_days = moq_turns * vol_price_num if moq_turns > 0 and vol_price_num > 0 else 0.0

        lead_times = rfq_entry.get("lead_times") if rfq_entry else None
        lead_time_str = f"{float(lead_times):,.2f}" if lead_times else "-"

        row = {
            "Part Number": cpn,
            "Description": description,
            "Commodity": commodity,
            "Mfg Name": mfg_name,
            "Mfg Part Number": mpn,
            "Part Qty": part_qty,
            "Ext Vol (Splits) #1": vol_qty,
            "Cost #1": cost_field,
            "Ext Price (Splits) #1 (Conv.)": ext_price,
            "X": x,
            "Ext Vol Cost (Splits) #1": ext_vol_cost,
            "Supp Name": supplier_name,
            "Pkg Qty": _coalesce(rfq_entry, "package_qty", "-"),
            "MOQ": _coalesce(rfq_entry, "vol_moq", "-"),
            "Lead Time": lead_time_str,
            # Static seed value only -- build_aclass_parts_sheet() always overwrites this
            # cell with a live formula pulling "ABC Classification" from the CBOM VL-1
            # sheet's own column (which is itself now a live Scrap Factor sheet lookup --
            # see cbom_vl.py), not from this dict. No classification logic lives here
            # anymore (previously a hardcoded, dead-on-arrival price-threshold check).
            "ABC Classification": "-",
            "MOQ turns": f"{moq_turns:,.2f}" if moq_turns > 0 else "-",
            "Average MOQ turns in days": f"{avg_moq_turn_days:,.2f}" if avg_moq_turn_days > 0 else "-",
            "Price control": _coalesce(rfq_entry, "price_control", "-"),
            "Remarks": "-",
        }
        rows_by_part_number.setdefault(cpn, row)

    return list(rows_by_part_number.values())


_CBOM_SHEET = "7.0 CBOM VL-1"
_START_ROW_REF = "$AL$1"
_END_ROW_REF = "$AK$1"
_YELLOW_FILL = PatternFill("solid", fgColor="FFD966")
_HEADER_FILL = PatternFill("solid", fgColor="2F5496")
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_DATA_FILL = PatternFill("solid", fgColor="F2F6FC")
_DATA_FONT = Font(color="000000")
_THIN_SIDE = Side(style="thin", color="000000")
_THIN_BORDER = Border(left=_THIN_SIDE, right=_THIN_SIDE, top=_THIN_SIDE, bottom=_THIN_SIDE)


def _bounded_range(column_letter):
    sheet = f"'{_CBOM_SHEET}'"
    return (
        f"INDEX({sheet}!${column_letter}:${column_letter}, {_START_ROW_REF})"
        f":INDEX({sheet}!${column_letter}:${column_letter}, {_END_ROW_REF})"
    )


def _match_expression(part_number_cell):
    return (
        f"MATCH(1, INDEX(({_bounded_range('C')} = {part_number_cell}) * "
        f"({_bounded_range('AH')} <> TRUE), 0), 0)"
    )


def _index_formula(column_letter, match_expression, coerce_text=False):
    """Wrapped in IFERROR(..., "-") -- when match_expression's MATCH() can't find the part
    number in the CBOM VL sheet (the phantom-assembly-row case this report now filters out
    upstream, plus any other unmatched-part edge case), a bare INDEX(range, #N/A) had
    nothing to catch it and the raw #N/A leaked straight into the exported cell.
    """
    inner = f"INDEX({_bounded_range(column_letter)}, {match_expression})"
    if coerce_text:
        inner = inner + '&""'
    return f'=IFERROR({inner},"-")'


def _sumifs_formula(value_column_letter, part_number_cell):
    return (
        f"=SUMIFS({_bounded_range(value_column_letter)}, {_bounded_range('C')}, {part_number_cell}, "
        f'{_bounded_range("AH")}, "<>TRUE")'
    )


def build_aclass_parts_sheet(wb, rows, cbom_bounds):
    """Port of PartsDetailsExportExcelFormula: live-formula 'A CLASS PARTS' sheet.

    wb: an openpyxl.Workbook to append the sheet to.
    rows: the list of dicts produced by aclass_parts().
    cbom_bounds: (first_data_row, last_data_row) for '7.0 CBOM VL-1', computed
        once in Python via cbom_vl.cbom_vl_bounds() -- the exact same values the
        AL1/AK1 cells below used to compute at Excel runtime via
        MATCH("Part Number", $C:$C, 0)+1 / LOOKUP(2, 1/($C:$C<>""), ROW($C:$C)),
        both full-column scans. Required (no default): a missing/wrong value here
        should raise loudly rather than risk silently under-bounding every formula
        on this sheet (they all key off _bounded_range(), itself keyed off AL1/AK1).

    Row 1 is a grand-total row, row 2 is the header label row, data starts
    at row 3. Nearly every column is overwritten by a formula referencing
    the '7.0 CBOM VL-1' sheet (Part Number match, gated on that sheet's AH
    "excluded" flag), bounded by hidden AK1/AL1 helper cells — only Part
    Number and Remarks stay as static passthrough values from the JSON.

    Note: the 'X' column's formula is a plain 0-1 fraction (per an explicit
    business-rule correction -- it previously multiplied by 100 as well,
    which double-counted against Excel's own '0.00%' number format on this
    column, e.g. displaying 96.77 as "9677.00%"). Summing this column down
    the sheet now correctly totals to 1 (100%).
    """
    ws = wb.create_sheet(title="A CLASS PARTS")

    column_letter = {label: get_column_letter(i + 1) for i, label in enumerate(HEADER_LABELS)}
    last_col = len(HEADER_LABELS)

    data_row_count = len(rows)
    data_start_row = 3
    data_end_row = data_start_row + data_row_count - 1 if data_row_count > 0 else data_start_row

    grand_total_row = ["" for _ in HEADER_LABELS]
    if data_row_count > 0:
        ext_price_letter = column_letter["Ext Price (Splits) #1 (Conv.)"]
        ext_vol_cost_letter = column_letter["Ext Vol Cost (Splits) #1"]
        avg_moq_letter = column_letter["Average MOQ turns in days"]
        grand_total_row[8] = (
            f'=" $ "&TEXT(SUM(${ext_price_letter}${data_start_row}:${ext_price_letter}${data_end_row}),"0.00")'
        )
        grand_total_row[10] = (
            f'=" $ "&TEXT(SUM(${ext_vol_cost_letter}${data_start_row}:${ext_vol_cost_letter}${data_end_row}),"0.00")'
        )
        # Average MOQ turns in days (R1): sum of every row's own Average MOQ turns in
        # days, divided by the sheet's total Ext Vol Cost (K1, "Ext Vol Cost (Splits)
        # #1") -- per explicit business-rule correction, NOT the Ext Price total (I1)
        # used previously. Neither I1 nor K1 themselves can be referenced directly --
        # both hold a formatted text label ("$ 1234.56"), not a raw number -- so this
        # references the same SUM($K...) expression K1's own formula computes.
        grand_total_row[17] = (
            f'=ROUND(SUM(${avg_moq_letter}${data_start_row}:${avg_moq_letter}${data_end_row})'
            f'/SUM(${ext_vol_cost_letter}${data_start_row}:${ext_vol_cost_letter}${data_end_row}),6)'
        )
    else:
        grand_total_row[8] = "$ 0.00"
        grand_total_row[10] = "$ 0.00"
        grand_total_row[17] = "0.000000"

    ws.append(grand_total_row)
    ws.append(list(HEADER_LABELS))

    for row_index, item in enumerate(rows):
        excel_row = data_start_row + row_index
        part_number_cell = f"{column_letter['Part Number']}{excel_row}"
        part_qty_cell = f"{column_letter['Part Qty']}{excel_row}"
        ext_vol_cell = f"{column_letter['Ext Vol (Splits) #1']}{excel_row}"
        cost_cell = f"{column_letter['Cost #1']}{excel_row}"
        ext_price_cell = f"{column_letter['Ext Price (Splits) #1 (Conv.)']}{excel_row}"
        ext_vol_cost_cell = f"{column_letter['Ext Vol Cost (Splits) #1']}{excel_row}"
        moq_cell = f"{column_letter['MOQ']}{excel_row}"
        moq_turns_cell = f"{column_letter['MOQ turns']}{excel_row}"
        match_expr = _match_expression(part_number_cell)
        ext_price_letter = column_letter["Ext Price (Splits) #1 (Conv.)"]

        out_row = []
        for key in HEADER_LABELS:
            value = item.get(key, "-")
            if key == "Description":
                value = _index_formula("D", match_expr, coerce_text=True)
            elif key == "Commodity":
                value = _index_formula("E", match_expr, coerce_text=True)
            elif key == "Mfg Name":
                value = _index_formula("F", match_expr, coerce_text=True)
            elif key == "Mfg Part Number":
                value = _index_formula("G", match_expr, coerce_text=True)
            elif key == "Part Qty":
                value = _sumifs_formula("AW", part_number_cell)
            elif key == "Ext Vol (Splits) #1":
                value = _sumifs_formula("J", part_number_cell)
            elif key == "Cost #1":
                cost_flag = f"INDEX({_bounded_range('AF')},{match_expr})"
                cost_value = f"INDEX({_bounded_range('K')},{match_expr})"
                flag_condition = f'UPPER({cost_flag}&"")="TRUE"'
                value = f"=IFERROR(IF({flag_condition},{cost_value},0),0)"
            elif key == "Ext Price (Splits) #1 (Conv.)":
                value = f"=IFERROR({part_qty_cell}*{cost_cell},0)"
            elif key == "X":
                # Per explicit business-rule correction: no *100 factor -- this column
                # is a plain fraction (0-1), not a pre-multiplied percentage, so summing
                # it down the column gives exactly 1 (displayed as "100%" under this
                # column's own "0.00%" number format). The *100 previously here doubled
                # up with that same percentage format, e.g. displaying 96.77 as
                # "9677.00%" -- a known quirk explicitly called out (and reproduced
                # as-is) in this module's own docstring before this fix.
                value = (
                    f"=IFERROR({ext_price_cell}/SUM(${ext_price_letter}${data_start_row}"
                    f":${ext_price_letter}${data_end_row}),0)"
                )
            elif key == "Ext Vol Cost (Splits) #1":
                value = f"=IFERROR({cost_cell}*{ext_vol_cell},0)"
            elif key == "Supp Name":
                value = _index_formula("P", match_expr, coerce_text=True)
            elif key == "Pkg Qty":
                value = _index_formula("Q", match_expr)
            elif key == "MOQ":
                value = _index_formula("R", match_expr)
            elif key == "Lead Time":
                value = _index_formula("S", match_expr)
            elif key == "ABC Classification":
                value = _index_formula("AJ", match_expr)
            elif key == "MOQ turns":
                value = f'=IFERROR({ext_vol_cell}/{moq_cell},"-")'
            elif key == "Average MOQ turns in days":
                value = f'=IFERROR({ext_vol_cost_cell}*{moq_turns_cell},"-")'
            elif key == "Price control":
                value = _index_formula("W", match_expr, coerce_text=True)
            out_row.append(value)
        ws.append(out_row)

    total_rows = 2 + data_row_count

    ws["I1"].fill = _YELLOW_FILL
    ws["K1"].fill = _YELLOW_FILL
    ws["R1"].fill = _YELLOW_FILL

    for col in range(1, last_col + 1):
        cell = ws.cell(row=2, column=col)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT

    for row in range(3, total_rows + 1):
        for col in range(1, last_col + 1):
            cell = ws.cell(row=row, column=col)
            cell.fill = _DATA_FILL
            cell.font = _DATA_FONT

    if total_rows >= 3:
        for label in ("Cost #1", "Ext Price (Splits) #1 (Conv.)", "Ext Vol Cost (Splits) #1"):
            letter = column_letter[label]
            for row in range(3, total_rows + 1):
                ws[f"{letter}{row}"].number_format = '"$"#,##0.0000'  # exactly 4 decimal places
        x_letter = column_letter["X"]
        for row in range(3, total_rows + 1):
            ws[f"{x_letter}{row}"].number_format = "0.00%"

    for row in range(1, total_rows + 1):
        for col in range(1, last_col + 1):
            ws.cell(row=row, column=col).border = _THIN_BORDER

    first_data_row, last_data_row = cbom_bounds
    ws["AL1"] = first_data_row
    ws["AK1"] = last_data_row
    ws.column_dimensions["AK"].hidden = True
    ws.column_dimensions["AL"].hidden = True

    return ws


def _demo():
    import json
    from openpyxl import Workbook

    payload = {
        "bom_upload_id": 123,
        "bom_details_json_data": [
            {"CPN": "CPN-2001", "FG": "ASSY-01"},
            {"CPN": "CPN-2002", "FG": "ASSY-01"}
        ],
        "bom_data": [
            {
                "CPN": "CPN-2001",
                "Description": "Resistor 10k",
                "Commodity": "Passive"
            },
            {
                "CPN": "CPN-2002",
                "Description": "Capacitor 1uF",
                "Commodity": "Passive"
            }
        ],
        "rfqs": [
            {
                "cpn": "CPN-2001",
                "is_L1": True,
                "vol_pricing": 1.5,
                "total_part_qty": 1000,
                "vol_qty": 1000,
                "manufacturer_name": "ACME",
                "MPN": "MPN-2001",
                "currency": "USD",
                "supplier_id": 7,
                "package_qty": 100,
                "vol_moq": 500,
                "lead_times": 12,
                "price_control": "Centum"
            },
            {
                "cpn": "CPN-2002",
                "is_L1": True,
                "vol_pricing": 0.10,
                "total_part_qty": 500,
                "vol_qty": 500,
                "manufacturer_name": "Vendor-X",
                "MPN": "MPN-2002",
                "currency": "USD",
                "supplier_id": 8,
                "package_qty": 50,
                "vol_moq": 200,
                "lead_times": 8,
                "price_control": "CNP"
            }
        ],
        "suppliers": [
            {
                "id": 7,
                "supplier_name": "Acme Corp"
            },
            {
                "id": 8,
                "supplier_name": "Vendor X Inc"
            }
        ]
    }

    print("\n========== INPUT ==========")
    print(json.dumps(payload, indent=4))

    result = aclass_parts(payload)

    print("\n========== OUTPUT ==========")
    print(json.dumps(result, indent=4))

    wb = Workbook()

    if "Sheet" in wb.sheetnames:
        del wb["Sheet"]

    build_aclass_parts_sheet(wb, result, cbom_bounds=(18, 500))

    wb.save("A_Class_Parts_Output.xlsx")

    print("\nExcel generated successfully.")
    print("File : A_Class_Parts_Output.xlsx")


if __name__ == "__main__":
    _demo()
