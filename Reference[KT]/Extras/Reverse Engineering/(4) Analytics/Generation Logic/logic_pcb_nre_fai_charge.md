# Generation logic: pcb_nre_fai_charge

Source: GitHub solutionsDigibull/BuLLMQuote_SRIM @ 540918090b1b, mcp-tools/reporting/superset/reports/pcb_nre_fai_charge.py
Method: static read of the module (docstrings, function bodies, constants). Statements labelled INFERENCE are not stated in code.

## Module docstring

Python port of the PCB NRE & FAI Charge report (Laravel PHP).

Two layers, mirroring the PHP pipeline:
  1. fai_charge_rows() — port of BlockthreeController::faiCharge(): the
     per-CPN PCB NRE-charge rollup (header row, one row per costed PCB
     CPN+MPN pair, a placeholder row if none qualify, a trailing total row),
     matching the input/output JSON documented in pcb-nre-fai-charge-report.md.
  2. build_fai_charge_sheet() — port of app/Exports/FaiChargeExportExcelFormula.php:
     writes a 'PCB NRE & FAI Charge' worksheet whose Description/Commodity/
     Mfg Name/Mfg Part Number/NRE-Charge cells (columns B-F, data rows only)
     hold live Excel formulas referencing '7.0 CBOM VL-1' — not the JSON
     values computed by fai_charge_rows() — same live-formula pattern as
     A Class Parts (aclass_parts.py) and CBOM VL (cbom_vl_report.py).

# ponytail: reproduces two shipped quirks verbatim rather than fixing them
# (see pcb-nre-fai-charge-report.md "Cross-check notes"):
#   - Column F is labeled "NRE Charge (Conv.)" but its formula sources CBOM
#     column T ("NRE Charge", raw) instead of column U ("NRE Charge (Conv.)")
#     — the currency conversion CBOM already computed is silently bypassed.
#   - The lookup always targets '7.0 CBOM VL-1' and a fixed row range
#     (27-282), never the dynamic per-volume AK1/AL1 bounds used elsewhere.

No DB access happens here — bom_details_json_data/rfqs are supplied by the
caller, and the DB write (`fai_charge_summary` table upsert) in the original
PHP is out of scope, consistent with every other port in this project.

## Module constants

- `_HEADER_KEYS = ["Part Number", "Description", "Commodity", "Mfg Name", "Mfg Part Number", "NRE Charge (Conv.)"]`
- `_CBOM_SHEET = "7.0 CBOM VL-1"`
- `_CBOM_ROW_START = 27`
- `_CBOM_ROW_END = 282`
- `_FORMULA_COLUMNS = {     "B": ("D", True),     "C": ("E", True),     "D": ("F", True),     "E": ("G", True),     "F": ("T", False), }`
- `_HEADER_FILL = PatternFill("solid", fgColor="2F5496")`
- `_HEADER_FONT = Font(bold=True, color="FFFFFF")`
- `_DATA_FILL = PatternFill("solid", fgColor="F2F6FC")`
- `_TOTAL_FILL = PatternFill("solid", fgColor="FFD966")`
- `_TOTAL_FONT = Font(bold=True)`
- `_THIN_SIDE = Side(style="thin", color="000000")`
- `_THIN_BORDER = Border(left=_THIN_SIDE, right=_THIN_SIDE, top=_THIN_SIDE, bottom=_THIN_SIDE)`

## Functions (line, name, first docstring line)

- L57 `fai_charge_rows(payload)` Port of BlockthreeController::faiCharge(): the PCB NRE/FAI charge rollup.
- L138 `_lookup_formula(cbom_col, part_cell, coerce_text)` 
- L150 `build_fai_charge_sheet(wb, rows)` Port of FaiChargeExportExcelFormula: writes and styles the 'PCB NRE & FAI Charge' sheet.
- L204 `_demo()` 

## Authored formula sites (line: template string; placeholders in braces are Python f-string fields)

- L147: `="","",IFERROR(`
- L147: `=IF(`
- L147: `=IF({part_cell}="","",IFERROR({value_expr},""))`
- L246: `=IF($A2="","",IFERROR(INDEX('7.0 CBOM VL-1'!$D$27:$D$282`

## Assembly rules read from code

(see section 'Hand analysis' of 4_generation_logic_overview.md for cross-report rules: IFERROR wrapping, bounded ranges, row anchoring)
