# Generation logic: lead_time_fg

Source: GitHub solutionsDigibull/BuLLMQuote_SRIM @ 540918090b1b, mcp-tools/reporting/superset/reports/lead_time_fg.py
Method: static read of the module (docstrings, function bodies, constants). Statements labelled INFERENCE are not stated in code.

## Module docstring

Python port of the Lead Time (FG Wise) report (Laravel PHP).

Three layers, mirroring the PHP pipeline:
  1. lead_time_fg_blocks() — port of BlockthreeController::lead_time_fg():
     computes the per-FG lead-time buckets from bom_details_json_data/rfqs,
     matching the input/output JSON documented in lead-time-fg-wise-report.md.
     This is the exact shape persisted to lead_time_fg.json_desc and the only
     shape app/Exports/FgLeadTimeExport.php's array() actually consumes
     correctly — three other call sites in the PHP codebase build differently
     -shaped data for that class and are broken as a result (see the .md's
     "Cross-check notes"); this port follows the one working shape.
  2. flatten_lead_time_fg() — port of FgLeadTimeExport::array()'s own
     dedup-by-FG + horizontal-merge logic: turns the per-FG blocks into the
     flat 2D array actually written to the sheet (one 2-column {LT, Count}
     table per FG, side by side, padded to a common row count).
  3. build_lead_time_fg_sheet() — port of FgLeadTimeExport::styles(): colors
     each 3-column group (2 data columns + 1 spacer) independently, scanning
     for that FG's own last non-blank row rather than the shared padded
     height.

No DB access happens here — bom_details_json_data/rfqs are supplied by the
caller, and the DB write (`lead_time_fg` table upsert) in the original PHP is
out of scope, consistent with every other port in this project.

## Module constants

- `_HEADER_FILL = PatternFill("solid", fgColor="2F5496")`
- `_HEADER_FONT = Font(bold=True, color="FFFFFF")`
- `_DATA_FILL = PatternFill("solid", fgColor="F2F6FC")`
- `_TOTAL_FILL = PatternFill("solid", fgColor="FFD966")`
- `_TOTAL_FONT = Font(bold=True)`
- `_THIN_SIDE = Side(style="thin", color="000000")`
- `_THIN_BORDER = Border(left=_THIN_SIDE, right=_THIN_SIDE, top=_THIN_SIDE, bottom=_THIN_SIDE)`

## Functions (line, name, first docstring line)

- L39 `_natural_key(value)` Mirrors PHP's ksort(..., SORT_NATURAL) for lead-time-week labels.
- L44 `lead_time_fg_blocks(payload)` Port of BlockthreeController::lead_time_fg(): per-FG lead-time buckets.
- L112 `flatten_lead_time_fg(blocks)` Port of FgLeadTimeExport::array(): dedupe FGs, build one 2-col table
- L150 `build_lead_time_fg_sheet(wb, rows)` Port of FgLeadTimeExport::styles(): colors each 3-column group
- L203 `_demo()` 
- L164 `cell_str(r, c)` 

## Authored formula sites (line: template string; placeholders in braces are Python f-string fields)


## Assembly rules read from code

(see section 'Hand analysis' of 4_generation_logic_overview.md for cross-report rules: IFERROR wrapping, bounded ranges, row anchoring)
