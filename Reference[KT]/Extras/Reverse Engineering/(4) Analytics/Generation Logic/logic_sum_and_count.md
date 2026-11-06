# Generation logic: sum_and_count

Source: GitHub solutionsDigibull/BuLLMQuote_SRIM @ 540918090b1b, mcp-tools/reporting/superset/reports/sum_and_count.py
Method: static read of the module (docstrings, function bodies, constants). Statements labelled INFERENCE are not stated in code.

## Module docstring

Python port of BlockthreeController::sum_and_count() (Laravel PHP).

Pure transform: takes the upstream JSON payload described in
sum_and_count.md and returns the output payload described there too.

Also includes build_sum_and_count_sheet(), a port of the Laravel
SumAndCountExportExcelFormula export: given that same output payload,
it writes a "Sum & Count" worksheet whose cells hold live Excel
formulas (matching the original) rather than static values. Those
formulas only resolve correctly once opened in Excel alongside a
'Sum & Count Detailed' sheet built the same way (see
sum_and_count_detailed.py) — this module does not evaluate them.

## Module constants

- `_HEADER_FILL = PatternFill("solid", fgColor="2F5496")`
- `_HEADER_FONT = Font(bold=True, color="FFFFFF")`
- `_DATA_FILL = PatternFill("solid", fgColor="F2F6FC")`
- `_DATA_FONT = Font(color="000000")`
- `_MISMATCH_FILL = PatternFill("solid", fgColor="FFFF0000")`

## Functions (line, name, first docstring line)

- L22 `_to_float(value)` Mirror PHP's forgiving (float) cast: non-numeric -> 0.0.
- L30 `sum_and_count(payload)` Per-Assembly rollup of scrub BOM sum/count vs Proto/volume RFQ coverage.
- L98 `_header_meta(headers)` Column metadata (label, index, letter) for non-empty string headers.
- L107 `_resolve_meta(header_meta, candidates)` First header meta matching any candidate label, in candidate order.
- L116 `_collect_volume_columns(header_meta)` Detect 'VL-{n} Sum'/'VL-{n} Count' column pairs from the header.
- L132 `_build_detailed_column_map(volume_columns, include_proto)` Column letters as they appear (positionally) on the Detailed sheet.
- L167 `_detailed_column_range(column_map, candidates, detailed_last_row)` 
- L175 `_consistency_formula(columns_meta, row_number)` =AND(a=b, b=c, ...) chaining consecutive columns on the same row.
- L197 `build_sum_and_count_sheet(wb, rows, detailed_last_row, include_proto)` Port of SumAndCountExportExcelFormula: live-formula 'Sum & Count' sheet.
- L316 `_demo()` 
- L222 `sort_key(row)` 

## Authored formula sites (line: template string; placeholders in braces are Python f-string fields)

- L176: `=AND(a=b, b=c, ...) chaining consecutive columns on the same row.`
- L184: `=AND(`
- L271: `=IFERROR(SUMIFS(`
- L271: `=IFERROR(SUMIFS({value_range}, {assembly_range}, {assembly_cell}), 0)`
- L300: `=NOT(AND($`
- L300: `=NOT(AND(${is_sum_same_meta['column']}2=TRUE, ${is_count_same_meta['column']}2=TRUE))`
- L379: `=IFERROR(SUMIFS('Sum & Count Detailed'!$C$1:$C$50, 'Sum & Count Detailed'!$A$1:$A$50, A2), 0)`
- L385: `=AND(B2=D2, D2=F2, F2=H2)`

## Assembly rules read from code

(see section 'Hand analysis' of 4_generation_logic_overview.md for cross-report rules: IFERROR wrapping, bounded ranges, row anchoring)
