"""Python port of the Ex Inv VL report (Laravel PHP).

Two layers, mirroring the PHP pipeline:
  1. ex_inv_vl_rows() — port of ExcessInventoryVolumeSheetExcelFormula::array():
     builds the literal 2D row layout for one volume (or 'proto'). Unlike
     most ports in this project, nearly every cell besides Part Number and
     Excess In Stk IS an Excel formula string referencing the matching
     '7.0 CBOM VL-{volume}' sheet — that's this report's actual output
     contract (see ex-inv-vl-report.md), not a value to precompute, so the
     formulas are reproduced verbatim rather than skipped.
  2. build_ex_inv_vl_sheet() — port of the same class's registerEvents():
     sheet title, special cells (A1 label, A2/summary-row totals, merged
     V3:Z3 super-header), the previous-volume AH/AI delta formulas, the
     CBOM-bounds AK1/AL1 formulas, and static styling.

Both known bugs in the shipped PHP are reproduced as-is rather than fixed
(see ex-inv-vl-report.md "Cross-check notes"):
  - A1 reads "Excess Cost #<volume>" (the PHP hardcoded "#1" on every volume; corrected).
  - Volume 1's AH/AI delta formulas always reference a sheet named
    'Ex Inv VL-proto', even if the proto sheet was excluded from the
    workbook (BomDetail.proto <= 0) — a latent #REF! source.

# ponytail: PHP's colAHSource/colAISource ternaries (`$suffix == '1' ? 'O' :
# 'O'`) always resolve to the same value on both branches — reproduced here
# as the plain literals 'O'/'T', skipping the dead conditional.

No DB access happens here — the CPN/volumes payload is supplied by the caller.

v2 source schema notes:
  - `excess_in_stk` is confirmed sourced from `scrub_bom_items.inventory_stock`
    (previously undetermined) -- no code change needed here, this file only
    ever consumed the `matched.get("excess_in_stk", ...)` dict key; only the
    loader that builds `json_data` needs to populate it from that column.
  - "Ordering qty" (row 134, the `W{r}` formula) already implements the
    finalized business logic exactly:
    `=IF(V{r}=0,0,IFERROR(ROUNDUP(MAX(V{r},T{r})/S{r},0)*S{r},0))`
    where V=Partial quantity (Required Quantity), T=MOQ (Minimum Order
    Quantity), S=Pkg Qty (Order Multiple). No code change was needed -- this
    was a gap in an earlier summary doc's write-up, not in this file.
  - "New Supp" (the `AL` INDEX lookup a few lines below) is PENDING CLIENT
    CLARIFICATION: does it hold an alternate supplier name, or a boolean
    "supplier changed" flag? Left exactly as ported (an `INDEX` lookup against
    CBOM's own "New Supp" column) rather than guessed at -- see
    cbom-pending-client-clarifications.md.
"""

from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

_HEADER_FILL = PatternFill("solid", fgColor="2F5496")
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_YELLOW_FILL = PatternFill("solid", fgColor="FFD966")
_THIN_SIDE = Side(style="thin", color="000000")
_THIN_BORDER = Border(left=_THIN_SIDE, right=_THIN_SIDE, top=_THIN_SIDE, bottom=_THIN_SIDE)
_CURRENCY_FORMAT = '"$"#,##0.0000'  # exactly 4 decimal places on every monetary column


def _suffix(volume):
    return "P" if volume == "proto" else str(volume)


def _cbom_sheet_name(volume):
    return "7.0 CBOM Proto" if volume == "proto" else f"7.0 CBOM VL-{volume}"


def _sheet_title(volume):
    return "Ex Inv VL-proto" if volume == "proto" else f"Ex Inv VL-{volume}"


def _headers(suffix):
    headers = [
        "Part Number", "Description", "Commodity", "Mfg Name", "Mfg Part Number", "Part Qty",
        f"Ext Vol (Splits) #{suffix}", "Excess In Stk", "Excess after considering current demand", "Shortage Qty",
        "Scrap", "Scrap Factor", "Batch Qty", "Batch Scrap factor", f"Cost #{suffix}",
        f"Ext Vol Cost (Splits) #{suffix}", "Supp Name", "New Supp", "Pkg Qty", "MOQ", "Lead Time",
        f"Partial quantity -B{suffix}", f"Ordering qty -B{suffix}", f"Excess Qty #{suffix} -B{suffix}",
        f"Excess Cost #{suffix} -B{suffix}", f"Buy value after -B{suffix}", "Net Ordering qty",
        f"Net Excess Qty #{suffix}", f"Net Excess Cost #{suffix}", "Final buy value", "Supplier Type",
        "Remarks", "Pkg <= MOQ",
    ]
    if suffix != "P":
        if suffix == "1":
            headers += [f"Cost Proto - V{suffix}", f"MOQ Proto - V{suffix}"]
        else:
            prev = int(suffix) - 1
            headers += [f"Cost V{prev} - V{suffix}", f"MOQ V{prev} - V{suffix}"]
    return headers


def _get_numeric(val):
    return 0 if val in (None, "", "0", 0) else val


def _find_volume(volumes, volume):
    # Compare as strings: a volume may arrive as 1 or "1" (and "proto" as a label), and an
    # exact-type comparison silently found nothing.
    for v in volumes or []:
        if str(v.get("volume")) == str(volume):
            return v
    return None


def _bounded(cbom_sheet, col):
    return f"INDEX('{cbom_sheet}'!${col}:${col}, $AL$1):INDEX('{cbom_sheet}'!${col}:${col}, $AK$1)"


def _index_lookup(cbom_sheet, col, row, coerce_text=False):
    inner = f"INDEX({_bounded(cbom_sheet, col)}, AJ{row})"
    # IFERROR-wrapped: AJ{row} is a MATCH() result (see _match_helper_formula) that
    # is #N/A whenever this row's part number isn't found on the CBOM sheet, and
    # that #N/A would otherwise propagate through this INDEX -- and from there into
    # every arithmetic consumer of this cell (Scrap/Cost/Pkg Qty/MOQ/Lead Time/
    # Supplier Type, etc.) plus this cell's own on-sheet display. Numeric-looking
    # columns fall back to 0 (they feed further arithmetic); text/display columns
    # fall back to "" (blank stays blank, and "" is also the correct SUMIF-safe
    # fallback for the Supplier Type column consumed by batchwise_cashflow.py).
    fallback = '""' if coerce_text else "0"
    formula = f"=IFERROR({inner},{fallback})"
    return formula + ' & ""' if coerce_text else formula


def _sumifs_lookup(cbom_sheet, value_col, pn_cell):
    return (
        f"=SUMIFS({_bounded(cbom_sheet, value_col)}, {_bounded(cbom_sheet, 'C')}, {pn_cell}, "
        f'{_bounded(cbom_sheet, "AH")}, "<>TRUE")'
    )


def _match_helper_formula(cbom_sheet, pn_cell):
    # IFERROR-wrapped: MATCH returns #N/A whenever this row's part number has no
    # match on the CBOM sheet. Without this, every _index_lookup() on this row
    # would inherit that #N/A through its own IFERROR fallback path anyway, but
    # this cell (AJ, hidden helper column) would still display the raw #N/A
    # itself if the column is ever unhidden -- "" keeps it a clean blank.
    inner = (
        f"MATCH(1, INDEX(({_bounded(cbom_sheet, 'C')} = {pn_cell}) * "
        f'({_bounded(cbom_sheet, "AH")} <> TRUE), 0), 0)'
    )
    return f'=IFERROR({inner},"")'


def _data_row(cpn_entry, matched, current_row, cbom_sheet):
    r = current_row
    pn_cell = f"A{r}"

    return [
        cpn_entry.get("CPN", ""),
        _index_lookup(cbom_sheet, "D", r, coerce_text=True),
        _index_lookup(cbom_sheet, "E", r, coerce_text=True),
        _index_lookup(cbom_sheet, "F", r, coerce_text=True),
        _index_lookup(cbom_sheet, "G", r, coerce_text=True),
        _sumifs_lookup(cbom_sheet, "AW", pn_cell),
        _sumifs_lookup(cbom_sheet, "J", pn_cell),
        _get_numeric(matched.get("excess_in_stk", "0")),
        f"=MAX(H{r}-G{r},0)",
        f"=MAX(G{r}-H{r},0)",
        _index_lookup(cbom_sheet, "AK", r),
        f"=IF(INT(F{r})=F{r}, ROUNDUP(J{r}*(1+IF(K{r}=\"\",0,K{r})),0), J{r}*(1+IF(K{r}=\"\",0,K{r})))",
        _sumifs_lookup(cbom_sheet, "AG", pn_cell),
        f"=IF(INT(F{r})=F{r}, ROUNDUP(M{r}*(1+IF(K{r}=\"\",0,K{r})),0), M{r}*(1+IF(K{r}=\"\",0,K{r})))",
        _index_lookup(cbom_sheet, "K", r),
        f"=IFERROR(O{r}*G{r},0)",
        _index_lookup(cbom_sheet, "P", r, coerce_text=True),
        _index_lookup(cbom_sheet, "AL", r),
        _index_lookup(cbom_sheet, "Q", r),
        _index_lookup(cbom_sheet, "R", r),
        _index_lookup(cbom_sheet, "S", r),
        f'=IF(AND(T{r}<>"",T{r}>0), MAX(N{r}-H{r},0), 0)',
        f"=IF(V{r}=0,0,IFERROR(ROUNDUP(MAX(V{r},T{r})/S{r},0)*S{r},0))",
        f'=IF(AND(T{r}<>"",T{r}>0), H{r}+W{r}-N{r}, 0)',
        f"=IFERROR(X{r}*O{r},0)",
        f"=IFERROR(W{r}*O{r},0)",
        f"=IFERROR(IF(L{r}<=T{r},T{r},ROUNDUP(L{r}/S{r},0)*S{r}),0)",
        f"=MAX(AA{r}+I{r}-L{r},0)",
        f"=IFERROR(AB{r}*O{r},0)",
        f"=IFERROR(AA{r}*O{r},0)",
        _index_lookup(cbom_sheet, "AD", r, coerce_text=True),
        "",
        f"=S{r}<=T{r}",
        "",
        "",
        _match_helper_formula(cbom_sheet, pn_cell),
    ]


def ex_inv_vl_rows(json_data, volume):
    """Port of ExcessInventoryVolumeSheetExcelFormula::array(): the full sheet rows.

    json_data: [{"CPN": ..., "volumes": [{"volume": ..., "excess_in_stk": ...}, ...]}, ...]
    volume: int volume number, or the string 'proto'.
    returns: list of rows — 3 blank rows, a header row, then one data row per
        CPN that has a matching volume entry.
    """
    suffix = _suffix(volume)
    cbom_sheet = _cbom_sheet_name(volume)
    rows = [[""], [""], [""], _headers(suffix)]

    for cpn_entry in json_data:
        matched = _find_volume(cpn_entry.get("volumes"), volume)
        if matched is None:
            continue
        current_row = len(rows) + 1
        rows.append(_data_row(cpn_entry, matched, current_row, cbom_sheet))

    return rows


def build_ex_inv_vl_sheet(wb, json_data, volume, cbom_bounds, has_proto=True, expected_row_count=None,
                          previous_sheet_exists=True):
    """Port of ExcessInventoryVolumeSheetExcelFormula: writes and styles an 'Ex Inv VL-n' sheet.

    wb: an openpyxl.Workbook to append the sheet to.
    json_data: the same payload passed to ex_inv_vl_rows().
    volume: int volume number, or 'proto'.
    cbom_bounds: (first_data_row, last_data_row) for this volume's own
        '7.0 CBOM VL-{n}'/'7.0 CBOM Proto' sheet, computed once in Python via
        cbom_vl.cbom_vl_bounds() -- the exact same values the AK1/AL1 cells below
        used to compute at Excel runtime via LOOKUP(2, 1/($C:$C<>""), ROW($C:$C)) /
        MATCH("Part Number", $C:$C, 0)+1, both full-column scans. Required (no
        default): a missing/wrong value here should raise loudly rather than risk
        silently under-bounding every formula on this sheet (they all key off
        _bounded(), itself keyed off AK1/AL1).
    has_proto: whether an 'Ex Inv VL-proto' sheet actually exists (or will exist) in
        this workbook. Volume 1's AH/AI delta formulas below always want to reference
        the "previous volume" sheet, which for volume 1 is 'Ex Inv VL-proto' -- this
        used to be hardcoded regardless of whether that sheet was ever built (a latent
        #REF! source, harmless only because no proto sheet was ever built at all). Now
        that proto sheets sometimes exist and sometimes don't per-RFQ, this flag lets
        volume 1 skip those formulas entirely when there's truly no proto sheet to
        reference, rather than emit a formula that will #REF!.
    expected_row_count: optional -- the row count exporter.py computed early (via its
        own call to ex_inv_vl_rows()) and already threaded into other sheets' cross-
        references to this one (bom_matrix.py, revision_history.py, batchwise_cashflow.py).
        ex_inv_vl_rows() is a pure function of (json_data, volume), so calling it again
        here is guaranteed to reproduce the same result -- this assert exists purely as
        a guard rail against a future code change breaking that guarantee, which would
        otherwise silently under-bound every formula elsewhere in the workbook pointing
        at this sheet.
    """
    suffix = _suffix(volume)
    title = _sheet_title(volume)
    rows = ex_inv_vl_rows(json_data, volume)
    if expected_row_count is not None:
        assert len(rows) == expected_row_count, (
            f"{title}: expected {expected_row_count} rows (threaded into other sheets' "
            f"cross-references), but ex_inv_vl_rows() produced {len(rows)} -- would silently "
            f"under/over-bound every formula elsewhere in the workbook pointing at this sheet."
        )

    ws = wb.create_sheet(title=title)
    for row in rows:
        ws.append(row)

    last_col = len(rows[3])
    last_data_row = len(rows)
    data_start_row = 5

    ws.merge_cells("V3:Z3")
    ws["V3"] = "Excess After 1st batch"
    for col in range(22, 27):  # V..Z
        cell = ws.cell(row=3, column=col)
        cell.fill = _YELLOW_FILL
        cell.font = Font(bold=True, color="000000")
        cell.alignment = Alignment(horizontal="center")

    for col in range(1, last_col + 1):
        cell = ws.cell(row=4, column=col)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT

    ws["A1"] = f"Excess Cost #{_suffix(volume)}"
    ws["A1"].fill = _HEADER_FILL
    ws["A1"].font = _HEADER_FONT

    # No supplier rows: the range would run backwards (AC5:AC4) and include its own cell, so the total is 0.
    ws["A2"] = f"=SUM(AC{data_start_row}:AC{last_data_row})" if last_data_row >= data_start_row else 0
    ws["A2"].fill = _YELLOW_FILL
    ws["A2"].number_format = _CURRENCY_FORMAT

    for r in range(data_start_row, last_data_row + 1):
        ws.cell(row=r, column=11).number_format = "0%"  # column K

    # The delta columns reference the previous volume's sheet; skip them when that sheet is absent.
    if suffix != "P" and previous_sheet_exists and (suffix != "1" or has_proto):
        # Quirk preserved as-is for suffix != "1": that branch always pointed at
        # 'Ex Inv VL-proto' regardless of whether it existed. For suffix == "1" this
        # is now gated on has_proto (see docstring) instead of always assuming it does.
        previous_title = "Ex Inv VL-proto" if suffix == "1" else f"Ex Inv VL-{int(suffix) - 1}"
        for r in range(data_start_row, last_data_row + 1):
            cpn_cell = f"A{r}"
            # IFERROR-wrapped: MATCH() is #N/A whenever this CPN doesn't exist on the
            # previous-volume sheet (a normal occurrence -- parts can drop in/out
            # between volumes), which would otherwise propagate through ABS()/the
            # subtraction and show as an error on-sheet. 0 fallback: both are numeric
            # deltas (a cost delta / a MOQ delta), not descriptive text cells.
            ws[f"AH{r}"] = (
                f"=IFERROR(ABS(INDEX('{previous_title}'!O$5:O$1029, MATCH('{title}'!{cpn_cell}, "
                f"'{previous_title}'!$A$5:$A$1029, 0)) - '{title}'!O{r}),0)"
            )
            ws[f"AI{r}"] = (
                f"=IFERROR(INDEX('{previous_title}'!T$5:T$1029, MATCH('{title}'!{cpn_cell}, "
                f"'{previous_title}'!$A$5:$A$1029, 0)) - '{title}'!T{r},0)"
            )

    for r in range(data_start_row, last_data_row + 1):
        for col in range(1, last_col + 1):
            cell = ws.cell(row=r, column=col)
            cell.border = _THIN_BORDER

    currency_cols = ["O", "P", "Y", "Z", "AC", "AD"] + (["AH"] if suffix != "P" else [])
    for col_letter in currency_cols:
        for r in range(data_start_row, last_data_row + 1):
            ws[f"{col_letter}{r}"].number_format = _CURRENCY_FORMAT

    summary_row = last_data_row + 1
    for col_letter in ("Y", "Z", "AC", "AD"):
        ws[f"{col_letter}{summary_row}"] = (
            f"=SUM({col_letter}{data_start_row}:{col_letter}{last_data_row})" if last_data_row >= data_start_row else 0
        )
        ws[f"{col_letter}{summary_row}"].number_format = _CURRENCY_FORMAT

    # AK1/AL1 define the row bounds ($AK$1/$AL$1) that every single
    # _index_lookup()/_sumifs_lookup()/_match_helper_formula() formula on this sheet
    # is built from (see _bounded()). Previously a runtime LOOKUP/MATCH full-column
    # scan against the CBOM sheet; now the exact same values, computed once in Python
    # (see cbom_bounds docstring above) instead of scanning up to 1,048,576 rows per
    # formula at Excel-open time.
    cbom_first_data_row, cbom_last_data_row = cbom_bounds
    ws["AK1"] = cbom_last_data_row
    ws["AL1"] = cbom_first_data_row

    for col_letter in ("AJ", "AK", "AL"):
        ws.column_dimensions[col_letter].hidden = True

    return ws


def _demo():
    import json
    from openpyxl import Workbook

    payload = [
        {
            "CPN": "CPN-1001",
            "commodity": "Passive",
            "part_description": "Resistor 10k",
            "part_qty": 10,
            "volumes": [
                {"volume": 1, "excess_in_stk": 50},
                {"volume": 2, "excess_in_stk": 30},
            ],
        },
        {
            "CPN": "CPN-1002",
            "commodity": "Semiconductor",
            "part_description": "Diode",
            "part_qty": 5,
            "volumes": [
                {"volume": 1, "excess_in_stk": "0"},
            ],
        },
    ]

    print("\n========== INPUT ==========")
    print(json.dumps(payload, indent=4))

    rows_v1 = ex_inv_vl_rows(payload, 1)

    assert rows_v1[0] == [""] and rows_v1[1] == [""] and rows_v1[2] == [""]
    assert rows_v1[3][:8] == [
        "Part Number", "Description", "Commodity", "Mfg Name", "Mfg Part Number",
        "Part Qty", "Ext Vol (Splits) #1", "Excess In Stk",
    ]
    assert rows_v1[3][-2:] == ["Cost Proto - V1", "MOQ Proto - V1"]
    assert len(rows_v1[3]) == 35  # 33 base + 2 delta labels (AJ match-helper column stays unlabeled)
    assert len(rows_v1[4]) == 36  # data rows include the unlabeled AJ helper formula
    print("ex_inv_vl_rows() header self-check passed")

    row_cpn1 = rows_v1[4]
    assert row_cpn1[0] == "CPN-1001"
    assert row_cpn1[7] == 50  # Excess In Stk, literal from JSON
    assert row_cpn1[1].startswith("=IFERROR(INDEX(") and row_cpn1[1].endswith('& ""')  # Description formula
    assert row_cpn1[8] == "=MAX(H5-G5,0)"  # Excess after demand, row-local
    assert "'7.0 CBOM VL-1'" in row_cpn1[14]  # Cost formula references the matching CBOM sheet
    assert row_cpn1[35].startswith("=IFERROR(MATCH(1,")  # AJ match helper
    print("ex_inv_vl_rows() data-row self-check passed")

    row_cpn2 = rows_v1[5]
    assert row_cpn2[0] == "CPN-1002" and row_cpn2[7] == 0  # "0" string coerced to 0
    print("ex_inv_vl_rows() numeric-coercion self-check passed")

    proto_rows = ex_inv_vl_rows(payload, "proto")
    assert len(proto_rows[3]) == 33  # no AH/AI labels for proto
    assert len(proto_rows) == 4  # 3 blank rows + header; neither CPN has a 'proto' volume entry
    print("ex_inv_vl_rows() proto-volume self-check passed")

    wb = Workbook()
    if "Sheet" in wb.sheetnames:
        del wb["Sheet"]
    ws = build_ex_inv_vl_sheet(wb, payload, 1, cbom_bounds=(18, 500))
    assert ws.title == "Ex Inv VL-1"
    assert ws["A1"].value == "Excess Cost #1"
    assert ws["V3"].value == "Excess After 1st batch"
    assert ws["AH5"].value.startswith("=IFERROR(ABS(INDEX('Ex Inv VL-proto'!")
    # AK1/AL1 are now literal ints computed in Python (see cbom_vl.cbom_vl_bounds()),
    # not runtime LOOKUP/MATCH full-column scans.
    assert ws["AK1"].value == 500 and ws["AL1"].value == 18
    assert ws.column_dimensions["AJ"].hidden is True
    print("build_ex_inv_vl_sheet() self-check passed")

    build_ex_inv_vl_sheet(wb, payload, 2, cbom_bounds=(18, 400))  # exercise the non-'1' previous-sheet branch
    ws2 = wb["Ex Inv VL-2"]
    assert ws2["AH5"].value.startswith("=IFERROR(ABS(INDEX('Ex Inv VL-1'!")
    print("build_ex_inv_vl_sheet() volume-2 previous-sheet self-check passed")

    wb.save("Ex_Inv_VL_Output.xlsx")
    print("\nExcel generated successfully.")
    print("File : Ex_Inv_VL_Output.xlsx")


if __name__ == "__main__":
    _demo()
