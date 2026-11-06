# Generation logic: part_num_vs_mfg_num

Source: GitHub solutionsDigibull/BuLLMQuote_SRIM @ 540918090b1b, mcp-tools/reporting/superset/reports/part_num_vs_mfg_num.py
Method: static read of the module (docstrings, function bodies, constants). Statements labelled INFERENCE are not stated in code.

## Module docstring

Python port of the Part Num Vs Mfg Num report (Laravel PHP).

Two layers, mirroring the PHP pipeline:
  1. part_num_vs_mfg_num() — port of BlockthreeController::cpnvsmpn_json():
     computes the CPN -> MPN / in-scrub-BOM rows from bom_details_json_data/
     rfqs, matching the input/output JSON documented in
     part-num-vs-mfg-num-report.md.
  2. build_part_num_vs_mfg_num_sheet() — port of app/Exports/BomDetailsExport.php:
     writes a 'Part Num Vs Mfg Num' worksheet from those rows.

No DB access happens here — bom_details_json_data/rfqs are supplied by the
caller, and the DB write (`part_number_vs_mpn` table upsert) in the original
PHP is out of scope, consistent with every other port in this project.

## Module constants

- `HEADER_LABELS = ["Part Number", "MPN", "In Scrub BOM"]`
- `_HEADER_FILL = PatternFill("solid", fgColor="2F5496")`
- `_HEADER_FONT = Font(bold=True, color="FFFFFF")`
- `_HEADER_ALIGN = Alignment(horizontal="center", vertical="center")`
- `_DATA_FILL = PatternFill("solid", fgColor="F2F6FC")`
- `_FALSE_FILL = PatternFill("solid", fgColor="FF0000")`
- `_FALSE_FONT = Font(color="FFFFFF")`
- `_THIN_SIDE = Side(style="thin", color="000000")`
- `_THIN_BORDER = Border(left=_THIN_SIDE, right=_THIN_SIDE, top=_THIN_SIDE, bottom=_THIN_SIDE)`

## Functions (line, name, first docstring line)

- L31 `part_num_vs_mfg_num(payload)` Port of BlockthreeController::cpnvsmpn_json(): CPN -> MPN / in-scrub-BOM rows.
- L88 `build_part_num_vs_mfg_num_sheet(wb, rows)` Port of BomDetailsExport: styles the Part Num Vs Mfg Num rows into a sheet.
- L130 `_demo()` 

## Authored formula sites (line: template string; placeholders in braces are Python f-string fields)


## Assembly rules read from code

(see section 'Hand analysis' of 4_generation_logic_overview.md for cross-report rules: IFERROR wrapping, bounded ranges, row anchoring)
