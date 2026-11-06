# Generation logic: revision_history

Source: GitHub solutionsDigibull/BuLLMQuote_SRIM @ 540918090b1b, mcp-tools/reporting/superset/reports/revision_history.py
Method: static read of the module (docstrings, function bodies, constants). Statements labelled INFERENCE are not stated in code.

## Module docstring

Python port of the Revision History report (Laravel PHP).

Two layers, mirroring the PHP pipeline:
  1. revision_history_rows() — port of BlockthreeController::revision_history_json():
     computes the literal top-header/sub-header/data rows (Old vs. New
     revision comparison per CPN, per volume), matching the input/output
     JSON documented in revision-history-report.md. This is the exact shape
     persisted to revision_history_json.json_desc.
  2. build_revision_history_sheet() — port of app/Exports/RevisionHistoryExportExcelFormula.php:
     restructures the columns (moves the single input-level "EAU" column
     into a "V{n} EAU" column per volume), then overwrites every "New"-labeled
     and fixed-identity cell with a live formula referencing '7.0 CBOM VL-{v}'
     / 'Ex Inv VL-{v}' — same live-formula pattern as A Class Parts, CBOM VL,
     Ex Inv VL, PCB NRE & FAI Charge, and Mech & EM NRE. "OLD"-labeled cells
     and "In %" are left exactly as the literal values from step 1.

# ponytail: the shipped PHP inserts each "V{n} EAU" column into an
# already-written sheet (removing the old EAU column, then
# insertNewColumnBefore() one at a time, processed in descending
# qty-column order specifically to avoid shifting not-yet-processed insertion
# points). Since this port builds the final column layout directly instead of
# mutating a live sheet, that ordering dance — and the PHP's follow-up
# "rescan for the last Delta column" workaround needed because insertion left
# ambiguous trailing columns — aren't needed: the clean layout already ends
# each block at an unambiguous boundary.

# BUG FIXED (previously preserved as-is to match the shipped PHP, confirmed
# against a real generated workbook showing visible #VALUE! errors in "New
# System Price" cells): unlike every other injected formula, "New System
# Price" (= NewQtyCell * NewUnitPriceCell) had NO IFERROR wrapper in the
# shipped PHP (RevisionHistoryExportExcelFormula.php line 543). Qty/Unit
# Price both fall back to "" via their own IFERROR when the CPN isn't found
# on the Ex Inv/CBOM sheets, and "" * "" (or number * "") is a genuine
# #VALUE! error in Excel — visible directly in the cell, not suppressed.
# "Delta" already came out blank rather than erroring, since its own formula
# IS wrapped in IFERROR and caught the propagated error from a "New System
# Price" cell that was #VALUE! — now it just catches the ordinary "" case
# instead. Per this project's hard requirement that no generated formula may
# ever show #VALUE! on blank/null/non-numeric input, "New System Price" is
# now IFERROR-wrapped like every other injected formula, deviating from PHP
# parity on this one cell deliberately.

No DB access happens here — bom_data/rfqs are supplied by the caller, and
the DB write (`revision_history_json` table upsert) in the original PHP is
out of scope, consistent with every other port in this project.

v2 source schema note: today's `quote_win` table stores only the latest
quote per part -- no revision dimension at all, so this report's Old-vs-New
comparison cannot be produced from it. See
cbom-revision-history-redesign.md for the full design; the short version is
`rfqs_from_quote_win_revision()` below, which adapts a dedicated
`quote_win_revision` table (one row per revision) into the same 'rfqs' shape
revision_history_rows() already expects -- so the core function needs no
changes once real revision data exists. That adapter carries explicit,
flagged assumptions (see i

## Module constants

- `_VOLUME_HEADER_COLORS = {1: "74B2E6", 2: "F56767", 3: "75D975", 4: "AD92F8", 5: "FFE06D"}`
- `_VOLUME_DATA_COLORS = {1: "D9EAF7", 2: "FDE2E2", 3: "E2F7E2", 4: "E9E2FD", 5: "FFF7D9"}`
- `_HEADER_FILL = PatternFill("solid", fgColor="2F5496")`
- `_HEADER_FONT = Font(bold=True, color="FFFFFF")`
- `_FIXED_DATA_FILL = PatternFill("solid", fgColor="F2F6FC")`
- `_CENTER = Alignment(horizontal="center", vertical="center")`

## Functions (line, name, first docstring line)

- L70 `rfqs_from_quote_win_revision(revision_rows, commodity_by_cpn, volume_no)` v2 schema adapter: reshapes `quote_win_revision` rows (see
- L118 `_natural_key(value)` 
- L122 `revision_history_rows(payload)` Port of BlockthreeController::revision_history_json(): Old-vs-New revision rollup.
- L258 `_final_sub_headers(max_volume)` 
- L270 `_final_top_headers(max_volume)` 
- L279 `_remap_data_row(orig_row, max_volume)` Drops the standalone EAU value; makes room for a per-volume EAU cell
- L295 `_cbom_range(v, col, cbom_bounds)` cbom_bounds: (first_data_row, last_data_row) for '7.0 CBOM VL-{v}', computed
- L309 `_identity_formula(v, target_col, asm_cell, cpn_cell, cbom_bounds)` 
- L319 `_qty_eau_formula(v, cpn_cell, ex_inv_last_row)` 
- L327 `_unit_price_formula(v, asm_cell, cpn_cell, cbom_bounds)` 
- L337 `_volume_for_header(sub_headers, col_index)` Returns the volume number a column belongs to, for coloring purposes.
- L356 `build_revision_history_sheet(wb, rows, cbom_bounds_by_volume, ex_inv_row_counts)` Port of RevisionHistoryExportExcelFormula: writes and styles the
- L477 `_demo()` 

## Authored formula sites (line: template string; placeholders in braces are Python f-string fields)

- L316: `=IFERROR(`
- L316: `=IFERROR({base}, IFERROR({fallback}, ""))`
- L322: `=IFERROR(SUMIFS('`
- L322: `=IFERROR(SUMIFS('{sheet}'!$G$5:$G${ex_inv_last_row}, '{sheet}'!$A$5:$A${ex_inv_last_row}, {cpn_cell}), "")`
- L334: `=IFERROR(`
- L334: `=IFERROR({base}, IFERROR({fallback}, ""))`
- L464: `=IFERROR(`
- L464: `=IFERROR({new_qty_cell}*{new_unit_cell}, "")`
- L471: `=IFERROR(`
- L471: `=IFERROR({new_sys_cell}-VALUE(SUBSTITUTE(SUBSTITUTE({old_sys_cell},"$",""),",","")),"")`
- L548: `=IFERROR(INDEX(`
- L565: `=IFERROR(`
- L567: `=IFERROR(`

## Assembly rules read from code

(see section 'Hand analysis' of 4_generation_logic_overview.md for cross-report rules: IFERROR wrapping, bounded ranges, row anchoring)
