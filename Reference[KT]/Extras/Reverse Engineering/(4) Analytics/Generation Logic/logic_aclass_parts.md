# Generation logic: aclass_parts

Source: GitHub solutionsDigibull/BuLLMQuote_SRIM @ 540918090b1b, mcp-tools/reporting/superset/reports/aclass_parts.py
Method: static read of the module (docstrings, function bodies, constants). Statements labelled INFERENCE are not stated in code.

## Module docstring

Python port of the A Class Parts report (Laravel PHP).

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

## Module constants

- `HEADER_LABELS = [     "Part Number", "Description", "Commodity", "Mfg Name", "Mfg Part Number", "Part Qty",     "Ext Vol (Splits) #1", "Cost #1", "Ext Price (Splits) #1 (Conv.)", "X",     "Ext Vol Cos`
- `_CBOM_SHEET = "7.0 CBOM VL-1"`
- `_START_ROW_REF = "$AL$1"`
- `_END_ROW_REF = "$AK$1"`
- `_YELLOW_FILL = PatternFill("solid", fgColor="FFD966")`
- `_HEADER_FILL = PatternFill("solid", fgColor="2F5496")`
- `_HEADER_FONT = Font(bold=True, color="FFFFFF")`
- `_DATA_FILL = PatternFill("solid", fgColor="F2F6FC")`
- `_DATA_FONT = Font(color="000000")`
- `_THIN_SIDE = Side(style="thin", color="000000")`
- `_THIN_BORDER = Border(left=_THIN_SIDE, right=_THIN_SIDE, top=_THIN_SIDE, bottom=_THIN_SIDE)`

## Functions (line, name, first docstring line)

- L29 `_is_numeric(value)` 
- L43 `_coalesce(d, key, default)` Mirrors PHP's `$d->key ?? $default`: null/missing -> default, falsy-but-set values pass through.
- L51 `aclass_parts(payload)` Port of BlockthreeController::aclass_json(): per-CPN ABC cost rollup.
- L182 `_bounded_range(column_letter)` 
- L190 `_match_expression(part_number_cell)` 
- L197 `_index_formula(column_letter, match_expression, coerce_text)` Wrapped in IFERROR(..., "-") -- when match_expression's MATCH() can't find the part
- L209 `_sumifs_formula(value_column_letter, part_number_cell)` 
- L216 `build_aclass_parts_sheet(wb, rows, cbom_bounds)` Port of PartsDetailsExportExcelFormula: live-formula 'A CLASS PARTS' sheet.
- L386 `_demo()` 

## Authored formula sites (line: template string; placeholders in braces are Python f-string fields)

- L206: `=IFERROR(`
- L206: `=IFERROR({inner},"-")`
- L211: `=SUMIFS(`
- L211: `=SUMIFS({_bounded_range(value_column_letter)}, {_bounded_range('C')}, {part_number_cell}, {_bounded_range('AH')}, "<>TRUE")`
- L256: `=" $ "&TEXT(SUM($`
- L256: `=" $ "&TEXT(SUM(${ext_price_letter}${data_start_row}:${ext_price_letter}${data_end_row}),"0.00")`
- L259: `=" $ "&TEXT(SUM($`
- L259: `=" $ "&TEXT(SUM(${ext_vol_cost_letter}${data_start_row}:${ext_vol_cost_letter}${data_end_row}),"0.00")`
- L268: `=ROUND(SUM($`
- L268: `=ROUND(SUM(${avg_moq_letter}${data_start_row}:${avg_moq_letter}${data_end_row})/SUM(${ext_vol_cost_letter}${data_start_row}:${ext_vol_cost_letter}${data_end_row}),6)`
- L311: `=IFERROR(IF(`
- L311: `=IFERROR(IF({flag_condition},{cost_value},0),0)`
- L313: `=IFERROR(`
- L313: `=IFERROR({part_qty_cell}*{cost_cell},0)`
- L323: `=IFERROR(`
- L323: `=IFERROR({ext_price_cell}/SUM(${ext_price_letter}${data_start_row}:${ext_price_letter}${data_end_row}),0)`
- L327: `=IFERROR(`
- L327: `=IFERROR({cost_cell}*{ext_vol_cell},0)`
- L339: `=IFERROR(`
- L339: `=IFERROR({ext_vol_cell}/{moq_cell},"-")`
- L341: `=IFERROR(`
- L341: `=IFERROR({ext_vol_cost_cell}*{moq_turns_cell},"-")`

## Assembly rules read from code

(see section 'Hand analysis' of 4_generation_logic_overview.md for cross-report rules: IFERROR wrapping, bounded ranges, row anchoring)
