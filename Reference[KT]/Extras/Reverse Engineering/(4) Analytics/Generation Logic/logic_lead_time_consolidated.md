# Generation logic: lead_time_consolidated

Source: GitHub solutionsDigibull/BuLLMQuote_SRIM @ 540918090b1b, mcp-tools/reporting/superset/reports/lead_time_consolidated.py
Method: static read of the module (docstrings, function bodies, constants). Statements labelled INFERENCE are not stated in code.

## Module docstring

Python port of the Lead Time Consolidated report (Laravel PHP).

Three layers, mirroring the PHP pipeline:
  1. lead_time_consolidated_rows() — port of
     BlockthreeController::lead_time_consolidate(): the BOM-wide lead-time
     rollup (no FG grouping, unlike Lead Time (FG Wise)), matching the
     input/output JSON documented in lead-time-consolidated-report.md. This
     is the exact shape persisted to lead_time_cons_json.json_desc.
  2. lead_time_consolidated_sheet_rows() — port of
     LeadTimeConsolidatedExportExcelFormula::array(): header row, one row
     per lead-time bucket (count literal, percentage left for a live
     formula), and a trailing Grand Total row whose count is a live SUM()
     and whose percentage cells are all self-referential IF() formulas
     against the Grand Total's own row — note that row number equals
     len(output) itself (count($output) in PHP), not len(output) - 1, a
     detail that was easy to get wrong (see the .md's "corrected during
     review" note).
  3. build_lead_time_consolidated_sheet() — port of the same class's
     registerEvents(): header/data/Grand-Total row coloring (the Grand Total
     scan stops at the first match, mirroring the PHP's `break`), percentage
     number formatting, borders, and column auto-sizing.

No DB access happens here — bom_details_json_data/rfqs are supplied by the
caller, and the DB write (`lead_time_cons_json` table upsert) in the
original PHP is out of scope, consistent with every other port in this
project.

## Module constants

- `_HEADER_FILL = PatternFill("solid", fgColor="2F5496")`
- `_HEADER_FONT = Font(bold=True, color="FFFFFF")`
- `_HEADER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)`
- `_DATA_FILL = PatternFill("solid", fgColor="F2F6FC")`
- `_DATA_ALIGN = Alignment(vertical="center", wrap_text=True)`
- `_TOTAL_FILL = PatternFill("solid", fgColor="FFD966")`
- `_TOTAL_FONT = Font(bold=True)`
- `_THIN_SIDE = Side(style="thin", color="000000")`
- `_THIN_BORDER = Border(left=_THIN_SIDE, right=_THIN_SIDE, top=_THIN_SIDE, bottom=_THIN_SIDE)`

## Functions (line, name, first docstring line)

- L45 `_natural_key(value)` Mirrors PHP's ksort(..., SORT_NATURAL) for lead-time-week labels.
- L50 `lead_time_consolidated_rows(payload)` Port of BlockthreeController::lead_time_consolidate(): the BOM-wide lead-time rollup.
- L112 `lead_time_consolidated_sheet_rows(rows)` Port of LeadTimeConsolidatedExportExcelFormula::array(): header + data
- L143 `build_lead_time_consolidated_sheet(wb, rows)` Port of LeadTimeConsolidatedExportExcelFormula: writes and styles the
- L190 `_demo()` 

## Authored formula sites (line: template string; placeholders in braces are Python f-string fields)

- L128: `=SUM(B2:B`
- L128: `=SUM(B2:B{grand_total_row_index - 1})`
- L134: `=IF($B$`
- L134: `=IF($B${grand_total_row_index}=0,0,B{excel_row}/$B${grand_total_row_index})`
- L137: `=IF($B$`
- L137: `=IF($B${grand_total_row_index}=0,0,B{grand_total_row_index}/$B${grand_total_row_index})`
- L229: `=SUM(B2:B3)`
- L230: `=IF($B$4=0,0,B4/$B$4)`
- L231: `=IF($B$4=0,0,B2/$B$4)`

## Assembly rules read from code

(see section 'Hand analysis' of 4_generation_logic_overview.md for cross-report rules: IFERROR wrapping, bounded ranges, row anchoring)
