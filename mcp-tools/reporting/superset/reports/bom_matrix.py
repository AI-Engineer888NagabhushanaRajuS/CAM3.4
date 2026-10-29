"""Python port of the BOM Matrix live-formula Excel export (Laravel PHP).

Port of app/Exports/BomMatrixFormatExportExcelFormula.php: given the BOM
Matrix JSON rows described in bom_matrix.md, writes a 'BOM MATRIX'
worksheet whose cells hold live Excel formulas (matching the original)
rather than static values. Those formulas reference other sheets
('7.0 CBOM VL-{n}', '7.0 CBOM Proto', 'Ex Inv VL-{n}', 'Ex Inv VL-proto')
that must exist elsewhere in the same workbook — this module does not
evaluate them. No pure JSON transform is ported here (unlike Sum & Count)
since only the Excel-formula variant was requested for this report.

v2 source schema note: "EAU Volumes" values are plain dict lookups
(`row["EAU Volumes"][vl]`) with no assumption baked in about where they came
from -- this file needed no changes when the confirmed source for EAU became
the `volume` table (fg, volume_name, batch_qty -- aliased volume_qty; see
cbom-database-schema-design.md) instead of the previously-guessed source.
Only the loader that builds `rows` needs to populate that key correctly.
"""

import re

from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

EXCESS_FIELDS = [
    "Pkg Qty", "MOQ", "Lead Time", "Long Comment", "Price Control", "NCNR",
    "Price Validity", "Effective Date", "Supp Name", "Corrected MPN", "Net Excess Cost",
]

_HEADER_COLORS = ["74B2E6", "F56767", "75D975", "AD92F8", "FFE06D"]
_LIGHT_COLORS = ["D9EAF7", "FDE2E2", "E2F7E2", "E9E2FD", "FFF7D9"]
_BLUE = "2F5496"
_WHITE = "FFFFFF"
_DATA_FILL_COLOR = "F2F6FC"
_CENTER = Alignment(horizontal="center")
_THIN_SIDE = Side(style="thin", color="000000")
_THICK_SIDE = Side(style="medium", color="000000")


def _fill(rgb):
    return PatternFill("solid", fgColor=rgb)


def _style_range(ws, col1, row1, col2, row2, fill=None, font=None, alignment=None):
    """Mirrors PhpSpreadsheet's getStyleByColumnAndRow(...)->applyFromArray(...): applies uniformly to every cell in the range."""
    for r in range(row1, row2 + 1):
        for c in range(col1, col2 + 1):
            cell = ws.cell(row=r, column=c)
            if fill is not None:
                cell.fill = fill
            if font is not None:
                cell.font = font
            if alignment is not None:
                cell.alignment = alignment


def _border_all(ws, col1, row1, col2, row2, side):
    """Mirrors PHP's 'allBorders' thin-border style: every cell in the range gets all 4 sides."""
    border = Border(left=side, right=side, top=side, bottom=side)
    for r in range(row1, row2 + 1):
        for c in range(col1, col2 + 1):
            ws.cell(row=r, column=c).border = border


def _border_outline(ws, col1, row1, col2, row2, side):
    """Mirrors PHP's 'outline' thick-border style: only the rectangle's outer edge, preserving other sides already set."""
    for r in range(row1, row2 + 1):
        for c in range(col1, col2 + 1):
            cell = ws.cell(row=r, column=c)
            b = cell.border
            cell.border = Border(
                left=side if c == col1 else b.left,
                right=side if c == col2 else b.right,
                top=side if r == row1 else b.top,
                bottom=side if r == row2 else b.bottom,
            )


def _apply_number_format(ws, col1, row1, col2, row2, fmt):
    for r in range(row1, row2 + 1):
        for c in range(col1, col2 + 1):
            ws.cell(row=r, column=c).number_format = fmt


def _cbom_sheet_name_for(volume_key):
    suffix = volume_key.strip().lower()
    match = re.search(r"vl-?(\d+)", suffix, re.IGNORECASE)
    if match:
        return f"7.0 CBOM VL-{match.group(1)}"
    if "proto" in suffix:
        return "7.0 CBOM Proto"
    parts = volume_key.split("-")
    return f"7.0 CBOM VL-{parts[-1] if parts[-1] else volume_key}"


def _ex_inv_sheet_name_for(volume_key):
    suffix = volume_key.strip().lower()
    match = re.search(r"vl-?(\d+)", suffix, re.IGNORECASE)
    if match:
        return f"Ex Inv VL-{match.group(1)}"
    if "proto" in suffix:
        return "Ex Inv VL-proto"
    parts = volume_key.split("-")
    return f"Ex Inv VL-{parts[-1] if parts[-1] else volume_key}"


def _bounded_col(col_range, last_row):
    """Converts a full-column ref like '$D:$D' into '$D$1:$D${last_row}'. Bounding
    to row 1 through the target sheet's own known last row (instead of the full
    1,048,576-row column) is behaviorally identical -- no data exists past that row
    either way -- but avoids the massive scan cost that was a major contributor to
    slow Excel load times (see Test_fixes/EXCEL_LOAD_PERFORMANCE.md).
    """
    col = col_range.strip("$").split(":")[0]
    return f"${col}$1:${col}${last_row}"


def _cbom_lookup_if_af_true(cbom_sheet, a_ref, target_col_range, if_false, cbom_last_row):
    c_range = _bounded_col("$C:$C", cbom_last_row)
    af_range = _bounded_col("$AF:$AF", cbom_last_row)
    target_range = _bounded_col(target_col_range, cbom_last_row)
    match = f"MATCH({a_ref}, '{cbom_sheet}'!{c_range}, 0)"
    af_val = f"INDEX('{cbom_sheet}'!{af_range}, {match})"
    val = f"INDEX('{cbom_sheet}'!{target_range}, {match})"
    return f'=IFERROR(IF(UPPER(TRIM({af_val}))="TRUE", {val}, {if_false}), "")'


def _fg_price_lookup(cbom_sheet, fg_name, a_ref, cbom_last_row):
    """Per-(FG, Part Number) price lookup for the FG price matrix -- unlike
    _cbom_lookup_if_af_true() above (CPN-only match, used for every other
    per-CPN field on this sheet, where a single first-match is the right
    answer), a CPN used in more than one Assembly/FG has one row per FG in
    the CBOM VL sheet, each carrying that FG's own price. Matching on CPN
    alone (as the FG Total Cost formula used to, via the shared Unit Price
    cell) picks whichever FG's row happens to come first for every FG
    column alike -- this two-condition match (FG name AND Part Number, both
    array-multiplied the same way aclass_parts.py's _match_expression()
    already does for its own AND-style condition) ties each FG's total back
    to that FG's own row instead.
    """
    fg_lit = str(fg_name).replace('"', '""')
    a_range = _bounded_col("$A:$A", cbom_last_row)
    c_range = _bounded_col("$C:$C", cbom_last_row)
    af_range = _bounded_col("$AF:$AF", cbom_last_row)
    k_range = _bounded_col("$K:$K", cbom_last_row)
    match = (
        f"MATCH(1, INDEX(('{cbom_sheet}'!{a_range}=\"{fg_lit}\")*"
        f"('{cbom_sheet}'!{c_range}={a_ref})*"
        f"(UPPER(TRIM('{cbom_sheet}'!{af_range}))=\"TRUE\"), 0), 0)"
    )
    return f"IFERROR(INDEX('{cbom_sheet}'!{k_range}, {match}), 0)"


def build_bom_matrix_sheet(wb, rows, cbom_row_counts, ex_inv_row_counts):
    """Port of BomMatrixFormatExportExcelFormula: live-formula 'BOM MATRIX' sheet.

    wb: an openpyxl.Workbook to append the sheet to.
    rows: the list of dicts described in bom_matrix.md (BOM Matrix JSON).
    cbom_row_counts: {cbom_sheet_name: last_row} for every '7.0 CBOM VL-{n}'/
        '7.0 CBOM Proto' sheet this workbook will contain -- computed early via
        cbom_vl.cbom_vl_rows() (before those sheets are actually built later in
        exporter.py) purely to get len(rows), so this sheet's cross-references to
        them can be bounded instead of scanning full columns. Required (no
        default/fallback): a missing entry should raise loudly rather than risk
        silently under-bounding a formula (see EXCEL_LOAD_PERFORMANCE.md's own
        "most dangerous failure mode" warning).
    ex_inv_row_counts: same, for every 'Ex Inv VL-{n}'/'Ex Inv VL-proto' sheet.

    Data rows are written with the same static values BomMatrixFormatExport
    would produce, then most cells are overwritten with live formulas
    referencing the CBOM/Ex-Inv sheets. Header styling (rows 6-8) replicates
    the original PHP pixel-for-pixel, including two real quirks preserved
    on purpose: the merged 'FG Grand Totals' label is immediately
    overwritten to 'Grand Total' by a later loop touching the same cell,
    and 'Price Validity'/'Effective Date' are the only two Excess Info
    fields that never get converted to formulas.
    """
    ws = wb.create_sheet(title="BOM MATRIX")
    if not rows:
        return ws

    fg_keys = sorted({fg for row in rows for fg in row.get("FG Counts", {})})
    # "VL-proto" sorts first (matches Summary's own proto-first volume-column ordering);
    # int(vl.split("-")[1]) alone would crash on "proto" via int("proto").
    volume_keys = sorted(
        {vl for row in rows for vl in row.get("EAU Volumes", {})},
        key=lambda vl: (0, 0) if vl.split("-", 1)[1].lower() == "proto" else (1, int(vl.split("-", 1)[1])),
    )
    has_proto = any("Proto Qty" in row or "Proto Price" in row for row in rows)

    # --- column layout (mirrors array() + injectFormulas offset math) ---
    part_number_col = 1
    fg_count_start = part_number_col + 1
    fg_count_cols = {fg: fg_count_start + i for i, fg in enumerate(fg_keys)}
    grand_total_col = fg_count_start + len(fg_keys)
    eau_start = grand_total_col + 1
    eau_cols = {vl: eau_start + i for i, vl in enumerate(volume_keys)}
    description_col = eau_start + len(volume_keys)
    commodity_col = description_col + 1
    proto_qty_col = commodity_col + 1 if has_proto else None
    proto_price_col = commodity_col + 2 if has_proto else None
    mfg_block_start = commodity_col + 1 + (2 if has_proto else 0)
    mfg_name_cols = [mfg_block_start + vi * 3 for vi in range(len(volume_keys))]
    mpn_cols = [mfg_block_start + vi * 3 + 1 for vi in range(len(volume_keys))]
    unit_price_cols = [mfg_block_start + vi * 3 + 2 for vi in range(len(volume_keys))]
    fg_price_start = mfg_block_start + len(volume_keys) * 3
    fg_price_cols = {
        (fi, vi): fg_price_start + fi * len(volume_keys) + vi
        for fi in range(len(fg_keys))
        for vi in range(len(volume_keys))
    }
    fg_grand_start = fg_price_start + len(fg_keys) * len(volume_keys)
    fg_grand_cols = [fg_grand_start + vi for vi in range(len(volume_keys))]
    ex_start = fg_grand_start + len(volume_keys)
    ex_cols = {
        (vi, fi): ex_start + vi * len(EXCESS_FIELDS) + fi
        for vi in range(len(volume_keys))
        for fi in range(len(EXCESS_FIELDS))
    }
    last_col = ex_start + len(volume_keys) * len(EXCESS_FIELDS) - 1

    # --- data rows: static values first (mirrors BomMatrixFormatExport::array()) ---
    last_data_row = 8 + len(rows)
    for r_offset, row in enumerate(rows):
        r = 9 + r_offset
        ws.cell(row=r, column=part_number_col).value = row.get("Part Number", "")
        for fg, col in fg_count_cols.items():
            ws.cell(row=r, column=col).value = row.get("FG Counts", {}).get(fg, "-")
        ws.cell(row=r, column=grand_total_col).value = row.get("Grand Total", "")
        for vl, col in eau_cols.items():
            ws.cell(row=r, column=col).value = row.get("EAU Volumes", {}).get(vl, "-")
        ws.cell(row=r, column=description_col).value = row.get("Part Description", "-")
        ws.cell(row=r, column=commodity_col).value = row.get("Commodity", "-")
        if has_proto:
            ws.cell(row=r, column=proto_qty_col).value = row.get("Proto Qty", "-")
            ws.cell(row=r, column=proto_price_col).value = row.get("Proto Price", "-")
        for vi, vl in enumerate(volume_keys):
            ws.cell(row=r, column=mfg_name_cols[vi]).value = row.get("Mfg Name Volumes", {}).get(vl, "-")
            ws.cell(row=r, column=mpn_cols[vi]).value = row.get("Mfg Part Number Volumes", {}).get(vl, "-")
            ws.cell(row=r, column=unit_price_cols[vi]).value = row.get("Unit Prices", {}).get(vl, "-")
        for fi, fg in enumerate(fg_keys):
            for vi, vl in enumerate(volume_keys):
                ws.cell(row=r, column=fg_price_cols[(fi, vi)]).value = (
                    row.get("FG Total Costs", {}).get(fg, {}).get(vl, "-")
                )
        for vi, vl in enumerate(volume_keys):
            ws.cell(row=r, column=fg_grand_cols[vi]).value = row.get("FG Grand Totals", {}).get(vl, "-")
        for vi, vl in enumerate(volume_keys):
            mpn_for_vl = row.get("Mfg Part Number Volumes", {}).get(vl, "")
            ex_entry = next(
                (e for e in row.get("Excess Info", {}).get(vl, []) if e.get("MPN") == mpn_for_vl),
                {},
            )
            for fi, field in enumerate(EXCESS_FIELDS):
                ws.cell(row=r, column=ex_cols[(vi, fi)]).value = ex_entry.get(field, "-")

    # === Step A: F2F6FC fill on the early data-row columns ===
    early_cols = [part_number_col, *fg_count_cols.values(), grand_total_col, *eau_cols.values(),
                  description_col, commodity_col]
    if has_proto:
        early_cols += [proto_qty_col, proto_price_col]
    for col in early_cols:
        _style_range(ws, col, 9, col, last_data_row, fill=_fill(_DATA_FILL_COLOR))

    # === Step C/D: light-color fill on FG price matrix + FG Grand Totals data rows ===
    for fi in range(len(fg_keys)):
        for vi in range(len(volume_keys)):
            col = fg_price_cols[(fi, vi)]
            _style_range(ws, col, 9, col, last_data_row, fill=_fill(_LIGHT_COLORS[vi % 5]))
    for vi in range(len(volume_keys)):
        col = fg_grand_cols[vi]
        _style_range(ws, col, 9, col, last_data_row, fill=_fill(_LIGHT_COLORS[vi % 5]))

    # === Step E: row 8 static header labels ===
    ws.cell(row=8, column=part_number_col).value = "Part Number"
    _style_range(ws, part_number_col, 8, part_number_col, 8, alignment=_CENTER)
    for fg, col in fg_count_cols.items():
        ws.cell(row=8, column=col).value = fg
        _style_range(ws, col, 8, col, 8, alignment=_CENTER)
    ws.cell(row=8, column=grand_total_col).value = "Grand Total"
    _style_range(ws, grand_total_col, 8, grand_total_col, 8, alignment=_CENTER)
    for vl, col in eau_cols.items():
        ws.cell(row=8, column=col).value = f"EAU {vl}"
        _style_range(ws, col, 8, col, 8, alignment=_CENTER)
    ws.cell(row=8, column=description_col).value = "Description"
    _style_range(ws, description_col, 8, description_col, 8, alignment=_CENTER)
    ws.cell(row=8, column=commodity_col).value = "Commodity"
    _style_range(ws, commodity_col, 8, commodity_col, 8, alignment=_CENTER)
    if has_proto:
        ws.cell(row=8, column=proto_qty_col).value = "Proto Qty"
        _style_range(ws, proto_qty_col, 8, proto_qty_col, 8, alignment=_CENTER)
        ws.cell(row=8, column=proto_price_col).value = "Proto Price"
        _style_range(ws, proto_price_col, 8, proto_price_col, 8, alignment=_CENTER)

    # === Mfg block: row 7 merged volume label + light data-row fill + row 8 sub-labels ===
    for vi, vl in enumerate(volume_keys):
        start = mfg_name_cols[vi]
        end = start + 2
        ws.merge_cells(start_row=7, start_column=start, end_row=7, end_column=end)
        ws.cell(row=7, column=start).value = vl
        _style_range(ws, start, 7, end, 7, fill=_fill(_HEADER_COLORS[vi % 5]), alignment=_CENTER)
        _style_range(ws, start, 9, end, last_data_row, fill=_fill(_LIGHT_COLORS[vi % 5]))

        ws.cell(row=8, column=mfg_name_cols[vi]).value = "Mfg Name"
        _style_range(ws, mfg_name_cols[vi], 8, mfg_name_cols[vi], 8, alignment=_CENTER)
        ws.cell(row=8, column=mpn_cols[vi]).value = "Mfg Part Number"
        _style_range(ws, mpn_cols[vi], 8, mpn_cols[vi], 8, alignment=_CENTER)
        ws.cell(row=8, column=unit_price_cols[vi]).value = "Unit Price"
        _style_range(ws, unit_price_cols[vi], 8, unit_price_cols[vi], 8, alignment=_CENTER)

    # === Navy overlay across every header cell built so far (row 8, cols 1..end of Mfg block) ===
    end_blue = mfg_block_start + len(volume_keys) * 3 - 1
    _style_range(ws, 1, 8, end_blue, 8, fill=_fill(_BLUE), font=Font(color=_WHITE))
    _border_all(ws, 1, 8, end_blue, 8, _THIN_SIDE)
    for vi in range(len(volume_keys)):
        start = mfg_name_cols[vi]
        _border_all(ws, start, 7, start + 2, 7, _THIN_SIDE)
    # (PHP's next loop, `for ($c = $startBlue; $c <= $endBlue; ...)`, never executes —
    # startBlue has already walked past endBlue by this point — so it's a dead no-op
    # in the original; nothing to port.)

    # === FG price matrix header: row 6 volume label + row 7 SUM formula, row 8 merged FG label ===
    for fi, fg in enumerate(fg_keys):
        for vi, vl in enumerate(volume_keys):
            col = fg_price_cols[(fi, vi)]
            ws.cell(row=6, column=col).value = vl
            _style_range(ws, col, 6, col, 6, fill=_fill(_HEADER_COLORS[vi % 5]), alignment=_CENTER)
            col_letter = get_column_letter(col)
            ws.cell(row=7, column=col).value = f"=SUM({col_letter}9:{col_letter}{last_data_row})"
            _style_range(ws, col, 7, col, 7, fill=_fill(_LIGHT_COLORS[vi % 5]), alignment=_CENTER)
        start = fg_price_cols[(fi, 0)]
        end = fg_price_cols[(fi, len(volume_keys) - 1)]
        ws.merge_cells(start_row=8, start_column=start, end_row=8, end_column=end)
        ws.cell(row=8, column=start).value = fg
        _style_range(ws, start, 8, end, 8, fill=_fill(_BLUE), alignment=_CENTER)
        _border_all(ws, start, 8, end, 8, _THIN_SIDE)
        _border_outline(ws, start, 8, end, 8, _THICK_SIDE)

    # === FG Grand Totals block (replicates the 'FG Grand Totals'->'Grand Total' overwrite quirk) ===
    fg_grand_first = fg_grand_cols[0]
    fg_grand_last = fg_grand_cols[-1]
    ws.merge_cells(start_row=8, start_column=fg_grand_first, end_row=8, end_column=fg_grand_last)
    ws.cell(row=8, column=fg_grand_first).value = "FG Grand Totals"
    _style_range(ws, fg_grand_first, 8, fg_grand_last, 8, alignment=_CENTER)
    for vi, vl in enumerate(volume_keys):
        col = fg_grand_cols[vi]
        ws.cell(row=7, column=col).value = vl
        if col == fg_grand_first:
            # Only the merge's anchor cell is settable in openpyxl (and the only
            # one Excel would ever display) — this single write is what makes the
            # earlier 'FG Grand Totals' label invisible, matching the PHP quirk.
            ws.cell(row=8, column=col).value = "Grand Total"
        _style_range(ws, col, 7, col, 7, alignment=_CENTER)
        _style_range(ws, col, 8, col, 8, alignment=_CENTER)
        _border_all(ws, col, 7, col, 7, _THIN_SIDE)
        _border_all(ws, col, 8, col, 8, _THIN_SIDE)
        _style_range(ws, col, 7, col, 7, fill=_fill(_HEADER_COLORS[vi % 5]))
    _border_outline(ws, fg_grand_first, 8, fg_grand_last, 8, _THICK_SIDE)
    _style_range(ws, fg_grand_first, 8, fg_grand_last, 8, fill=_fill(_BLUE), font=Font(color=_WHITE))

    # === EX blocks: row 7 merged 'EX-{vl}' label, row 8 field labels, body fill ===
    for vi, vl in enumerate(volume_keys):
        start = ex_cols[(vi, 0)]
        end = ex_cols[(vi, len(EXCESS_FIELDS) - 1)]
        ws.merge_cells(start_row=7, start_column=start, end_row=7, end_column=end)
        ws.cell(row=7, column=start).value = f"EX-{vl}"
        _style_range(ws, start, 7, end, 7, fill=_fill(_HEADER_COLORS[vi % 5]), alignment=_CENTER)
        _border_outline(ws, start, 7, end, 7, _THICK_SIDE)
        for fi, field in enumerate(EXCESS_FIELDS):
            col = ex_cols[(vi, fi)]
            ws.cell(row=8, column=col).value = field
            _style_range(ws, col, 8, col, 8, fill=_fill(_BLUE), font=Font(color=_WHITE), alignment=_CENTER)
            _border_all(ws, col, 8, col, 8, _THIN_SIDE)
        _style_range(ws, start, 9, end, last_data_row, fill=_fill(_LIGHT_COLORS[vi % 5]))

    # === Final thin-border reapply pass over row 6/7 cells that hold a value ===
    for col in range(1, last_col + 1):
        if ws.cell(row=6, column=col).value not in (None, ""):
            _border_all(ws, col, 6, col, 6, _THIN_SIDE)
        if ws.cell(row=7, column=col).value not in (None, ""):
            _border_all(ws, col, 7, col, 7, _THIN_SIDE)

    # === Number formats (currency) ===
    currency_format = '"$"#,##0.0000'  # exactly 4 decimal places
    for col in unit_price_cols:
        _apply_number_format(ws, col, 9, col, last_data_row, currency_format)
    if has_proto:
        _apply_number_format(ws, proto_price_col, 9, proto_price_col, last_data_row, currency_format)
    if fg_price_cols:
        fg_price_last = fg_price_start + len(fg_keys) * len(volume_keys) - 1
        _apply_number_format(ws, fg_price_start, 9, fg_price_last, last_data_row, currency_format)
        _apply_number_format(ws, fg_price_start, 7, fg_price_last, 7, currency_format)
    if fg_grand_cols:
        _apply_number_format(ws, fg_grand_first, 9, fg_grand_last, last_data_row, currency_format)
        _apply_number_format(ws, fg_grand_first, 7, fg_grand_last, 7, currency_format)
    net_excess_index = EXCESS_FIELDS.index("Net Excess Cost")
    for vi in range(len(volume_keys)):
        col = ex_cols[(vi, net_excess_index)]
        _apply_number_format(ws, col, 9, col, last_data_row, currency_format)

    # === Formula injection over data rows (mirrors 'Inject formulas...' block) ===
    base_cbom_sheet = _cbom_sheet_name_for(volume_keys[0])
    ex_formula_fields = [
        ("Pkg Qty", "$Q:$Q"), ("MOQ", "$R:$R"), ("Lead Time", "$S:$S"),
        ("Long Comment", "$X:$X"), ("Price Control", "$W:$W"), ("NCNR", "$V:$V"),
        ("Supp Name", "$P:$P"), ("Corrected MPN", "$AB:$AB"),
    ]  # "Price Validity"/"Effective Date" deliberately excluded — see docstring.

    base_cbom_last_row = cbom_row_counts[base_cbom_sheet]

    for r_offset in range(len(rows)):
        row_num = 9 + r_offset
        a_ref = f"${get_column_letter(part_number_col)}{row_num}"

        ws.cell(row=row_num, column=description_col).value = _cbom_lookup_if_af_true(
            base_cbom_sheet, a_ref, "$D:$D", '""', base_cbom_last_row
        )
        ws.cell(row=row_num, column=commodity_col).value = _cbom_lookup_if_af_true(
            base_cbom_sheet, a_ref, "$E:$E", '""', base_cbom_last_row
        )

        for vi, vl in enumerate(volume_keys):
            cbom_sheet = _cbom_sheet_name_for(vl)
            cbom_last_row = cbom_row_counts[cbom_sheet]
            ws.cell(row=row_num, column=mfg_name_cols[vi]).value = _cbom_lookup_if_af_true(
                cbom_sheet, a_ref, "$F:$F", '""', cbom_last_row
            )
            ws.cell(row=row_num, column=mpn_cols[vi]).value = _cbom_lookup_if_af_true(
                cbom_sheet, a_ref, "$G:$G", '""', cbom_last_row
            )
            ws.cell(row=row_num, column=unit_price_cols[vi]).value = _cbom_lookup_if_af_true(
                cbom_sheet, a_ref, "$K:$K", "0", cbom_last_row
            )

        for fi in range(len(fg_keys)):
            fg_qty_letter = get_column_letter(fg_count_cols[fg_keys[fi]])
            for vi, vl in enumerate(volume_keys):
                cbom_sheet = _cbom_sheet_name_for(vl)
                cbom_last_row = cbom_row_counts[cbom_sheet]
                ws.cell(row=row_num, column=fg_price_cols[(fi, vi)]).value = (
                    f"=IFERROR({_fg_price_lookup(cbom_sheet, fg_keys[fi], a_ref, cbom_last_row)}"
                    f"*${fg_qty_letter}{row_num},0)"
                )

        for vi in range(len(volume_keys)):
            fg_cost_letters = [get_column_letter(fg_price_cols[(fi, vi)]) for fi in range(len(fg_keys))]
            ws.cell(row=row_num, column=fg_grand_cols[vi]).value = (
                "=" + "+".join(f"{letter}{row_num}" for letter in fg_cost_letters)
            )

        for vi, vl in enumerate(volume_keys):
            cbom_sheet = _cbom_sheet_name_for(vl)
            cbom_last_row = cbom_row_counts[cbom_sheet]
            ex_inv_sheet = _ex_inv_sheet_name_for(vl)
            ex_inv_last_row = ex_inv_row_counts[ex_inv_sheet]
            for field, target_range in ex_formula_fields:
                col = ex_cols[(vi, EXCESS_FIELDS.index(field))]
                ws.cell(row=row_num, column=col).value = _cbom_lookup_if_af_true(
                    cbom_sheet, a_ref, target_range, '""', cbom_last_row
                )
            net_excess_col = ex_cols[(vi, net_excess_index)]
            ws.cell(row=row_num, column=net_excess_col).value = (
                f"=IFERROR(INDEX('{ex_inv_sheet}'!$AC$1:$AC${ex_inv_last_row}, "
                f"MATCH({a_ref}, '{ex_inv_sheet}'!$A$1:$A${ex_inv_last_row}, 0)), 0)"
            )
            # Price Validity / Effective Date are never converted to formulas — left as-is.

    # === Footer row ===
    footer_row = last_data_row + 1
    ws.cell(row=footer_row, column=1).value = "Price Validity will be ensured by Centum Sourcing Team."
    ws.merge_cells(start_row=footer_row, start_column=1, end_row=footer_row, end_column=last_col)

    return ws


def _demo():
    row = {
        "Part Number": "CPN-1001",
        "FG Counts": {"FG-A": 10},
        "Grand Total": 10,
        "EAU Volumes": {"VL-1": 1000, "VL-2": 500},
        "Mfg Part Number Volumes": {"VL-1": "MPN-1", "VL-2": "MPN-1"},
        "Mfg Name Volumes": {"VL-1": "ACME", "VL-2": "ACME"},
        "Unit Prices": {"VL-1": 1.5, "VL-2": 1.4},
        "FG Total Costs": {"FG-A": {"VL-1": 15.0, "VL-2": 14.0}},
        "FG Grand Totals": {"VL-1": 15.0, "VL-2": 14.0},
        "Excess Info": {
            "VL-1": [{
                "MPN": "MPN-1", "Pkg Qty": 100, "MOQ": 500, "Lead Time": "-",
                "Long Comment": "std lead time", "Price Control": "Centum", "NCNR": "No",
                "Price Validity": "Valid for 30 Days", "Effective Date": "15/01/26",
                "Supp Name": "Acme Corp", "Corrected MPN": "MPN-1A", "Net Excess Cost": "-",
            }],
            "VL-2": [{
                "MPN": "MPN-1", "Pkg Qty": 100, "MOQ": 500, "Lead Time": "-",
                "Long Comment": "std lead time", "Price Control": "Centum", "NCNR": "No",
                "Price Validity": "Valid for 30 Days", "Effective Date": "15/01/26",
                "Supp Name": "Acme Corp", "Corrected MPN": "MPN-1A", "Net Excess Cost": "-",
            }],
        },
        "Part Description": "Resistor 10k",
        "Commodity": "Passive",
        "Proto Qty": 20,
        "Proto Price": 1.0,
    }
    rows = [row]

    from openpyxl import Workbook

    wb = Workbook()
    cbom_row_counts = {"7.0 CBOM VL-1": 500, "7.0 CBOM VL-2": 400}
    ex_inv_row_counts = {"Ex Inv VL-1": 200, "Ex Inv VL-2": 150}
    ws = build_bom_matrix_sheet(wb, rows, cbom_row_counts, ex_inv_row_counts)

    assert ws.title == "BOM MATRIX"

    # Column layout for this sample: FG-A=col2, Grand Total=3, EAU VL-1/VL-2=4/5,
    # Description=6, Commodity=7, Proto Qty/Price=8/9, Mfg block VL-1=10-12,
    # VL-2=13-15, FG price matrix=16-17, FG Grand Totals=18-19, EX VL-1=20-30, VL-2=31-41.
    header_texts = {
        1: "Part Number", 2: "FG-A", 3: "Grand Total", 4: "EAU VL-1", 5: "EAU VL-2",
        6: "Description", 7: "Commodity", 8: "Proto Qty", 9: "Proto Price",
        10: "Mfg Name", 11: "Mfg Part Number", 12: "Unit Price",
        13: "Mfg Name", 14: "Mfg Part Number", 15: "Unit Price",
    }
    for col, expected in header_texts.items():
        actual = ws.cell(row=8, column=col).value
        assert actual == expected, f"col {col}: expected {expected!r}, got {actual!r}"

    # 'FG Grand Totals' -> 'Grand Total' overwrite quirk, reproduced.
    assert ws.cell(row=8, column=18).value == "Grand Total"

    # Row 7 SUM formula for the FG-A x VL-1 price-matrix column (col 16 = 'P').
    assert ws.cell(row=7, column=16).value == "=SUM(P9:P9)"

    # Unit Price formula (col 12) looks up '7.0 CBOM VL-1' via a guarded MATCH/INDEX,
    # bounded to that sheet's own known last row instead of a full column.
    expected_unit_price = _cbom_lookup_if_af_true("7.0 CBOM VL-1", "$A9", "$K:$K", "0", 500)
    assert ws.cell(row=9, column=12).value == expected_unit_price

    # FG price matrix formula: per-(FG, Part Number) lookup against '7.0 CBOM VL-1'
    # (not the shared Unit Price cell -- a CPN used in more than one FG needs each
    # FG's own price) * FG Counts(FG-A, col B).
    expected_fg_price = f"=IFERROR({_fg_price_lookup('7.0 CBOM VL-1', 'FG-A', '$A9', 500)}*$B9,0)"
    assert ws.cell(row=9, column=16).value == expected_fg_price

    # FG Grand Total (col 18, VL-1): sum of this row's own FG Total Cost cells for
    # that volume (here just the one FG-A column, P) -- always internally consistent
    # with what the FG columns show, rather than re-deriving from Unit Price*Grand Total.
    assert ws.cell(row=9, column=18).value == "=P9"

    # Net Excess Cost formula (last of the 11 EX fields for VL-1, col 30) pulls from Ex Inv,
    # bounded to that sheet's own known last row instead of a full column.
    assert ws.cell(row=9, column=30).value == (
        "=IFERROR(INDEX('Ex Inv VL-1'!$AC$1:$AC$200, MATCH($A9, 'Ex Inv VL-1'!$A$1:$A$200, 0)), 0)"
    )

    # Price Validity / Effective Date (cols 26/27 for VL-1) keep their static values.
    assert ws.cell(row=9, column=26).value == "Valid for 30 Days"
    assert ws.cell(row=9, column=27).value == "15/01/26"

    # Footer row.
    assert ws.cell(row=10, column=1).value == "Price Validity will be ensured by Centum Sourcing Team."

    # Representative fill colors: Mfg-block VL-1 header (row 7) and its data-row fill.
    assert ws.cell(row=7, column=10).fill.fgColor.rgb.endswith("74B2E6")
    assert ws.cell(row=9, column=10).fill.fgColor.rgb.endswith("D9EAF7")

    print("build_bom_matrix_sheet self-check passed")


if __name__ == "__main__":
    _demo()
