"""Python port of the Batchwise Cashflow report (Laravel PHP).

Two layers, mirroring the PHP pipeline:
  1. batchwise_cashflow_rows() — port of BatchwiseCashflowExportExcelFormula::array():
     builds the literal heading/header/label-row layout (proto section first,
     then volume sections sorted ascending), matching the input/output JSON
     documented in batchwise-cashflow-report.md.
  2. build_batchwise_cashflow_sheet() — port of the same class's styles():
     writes those rows, then overwrites every data-row cell (B onward) with
     a live SUMIF formula referencing 'Ex Inv VL-{volume}' / 'Ex Inv VL-proto'
     (matched by Supplier Type against that sheet's own AE column) and every
     Grand Total cell with a SUM() over its section's data rows — same
     live-formula pattern as Ex Inv VL, PCB NRE & FAI Charge, Mech & EM NRE,
     and Revision History.

# ponytail: only the supplier-type dict KEYS in the payload are ever read —
# proto_qty/final_buy_value/buy_after_value/batch_qty/cpn_count (and any
# leftover 'cpns' sub-map under 'proto', which the shipped PHP never cleans
# up — see the .md) are computed by the real pipeline but never consumed by
# this export; every visible number comes from the injected SUMIF formulas
# instead. No DB access happens here, consistent with every other port in
# this project; include_proto replaces the PHP's BomDetail.proto DB lookup
# with an explicit caller-supplied flag.
"""

from openpyxl.styles import Border, Font, PatternFill, Side

_HEADING_FILL = PatternFill("solid", fgColor="2F5496")
_HEADING_FONT = Font(bold=True, color="FFFFFF")
_HEADER_FILL = PatternFill("solid", fgColor="D9E2F3")
_HEADER_FONT = Font(bold=True)
_TOTAL_FILL = PatternFill("solid", fgColor="FFD966")
_TOTAL_FONT = Font(bold=True)
_DATA_FILL = PatternFill("solid", fgColor="F2F6FC")
_THIN_SIDE = Side(style="thin", color="AAAAAA")
_THIN_BORDER = Border(left=_THIN_SIDE, right=_THIN_SIDE, top=_THIN_SIDE, bottom=_THIN_SIDE)
_CURRENCY_FORMAT = '"$"#,##0.0000'  # exactly 4 decimal places on every monetary column


def _sorted_volumes(data):
    return sorted(data, key=lambda k: int(k) if str(k).isdigit() else float("inf"))


def batchwise_cashflow_rows(payload, include_proto=True):
    """Port of BatchwiseCashflowExportExcelFormula::array(): the literal
    heading/header/label-row layout, before formula injection.

    payload: {"proto": {supplierType: {...}}, "<volume>": {supplierType: {...}}, ...}
        — the {...} values are never read (see module docstring); only the
        supplier-type keys and section keys matter.
    include_proto: pass False to drop the 'proto' section entirely (stands
        in for resolveIncludeProto()'s BomDetail.proto DB check).
    returns: list of rows (heading/header/label/Grand-Total/blank), matching
        array()'s pre-formula-injection output.
    """
    data = dict(payload)
    if not include_proto:
        data.pop("proto", None)

    rows = []

    if "proto" in data:
        rows.append(["Payment term details for proto"])
        rows.append(["Supplier Type", "Sum of Final buy value", "Average payment terms for Final quantity"])
        for supplier_type in data["proto"]:
            rows.append([supplier_type, None, None])
        rows.append(["Grand Total", None, None])
        rows.append([None])
        del data["proto"]

    for volume in _sorted_volumes(data):
        suppliers = data[volume]
        rows.append([f"Payment term details for VL-{volume}"])
        rows.append([
            "Supplier Type", f"Sum of Buy value after -B{volume}", "Sum of Final buy value",
            f"Average payment terms for B{volume}", "Average payment terms for Final quantity",
        ])
        for supplier_type in suppliers:
            rows.append([supplier_type, None, None, None, None])
        rows.append(["Grand Total", None, None, None, None])
        rows.append([None])

    return rows


def build_batchwise_cashflow_sheet(wb, payload, ex_inv_row_counts, include_proto=True):
    """Port of BatchwiseCashflowExportExcelFormula: writes and styles the
    'Batchwise Cashflow' sheet, injecting live SUMIF/SUM formulas per row.

    wb: an openpyxl.Workbook to append the sheet to.
    payload: the same dict passed to batchwise_cashflow_rows().
    ex_inv_row_counts: {"Ex Inv VL-{v}"/"Ex Inv VL-proto": last_row} for every Ex Inv
        VL sheet this workbook will contain -- computed early via
        len(ex_inv_vl.ex_inv_vl_rows(...)) (before those sheets are actually built
        later in exporter.py) so this sheet's cross-references to them can be bounded
        instead of scanning full columns. Required (no default): a missing entry
        should raise loudly rather than risk silently under-bounding a formula.
    include_proto: see batchwise_cashflow_rows().
    """
    data = dict(payload)
    if not include_proto:
        data.pop("proto", None)

    ws = wb.create_sheet(title="Batchwise Cashflow")
    row_num = 0

    def write_row(cells):
        nonlocal row_num
        row_num += 1
        for col, value in enumerate(cells, start=1):
            ws.cell(row=row_num, column=col, value=value)
        return row_num

    def style_range(row, fill, font=None):
        for col in range(1, 6):  # PHP always styles A:E, even for the 3-column proto section
            cell = ws.cell(row=row, column=col)
            cell.fill = fill
            cell.border = _THIN_BORDER
            if font is not None:
                cell.font = font

    def write_section(heading, header, suppliers, formula_builder):
        heading_row = write_row([heading])
        style_range(heading_row, _HEADING_FILL, _HEADING_FONT)

        header_row = write_row(header)
        style_range(header_row, _HEADER_FILL, _HEADER_FONT)

        data_start = header_row + 1
        for supplier_type in suppliers:
            r = write_row([supplier_type] + [None] * (len(header) - 1))
            style_range(r, _DATA_FILL)
            for col, formula in formula_builder(supplier_type, r):
                ws.cell(row=r, column=col, value=formula)
                ws.cell(row=r, column=col).number_format = _CURRENCY_FORMAT
        data_end = row_num

        total_row = write_row(["Grand Total"] + [None] * (len(header) - 1))
        style_range(total_row, _TOTAL_FILL, _TOTAL_FONT)
        for col in range(2, len(header) + 1):
            letter = chr(ord("A") + col - 1)
            # An empty section has no data rows: SUM(B{h+1}:B{h}) would be a reversed range that
            # covers the total cell itself (circular in Excel). Total is 0 then.
            total_value = f"=SUM({letter}{data_start}:{letter}{data_end})" if suppliers else 0
            cell = ws.cell(row=total_row, column=col, value=total_value)
            cell.number_format = _CURRENCY_FORMAT

        write_row([None])  # blank spacer — no fill/border

    if "proto" in data:
        proto_last_row = ex_inv_row_counts["Ex Inv VL-proto"]

        def proto_formulas(supplier_type, r):
            yield 2, (
                f"=SUMIF('Ex Inv VL-proto'!$AE$5:$AE${proto_last_row},$A{r},"
                f"'Ex Inv VL-proto'!$AD$5:$AD${proto_last_row})"
            )
            yield 3, f'=$B{r}*IFERROR(_xlfn.NUMBERVALUE(LEFT($A{r},FIND(" ",$A{r}))),0)'

        write_section(
            "Payment term details for proto",
            ["Supplier Type", "Sum of Final buy value", "Average payment terms for Final quantity"],
            data["proto"], proto_formulas,
        )
        del data["proto"]

    for volume in _sorted_volumes(data):
        sheet_name = f"Ex Inv VL-{volume}"
        ex_inv_last_row = ex_inv_row_counts[sheet_name]

        def volume_formulas(supplier_type, r, sheet_name=sheet_name, ex_inv_last_row=ex_inv_last_row):
            yield 2, f"=SUMIF('{sheet_name}'!$AE$5:$AE${ex_inv_last_row},$A{r},'{sheet_name}'!$Z$5:$Z${ex_inv_last_row})"
            yield 3, (
                f"=SUMIF('{sheet_name}'!$AE$5:$AE${ex_inv_last_row},$A{r},"
                f"'{sheet_name}'!$AD$5:$AD${ex_inv_last_row})"
            )
            yield 4, f'=$B{r}*IFERROR(_xlfn.NUMBERVALUE(LEFT($A{r},FIND(" ",$A{r}))),0)'
            yield 5, f'=$C{r}*IFERROR(_xlfn.NUMBERVALUE(LEFT($A{r},FIND(" ",$A{r}))),0)'

        write_section(
            f"Payment term details for VL-{volume}",
            ["Supplier Type", f"Sum of Buy value after -B{volume}", "Sum of Final buy value",
             f"Average payment terms for B{volume}", "Average payment terms for Final quantity"],
            data[volume], volume_formulas,
        )

    ws.column_dimensions["A"].width = 20
    ws.column_dimensions["B"].width = 25
    ws.column_dimensions["C"].width = 25
    ws.column_dimensions["D"].width = 30
    ws.column_dimensions["E"].width = 35
    for r in range(1, row_num + 1):
        ws.row_dimensions[r].height = 20

    return ws


def _demo():
    import json
    from openpyxl import Workbook

    payload = {
        "proto": {
            "Standard": {"proto_qty": 500, "final_buy_value": 75000.00, "cpn_count": 12,
                         "cpns": {"CPN-1001": 30000.00, "CPN-1002": 45000.00}},
            "Advance": {"proto_qty": 200, "final_buy_value": 30000.00, "cpn_count": 5,
                        "cpns": {"CPN-1003": 30000.00}},
        },
        "1": {
            "Standard": {"buy_after_value": 90000.00, "final_buy_value": 155000.00, "batch_qty": 1000, "cpn_count": 15},
            "Advance": {"buy_after_value": 40000.00, "final_buy_value": 60000.00, "batch_qty": 400, "cpn_count": 6},
        },
    }

    print("\n========== INPUT ==========")
    print(json.dumps(payload, indent=4))

    rows = batchwise_cashflow_rows(payload)

    print("\n========== OUTPUT ==========")
    print(json.dumps(rows, indent=4))

    assert rows[0] == ["Payment term details for proto"]
    assert rows[1] == ["Supplier Type", "Sum of Final buy value", "Average payment terms for Final quantity"]
    assert rows[2] == ["Standard", None, None]
    assert rows[3] == ["Advance", None, None]
    assert rows[4] == ["Grand Total", None, None]
    assert rows[5] == [None]
    assert rows[6] == ["Payment term details for VL-1"]
    assert rows[7][:2] == ["Supplier Type", "Sum of Buy value after -B1"]
    assert rows[8] == ["Standard", None, None, None, None]
    assert rows[9] == ["Advance", None, None, None, None]
    assert rows[10] == ["Grand Total", None, None, None, None]
    assert rows[11] == [None]
    print("batchwise_cashflow_rows() self-check passed")

    no_proto_rows = batchwise_cashflow_rows(payload, include_proto=False)
    assert no_proto_rows[0] == ["Payment term details for VL-1"]
    print("batchwise_cashflow_rows() include_proto=False self-check passed")

    wb = Workbook()
    if "Sheet" in wb.sheetnames:
        del wb["Sheet"]
    ex_inv_row_counts = {"Ex Inv VL-proto": 300, "Ex Inv VL-1": 200}
    ws = build_batchwise_cashflow_sheet(wb, payload, ex_inv_row_counts)

    assert ws.title == "Batchwise Cashflow"
    assert ws["A3"].value == "Standard"
    assert ws["B3"].value == "=SUMIF('Ex Inv VL-proto'!$AE$5:$AE$300,$A3,'Ex Inv VL-proto'!$AD$5:$AD$300)"
    assert ws["C3"].value == '=$B3*IFERROR(_xlfn.NUMBERVALUE(LEFT($A3,FIND(" ",$A3))),0)'
    assert ws["B5"].value == "=SUM(B3:B4)"  # Grand Total for proto (2 suppliers -> rows 3-4)
    assert ws["A9"].value == "Standard"  # first VL-1 supplier row
    assert ws["B9"].value == "=SUMIF('Ex Inv VL-1'!$AE$5:$AE$200,$A9,'Ex Inv VL-1'!$Z$5:$Z$200)"
    assert ws["E9"].value == '=$C9*IFERROR(_xlfn.NUMBERVALUE(LEFT($A9,FIND(" ",$A9))),0)'
    assert ws["B11"].value == "=SUM(B9:B10)"  # Grand Total for VL-1 (2 suppliers -> rows 9-10)
    assert ws["A1"].fill.fgColor.rgb.endswith("2F5496")
    assert ws["A5"].fill.fgColor.rgb.endswith("FFD966")
    assert ws["D1"].fill.fgColor.rgb.endswith("2F5496")  # proto heading styled A:E even though only 3 cols used
    print("build_batchwise_cashflow_sheet() self-check passed")

    wb.save("Batchwise_Cashflow_Output.xlsx")
    print("\nExcel generated successfully.")
    print("File : Batchwise_Cashflow_Output.xlsx")


if __name__ == "__main__":
    _demo()
