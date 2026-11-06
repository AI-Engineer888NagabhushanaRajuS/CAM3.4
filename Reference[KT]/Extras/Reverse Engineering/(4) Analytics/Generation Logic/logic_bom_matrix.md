# Generation logic: bom_matrix

Source: GitHub solutionsDigibull/BuLLMQuote_SRIM @ 540918090b1b, mcp-tools/reporting/superset/reports/bom_matrix.py
Method: static read of the module (docstrings, function bodies, constants). Statements labelled INFERENCE are not stated in code.

## Module docstring

Python port of the BOM Matrix live-formula Excel export (Laravel PHP).

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

## Module constants

- `EXCESS_FIELDS = [     "Pkg Qty", "MOQ", "Lead Time", "Long Comment", "Price Control", "NCNR",     "Price Validity", "Effective Date", "Supp Name", "Corrected MPN", "Net Excess Cost", ]`
- `_HEADER_COLORS = ["74B2E6", "F56767", "75D975", "AD92F8", "FFE06D"]`
- `_LIGHT_COLORS = ["D9EAF7", "FDE2E2", "E2F7E2", "E9E2FD", "FFF7D9"]`
- `_BLUE = "2F5496"`
- `_WHITE = "FFFFFF"`
- `_DATA_FILL_COLOR = "F2F6FC"`
- `_CENTER = Alignment(horizontal="center")`
- `_THIN_SIDE = Side(style="thin", color="000000")`
- `_THICK_SIDE = Side(style="medium", color="000000")`

## Functions (line, name, first docstring line)

- L40 `_fill(rgb)` 
- L44 `_style_range(ws, col1, row1, col2, row2, fill, font, alignment)` Mirrors PhpSpreadsheet's getStyleByColumnAndRow(...)->applyFromArray(...): applies uniformly to every cell in the range.
- L57 `_border_all(ws, col1, row1, col2, row2, side)` Mirrors PHP's 'allBorders' thin-border style: every cell in the range gets all 4 sides.
- L65 `_border_outline(ws, col1, row1, col2, row2, side)` Mirrors PHP's 'outline' thick-border style: only the rectangle's outer edge, preserving other sides already set.
- L79 `_apply_number_format(ws, col1, row1, col2, row2, fmt)` 
- L85 `_cbom_sheet_name_for(volume_key)` 
- L96 `_ex_inv_sheet_name_for(volume_key)` 
- L107 `_bounded_col(col_range, last_row)` Converts a full-column ref like '$D:$D' into '$D$1:$D${last_row}'. Bounding
- L118 `_cbom_lookup_if_af_true(cbom_sheet, a_ref, target_col_range, if_false, cbom_last_row)` 
- L128 `_fg_price_lookup(cbom_sheet, fg_name, a_ref, cbom_last_row)` Per-(FG, Part Number) price lookup for the FG price matrix -- unlike
- L154 `build_bom_matrix_sheet(wb, rows, cbom_row_counts, ex_inv_row_counts)` Port of BomMatrixFormatExportExcelFormula: live-formula 'BOM MATRIX' sheet.
- L476 `_demo()` 

## Authored formula sites (line: template string; placeholders in braces are Python f-string fields)

- L125: `=IFERROR(IF(UPPER(TRIM(`
- L125: `=IFERROR(IF(UPPER(TRIM({af_val}))="TRUE", {val}, {if_false}), "")`
- L329: `=SUM(`
- L329: `=SUM({col_letter}9:{col_letter}{last_data_row})`
- L441: `=IFERROR(`
- L441: `=IFERROR({_fg_price_lookup(cbom_sheet, fg_keys[fi], a_ref, cbom_last_row)}*${fg_qty_letter}{row_num},0)`
- L463: `=IFERROR(INDEX('`
- L463: `=IFERROR(INDEX('{ex_inv_sheet}'!$AC$1:$AC${ex_inv_last_row}, MATCH({a_ref}, '{ex_inv_sheet}'!$A$1:$A${ex_inv_last_row}, 0)), 0)`
- L534: `=SUM(P9:P9)`
- L544: `=IFERROR(`
- L544: `=IFERROR({_fg_price_lookup('7.0 CBOM VL-1', 'FG-A', '$A9', 500)}*$B9,0)`
- L550: `=P9`
- L555: `=IFERROR(INDEX('Ex Inv VL-1'!$AC$1:$AC$200, MATCH($A9, 'Ex Inv VL-1'!$A$1:$A$200, 0)), 0)`

## Assembly rules read from code

(see section 'Hand analysis' of 4_generation_logic_overview.md for cross-report rules: IFERROR wrapping, bounded ranges, row anchoring)
