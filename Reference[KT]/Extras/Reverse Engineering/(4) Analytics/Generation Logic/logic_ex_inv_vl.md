# Generation logic: ex_inv_vl

Source: GitHub solutionsDigibull/BuLLMQuote_SRIM @ 540918090b1b, mcp-tools/reporting/superset/reports/ex_inv_vl.py
Method: static read of the module (docstrings, function bodies, constants). Statements labelled INFERENCE are not stated in code.

## Module docstring

Python port of the Ex Inv VL report (Laravel PHP).

Two layers, mirroring the PHP pipeline:
  1. ex_inv_vl_rows() — port of ExcessInventoryVolumeSheetExcelFormula::array():
     builds the literal 2D row layout for one volume (or 'proto'). Unlike
     most ports in this project, nearly every cell besides Part Number and
     Excess In Stk IS an Excel formula string referencing the matching
     '7.0 CBOM VL-{volume}' sheet — that's this report's actual output
     contract (see ex-inv-vl-report.md), not a value to precompute, so the
     formulas are reproduced verbatim rather than skipped.
  2. build_ex_inv_vl_sheet() — port of the same class's registerEvents():
     sheet title, special cells (A1 label, A2/summary-row totals, merged
     V3:Z3 super-header), the previous-volume AH/AI delta formulas, the
     CBOM-bounds AK1/AL1 formulas, and static styling.

Both known bugs in the shipped PHP are reproduced as-is rather than fixed
(see ex-inv-vl-report.md "Cross-check notes"):
  - A1 is always literally "Excess Cost #1", even on volume 2/3/proto sheets.
  - Volume 1's AH/AI delta formulas always reference a sheet named
    'Ex Inv VL-proto', even if the proto sheet was excluded from the
    workbook (BomDetail.proto <= 0) — a latent #REF! source.

# ponytail: PHP's colAHSource/colAISource ternaries (`$suffix == '1' ? 'O' :
# 'O'`) always resolve to the same value on both branches — reproduced here
# as the plain literals 'O'/'T', skipping the dead conditional.

No DB access happens here — the CPN/volumes payload is supplied by the caller.

v2 source schema notes:
  - `excess_in_stk` is confirmed sourced from `scrub_bom_items.inventory_stock`
    (previously undetermined) -- no code change needed here, this file only
    ever consumed the `matched.get("excess_in_stk", ...)` dict key; only the
    loader that builds `json_data` needs to populate it from that column.
  - "Ordering qty" (row 134, the `W{r}` formula) already implements the
    finalized business logic exactly:
    `=IF(V{r}=0,0,IFERROR(ROUNDUP(MAX(V{r},T{r})/S{r},0)*S{r},0))`
    where V=Partial quantity (Required Quantity), T=MOQ (Minimum Order
    Quantity), S=Pkg Qty (Order Multiple). No code change was needed -- this
    was a gap in an earlier summary doc's write-up, not in this file.
  - "New Supp" (the `AL` INDEX lookup a few lines below) is PENDING CLIENT
    CLARIFICATION: does it hold an alternate supplier name, or a boolean
    "supplier changed" flag? Left exactly as ported (an `INDEX` lookup against
    CBOM's own "New Supp" column) rather than guessed at -- see
    cbom-pending-client-clarifications.md.

## Module constants

- `_HEADER_FILL = PatternFill("solid", fgColor="2F5496")`
- `_HEADER_FONT = Font(bold=True, color="FFFFFF")`
- `_DATA_FILL = PatternFill("solid", fgColor="F2F6FC")`
- `_YELLOW_FILL = PatternFill("solid", fgColor="FFD966")`
- `_THIN_SIDE = Side(style="thin", color="000000")`
- `_THIN_BORDER = Border(left=_THIN_SIDE, right=_THIN_SIDE, top=_THIN_SIDE, bottom=_THIN_SIDE)`
- `_CURRENCY_FORMAT = '"$"#,##0.0000'`

## Functions (line, name, first docstring line)

- L58 `_suffix(volume)` 
- L62 `_cbom_sheet_name(volume)` 
- L66 `_sheet_title(volume)` 
- L70 `_headers(suffix)` 
- L90 `_get_numeric(val)` 
- L94 `_find_volume(volumes, volume)` 
- L101 `_bounded(cbom_sheet, col)` 
- L105 `_index_lookup(cbom_sheet, col, row, coerce_text)` 
- L120 `_sumifs_lookup(cbom_sheet, value_col, pn_cell)` 
- L127 `_match_helper_formula(cbom_sheet, pn_cell)` 
- L140 `_data_row(cpn_entry, matched, current_row, cbom_sheet)` 
- L184 `ex_inv_vl_rows(json_data, volume)` Port of ExcessInventoryVolumeSheetExcelFormula::array(): the full sheet rows.
- L206 `build_ex_inv_vl_sheet(wb, json_data, volume, cbom_bounds, has_proto, expected_row_count)` Port of ExcessInventoryVolumeSheetExcelFormula: writes and styles an 'Ex Inv VL-n' sheet.
- L333 `_demo()` 

## Authored formula sites (line: template string; placeholders in braces are Python f-string fields)

- L116: `=IFERROR(`
- L116: `=IFERROR({inner},{fallback})`
- L122: `=SUMIFS(`
- L122: `=SUMIFS({_bounded(cbom_sheet, value_col)}, {_bounded(cbom_sheet, 'C')}, {pn_cell}, {_bounded(cbom_sheet, 'AH')}, "<>TRUE")`
- L137: `=IFERROR(`
- L137: `=IFERROR({inner},"")`
- L153: `=MAX(H`
- L153: `=MAX(H{r}-G{r},0)`
- L154: `=MAX(G`
- L154: `=MAX(G{r}-H{r},0)`
- L156: `=IF(INT(F`
- L156: `=IF(INT(F{r})=F{r}, ROUNDUP(J{r}*(1+K{r}),0), J{r}*(1+K{r}))`
- L158: `=IF(INT(F`
- L158: `=IF(INT(F{r})=F{r}, ROUNDUP(M{r}*(1+K{r}),0), M{r}*(1+K{r}))`
- L160: `=IFERROR(O`
- L160: `=IFERROR(O{r}*G{r},0)`
- L166: `=IF(AND(T`
- L166: `=IF(AND(T{r}<>"",T{r}>0), MAX(N{r}-H{r},0), 0)`
- L167: `=0,0,IFERROR(ROUNDUP(MAX(V`
- L167: `=IF(V`
- L167: `=IF(V{r}=0,0,IFERROR(ROUNDUP(MAX(V{r},T{r})/S{r},0)*S{r},0))`
- L168: `=IF(AND(T`
- L168: `=IF(AND(T{r}<>"",T{r}>0), H{r}+W{r}-N{r}, 0)`
- L169: `=IFERROR(X`
- L169: `=IFERROR(X{r}*O{r},0)`
- L170: `=IFERROR(W`
- L170: `=IFERROR(W{r}*O{r},0)`
- L171: `=IFERROR(IF(L`
- L171: `=IFERROR(IF(L{r}<=T{r},T{r},ROUNDUP(L{r}/S{r},0)*S{r}),0)`
- L172: `=MAX(AA`
- L172: `=MAX(AA{r}+I{r}-L{r},0)`
- L173: `=IFERROR(AB`
- L173: `=IFERROR(AB{r}*O{r},0)`
- L174: `=IFERROR(AA`
- L174: `=IFERROR(AA{r}*O{r},0)`
- L177: `=S{r}<=T{r}`
- L273: `=SUM(AC`
- L273: `=SUM(AC{data_start_row}:AC{last_data_row})`
- L293: `=IFERROR(ABS(INDEX('`
- L293: `=IFERROR(ABS(INDEX('{previous_title}'!O$5:O$1029, MATCH('{title}'!{cpn_cell}, '{previous_title}'!$A$5:$A$1029, 0)) - '{title}'!O{r}),0)`
- L297: `=IFERROR(INDEX('`
- L297: `=IFERROR(INDEX('{previous_title}'!T$5:T$1029, MATCH('{title}'!{cpn_cell}, '{previous_title}'!$A$5:$A$1029, 0)) - '{title}'!T{r},0)`
- L314: `=SUM(`
- L314: `=SUM({col_letter}{data_start_row}:{col_letter}{last_data_row})`
- L377: `=IFERROR(INDEX(`
- L378: `=MAX(H5-G5,0)`
- L380: `=IFERROR(MATCH(1,`
- L399: `=IFERROR(ABS(INDEX('Ex Inv VL-proto'!`
- L408: `=IFERROR(ABS(INDEX('Ex Inv VL-1'!`

## Assembly rules read from code

(see section 'Hand analysis' of 4_generation_logic_overview.md for cross-report rules: IFERROR wrapping, bounded ranges, row anchoring)
