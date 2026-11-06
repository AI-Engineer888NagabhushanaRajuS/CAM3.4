# Generation logic: mech_em_nre

Source: GitHub solutionsDigibull/BuLLMQuote_SRIM @ 540918090b1b, mcp-tools/reporting/superset/reports/mech_em_nre.py
Method: static read of the module (docstrings, function bodies, constants). Statements labelled INFERENCE are not stated in code.

## Module docstring

Python port of the Mech & EM NRE report (Laravel PHP).

Two layers, mirroring the PHP pipeline:
  1. mech_em_nre_rows() — port of BlockthreeController::nrecharge(): the
     per-CPN Mechanical/Electromechanical NRE-charge rollup, matching the
     input/output JSON documented in mech-em-nre-report.md. This is the exact
     shape persisted to nre_charge_data.json_desc and the only shape
     NreChargeExportExcelFormula::array() actually consumes correctly (see
     the "Cross-check notes" in the .md for two call sites that get this
     wrong by pre-formatting the data before handing it to that class).
  2. build_mech_em_nre_sheet() — port of app/Exports/NreChargeExportExcelFormula.php:
     writes a 'Mech & EM NRE' worksheet — grand-total row first, header row
     second, data rows third — whose Description/Commodity/Mfg Name/Mfg Part
     Number/NRE-Charge cells (columns B-F, data rows only) hold live Excel
     formulas referencing '7.0 CBOM VL-1', same live-formula pattern as
     PCB NRE & FAI Charge (pcb_nre_fai_charge_report.py).

# ponytail: reproduces two shipped quirks verbatim rather than fixing them
# (see mech-em-nre-report.md "Cross-check notes"):
#   - Column F is labeled "NRE Charge (Conv.)" but its formula sources CBOM
#     column T ("NRE Charge", raw) instead of column U ("NRE Charge (Conv.)")
#     — identical bug to the PCB NRE & FAI Charge report.
#   - The lookup always targets '7.0 CBOM VL-1' and a fixed row range
#     (27-282), never the dynamic per-volume AK1/AL1 bounds used elsewhere.

No DB access happens here — bom_details_json_data/rfqs are supplied by the
caller, and the DB write (`nre_charge_data` table upsert) in the original PHP
is out of scope, consistent with every other port in this project.

## Module constants

- `_HEADER = ["Part Number", "Description", "Commodity", "Mfg Name", "Mfg Part Number", "NRE Charge (Conv.)"]`
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

- L59 `mech_em_nre_rows(payload)` Port of BlockthreeController::nrecharge(): the Mechanical/EM NRE charge rollup.
- L124 `mech_em_nre_sheet_rows(rows)` Port of NreChargeExportExcelFormula::array(): grand-total row first,
- L143 `_lookup_formula(cbom_col, part_cell, coerce_text)` 
- L155 `build_mech_em_nre_sheet(wb, rows)` Port of NreChargeExportExcelFormula: writes and styles the 'Mech & EM NRE' sheet.
- L195 `_demo()` 

## Authored formula sites (line: template string; placeholders in braces are Python f-string fields)

- L152: `="","",IFERROR(`
- L152: `=IF(`
- L152: `=IF({part_cell}="","",IFERROR({value_expr},""))`
- L239: `=IF($A3="","",IFERROR(INDEX('7.0 CBOM VL-1'!$D$27:$D$282`

## Assembly rules read from code

(see section 'Hand analysis' of 4_generation_logic_overview.md for cross-report rules: IFERROR wrapping, bounded ranges, row anchoring)
