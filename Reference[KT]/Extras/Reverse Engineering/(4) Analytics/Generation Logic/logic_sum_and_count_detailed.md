# Generation logic: sum_and_count_detailed

Source: GitHub solutionsDigibull/BuLLMQuote_SRIM @ 540918090b1b, mcp-tools/reporting/superset/reports/sum_and_count_detailed.py
Method: static read of the module (docstrings, function bodies, constants). Statements labelled INFERENCE are not stated in code.

## Module docstring

Python port of BlockthreeController::sum_and_count_detail() (Laravel PHP).

Pure transform: takes the upstream JSON payload described in
sum_and_count_detailed.md and returns the output payload described there too.

Also includes build_sum_and_count_detailed_sheet(), a port of the Laravel
SumAndCountDetailedExportExcelFormula export: given that same output
payload, it writes a "Sum & Count Detailed" worksheet whose cells hold
live Excel formulas (matching the original) rather than static values.
Those formulas look up raw CBOM sheets ('7.0 CBOM Proto', '7.0 CBOM
VL-{n}') that must exist elsewhere in the same workbook — this module
does not evaluate them.

## Module constants

- `_START_ROW_REF = "$AL$1"`
- `_END_ROW_REF = "$AK$1"`
- `_HEADER_FILL = PatternFill("solid", fgColor="2F5496")`
- `_HEADER_FONT = Font(bold=True, color="FFFFFF")`
- `_DATA_FILL = PatternFill("solid", fgColor="F2F6FC")`
- `_DATA_FONT = Font(color="000000")`
- `_MISMATCH_FILL = PatternFill("solid", fgColor="FFFF0000")`

## Functions (line, name, first docstring line)

- L22 `_to_float(value)` Mirror PHP's forgiving (float) cast: non-numeric -> 0.0.
- L30 `sum_and_count_detail(payload)` Per-Assembly + CPN breakdown.
- L94 `_header_meta(headers)` Column metadata (label, index, letter) for non-empty string headers.
- L103 `_resolve_meta(header_meta, candidates)` First header meta matching any candidate label, in candidate order.
- L112 `_sheet_name_for_volume(label)` 
- L119 `_collect_volume_columns(header_meta)` Detect 'VL-{n} Sum'/'VL-{n} Count' column pairs and their raw sheet.
- L136 `_consistency_formula(columns_meta, row_number)` =AND(a=b, b=c, ...) chaining consecutive columns on the same row.
- L148 `_quote_sheet(name)` 
- L165 `_bounded_range(sheet_name, column_letter)` Dynamic range on a raw CBOM sheet, bounded by the shared AL1/AK1 helper cells.
- L174 `_average_formula(sheet_name, assembly_meta, part_meta, row_number)` 
- L186 `_count_formula(sheet_name, assembly_meta, part_meta, row_number)` 
- L195 `build_sum_and_count_detailed_sheet(wb, rows, cbom_bounds, include_proto)` Port of SumAndCountDetailedExportExcelFormula: live-formula sheet.
- L324 `_demo()` 
- L224 `sort_key(row)` 

## Authored formula sites (line: template string; placeholders in braces are Python f-string fields)

- L137: `=AND(a=b, b=c, ...) chaining consecutive columns on the same row.`
- L145: `=AND(`
- L181: `=IFERROR(AVERAGEIFS(`
- L181: `=IFERROR(AVERAGEIFS({avg_range}, {assembly_range}, {assembly_cell}, {part_range}, {part_cell}), 0)`
- L192: `=IF(SUM(INDEX(`
- L192: `=IF(SUM(INDEX({criteria}, 0, 1)) > 0, 1, 0)`
- L302: `=NOT(AND($`
- L302: `=NOT(AND(${is_sum_same_meta['column']}2=TRUE, ${is_count_same_meta['column']}2=TRUE))`
- L395: `=IFERROR(AVERAGEIFS(INDEX('7.0 CBOM Proto'!$I:$I, $AL$1):INDEX('7.0 CBOM Proto'!$I:$I, $AK$1), INDEX('7.0 CBOM Proto'!$B:$B, $AL$1):INDEX('7.0 CBOM Proto'!$B:$B, $AK$1), A2, INDEX('7.0 CBOM Proto'!$C:$C, $AL$1):INDEX('7.0 CBOM Proto'!$C:$C, $AK$1), B2), 0)`

## Assembly rules read from code

(see section 'Hand analysis' of 4_generation_logic_overview.md for cross-report rules: IFERROR wrapping, bounded ranges, row anchoring)
