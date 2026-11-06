# Generation logic: price_control

Source: GitHub solutionsDigibull/BuLLMQuote_SRIM @ 540918090b1b, mcp-tools/reporting/superset/reports/price_control.py
Method: static read of the module (docstrings, function bodies, constants). Statements labelled INFERENCE are not stated in code.

## Module docstring

Python port of the Price Control report (Laravel PHP).

Two layers, mirroring the PHP pipeline:
  1. price_control() — port of PriceControlController::processPriceControl():
     buckets parts into Centum/Customer at the single last quoted volume,
     matching the input/output JSON documented in price_control.md.
  2. build_price_control_sheet() — port of app/Exports/PriceControlExportExcelFormula.php:
     writes a 'Price Control' worksheet whose cells hold live SUMPRODUCT formulas
     against the '7.0 CBOM VL-{last_volume}' sheet, rather than the static bucket sums.

No DB access happens here — rfqs/fgcounts/bom_data are supplied by the caller,
and the DB write (`price_controls` table upsert) in the original PHP is out of
scope, consistent with every other port in this project.

v2 source schema note: the finalized DB has no `fgcounts` table. The FG-level
volume-quantity multiplier this report needs now lives in the `volume` table
(columns: fg, volume_name, batch_qty -- where `batch_qty` is that table's own
misleading name for Volume Qty/EAU, not a batch quantity; see
cbom-database-schema-design.md). price_control()'s own logic is unchanged --
only the shape feeding it changes, so this file adds an adapter
(fgcounts_from_volume_rows) rather than touching price_control() itself.

## Module constants

- `_THIN_SIDE = Side(style="thin", color="000000")`
- `_THIN_BORDER = Border(left=_THIN_SIDE, right=_THIN_SIDE, top=_THIN_SIDE, bottom=_THIN_SIDE)`
- `_HEADER_FILL = PatternFill("solid", fgColor="2F5496")`
- `_HEADER_FONT = Font(bold=True, color="FFFFFF")`
- `_DATA_FILL = PatternFill("solid", fgColor="F2F6FC")`
- `_DATA_FONT = Font(color="000000")`
- `_GRAND_TOTAL_FILL = PatternFill("solid", fgColor="FFD966")`

## Functions (line, name, first docstring line)

- L31 `fgcounts_from_volume_rows(volume_rows)` v2 schema adapter: `volume` table rows (fg, volume_name, batch_qty) ->
- L51 `price_control(payload)` Port of PriceControlController::processPriceControl().
- L169 `build_price_control_sheet(wb, data, cbom_last_row, last_volume, contract_names)` Port of PriceControlExportExcelFormula: live-formula 'Price Control' sheet.
- L302 `_demo()` 

## Authored formula sites (line: template string; placeholders in braces are Python f-string fields)

- L233: `=SUMPRODUCT(--(`
- L233: `=SUMPRODUCT(--({pc_upper}="CENTUM"),--({is_data_expr}),{ext_price_n})`
- L234: `=SUMPRODUCT(--(`
- L234: `=SUMPRODUCT(--({pc_upper}="CENTUM"),--({is_data_expr}),{ext_vol_n})`
- L239: `=SUMPRODUCT(--((`
- L239: `=SUMPRODUCT(--(({pc_upper}="CNP")+({pc_upper}="CUSTOMER")),--({is_data_expr}),{ext_price_n})`
- L240: `=SUMPRODUCT(--((`
- L240: `=SUMPRODUCT(--(({pc_upper}="CNP")+({pc_upper}="CUSTOMER")),--({is_data_expr}),{ext_vol_n})`
- L250: `=SUMPRODUCT(--(`
- L250: `=SUMPRODUCT(--({pc_upper}="{upper_name}"),--({is_data_expr}),{ext_price_n})`
- L251: `=SUMPRODUCT(--(`
- L251: `=SUMPRODUCT(--({pc_upper}="{upper_name}"),--({is_data_expr}),{ext_vol_n})`
- L257: `=SUM(B2:B`
- L257: `=SUM(B2:B{data_row_end})`
- L257: `=SUM(C2:C`
- L257: `=SUM(C2:C{data_row_end})`
- L260: `=IF($C$`
- L260: `=IF($C${grand_total_row_number}=0,0,C{excel_row}/$C${grand_total_row_number})`

## Assembly rules read from code

(see section 'Hand analysis' of 4_generation_logic_overview.md for cross-report rules: IFERROR wrapping, bounded ranges, row anchoring)
