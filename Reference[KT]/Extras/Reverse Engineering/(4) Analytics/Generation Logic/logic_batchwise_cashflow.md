# Generation logic: batchwise_cashflow

Source: GitHub solutionsDigibull/BuLLMQuote_SRIM @ 540918090b1b, mcp-tools/reporting/superset/reports/batchwise_cashflow.py
Method: static read of the module (docstrings, function bodies, constants). Statements labelled INFERENCE are not stated in code.

## Module docstring

Python port of the Batchwise Cashflow report (Laravel PHP).

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

## Module constants

- `_HEADING_FILL = PatternFill("solid", fgColor="2F5496")`
- `_HEADING_FONT = Font(bold=True, color="FFFFFF")`
- `_HEADER_FILL = PatternFill("solid", fgColor="D9E2F3")`
- `_HEADER_FONT = Font(bold=True)`
- `_TOTAL_FILL = PatternFill("solid", fgColor="FFD966")`
- `_TOTAL_FONT = Font(bold=True)`
- `_DATA_FILL = PatternFill("solid", fgColor="F2F6FC")`
- `_THIN_SIDE = Side(style="thin", color="AAAAAA")`
- `_THIN_BORDER = Border(left=_THIN_SIDE, right=_THIN_SIDE, top=_THIN_SIDE, bottom=_THIN_SIDE)`
- `_CURRENCY_FORMAT = '"$"#,##0.0000'`

## Functions (line, name, first docstring line)

- L40 `_sorted_volumes(data)` 
- L44 `batchwise_cashflow_rows(payload, include_proto)` Port of BatchwiseCashflowExportExcelFormula::array(): the literal
- L86 `build_batchwise_cashflow_sheet(wb, payload, ex_inv_row_counts, include_proto)` Port of BatchwiseCashflowExportExcelFormula: writes and styles the
- L195 `_demo()` 
- L107 `write_row(cells)` 
- L114 `style_range(row, fill, font)` 
- L122 `write_section(heading, header, suppliers, formula_builder)` 
- L150 `proto_formulas(supplier_type, r)` 
- L168 `volume_formulas(supplier_type, r, sheet_name, ex_inv_last_row)` 

## Authored formula sites (line: template string; placeholders in braces are Python f-string fields)

- L142: `=SUM(`
- L142: `=SUM({letter}{data_start}:{letter}{data_end})`
- L152: `=SUMIF('Ex Inv VL-proto'!$AE$5:$AE$`
- L152: `=SUMIF('Ex Inv VL-proto'!$AE$5:$AE${proto_last_row},$A{r},'Ex Inv VL-proto'!$AD$5:$AD${proto_last_row})`
- L155: `=$B{r}*IFERROR(NUMBERVALUE(LEFT($A{r},FIND(" ",$A{r}))),0)`
- L169: `=SUMIF('`
- L169: `=SUMIF('{sheet_name}'!$AE$5:$AE${ex_inv_last_row},$A{r},'{sheet_name}'!$Z$5:$Z${ex_inv_last_row})`
- L171: `=SUMIF('`
- L171: `=SUMIF('{sheet_name}'!$AE$5:$AE${ex_inv_last_row},$A{r},'{sheet_name}'!$AD$5:$AD${ex_inv_last_row})`
- L174: `=$B{r}*IFERROR(NUMBERVALUE(LEFT($A{r},FIND(" ",$A{r}))),0)`
- L175: `=$C{r}*IFERROR(NUMBERVALUE(LEFT($A{r},FIND(" ",$A{r}))),0)`
- L246: `=SUMIF('Ex Inv VL-proto'!$AE$5:$AE$300,$A3,'Ex Inv VL-proto'!$AD$5:$AD$300)`
- L247: `=$B3*IFERROR(NUMBERVALUE(LEFT($A3,FIND(" ",$A3))),0)`
- L248: `=SUM(B3:B4)`
- L250: `=SUMIF('Ex Inv VL-1'!$AE$5:$AE$200,$A9,'Ex Inv VL-1'!$Z$5:$Z$200)`
- L251: `=$C9*IFERROR(NUMBERVALUE(LEFT($A9,FIND(" ",$A9))),0)`
- L252: `=SUM(B9:B10)`

## Assembly rules read from code

(see section 'Hand analysis' of 4_generation_logic_overview.md for cross-report rules: IFERROR wrapping, bounded ranges, row anchoring)
