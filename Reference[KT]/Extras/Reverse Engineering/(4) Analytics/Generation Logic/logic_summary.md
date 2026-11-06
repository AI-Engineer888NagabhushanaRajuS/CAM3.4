# Generation logic: summary

Source: GitHub solutionsDigibull/BuLLMQuote_SRIM @ 540918090b1b, mcp-tools/reporting/superset/reports/summary.py
Method: static read of the module (docstrings, function bodies, constants). Statements labelled INFERENCE are not stated in code.

## Module docstring

Python port of the Summary report (Laravel PHP), live-pipeline version.

Two layers, mirroring the live PHP pipeline:
  1. summary() — port of Tab8Context + Tab8Computer::computeRevisionPartial() +
     Tab8Merger::mergeAndPersist(), collapsed into a single non-chunked pass
     (the original splits CPNs into chunks of 200 for parallel queue processing
     purely for performance; a single Python process can compute the whole
     revision in one pass with mathematically identical results — chunking then
     merging is associative/commutative with computing the full set directly).
     Matches the input/output JSON documented in summary.md.
  2. build_summary_sheet() — port of app/Exports/SummaryExportExcelFormula.php:
     writes a 'Summary' worksheet whose last-revision cells hold live formulas
     referencing '7.0 CBOM VL-{n}'/'Ex Inv VL-{n}' sheets, rather than the
     static JSON values.

No DB access happens here — bom_data/rfqs/fgcounts/proto_qty/centum_id are
supplied by the caller, and the DB write (`summary_json` table upsert) in the
original PHP is out of scope, consistent with every other port in this project.

v2 source schema notes:
  - No `fgcounts` table in the finalized DB -- the FG-level volume-quantity
    multiplier now lives in the `volume` table (fg, volume_name, batch_qty --
    that column is Volume Qty/EAU despite its name, see
    cbom-database-schema-design.md). summary()'s own logic is unchanged; use
    fgcounts_from_volume_rows() (same adapter as price_control.py) to reshape
    `volume` rows before calling summary().
  - `quote_win` (the flat, current-quote-only table) has no revision_no
    column at all. summary()'s existing fallback -- `rev = 0 if
    r.get("revision_no") is None else int(...)` -- already degrades
    correctly: feed it rfqs rows with no `revision_no` key and it produces
    exactly one revision block (revision_no=0) instead of erroring or
    guessing. No code change was needed here for that gap; once a real
    revision-tracked source exists (see cbom-revision-history-redesign.md),
    populating `revision_no` on the adapted rows is enough to get multiple
    revision blocks back, again with no change to this function.

## Module constants

- `_THIN_SIDE = Side(style="thin", color="000000")`
- `_THICK_SIDE = Side(style="thick", color="000000")`
- `_CENTER = Alignment(horizontal="center")`

## Functions (line, name, first docstring line)

- L49 `fgcounts_from_volume_rows(volume_rows)` v2 schema adapter: `volume` table rows (fg, volume_name, batch_qty) ->
- L65 `_is_numeric(value)` 
- L79 `_price_conv(price, currency)` 
- L83 `_scrap_percent(price_conv)` Scrap percentage for this MOQ-cost calculation's own unit price -- sourced from
- L104 `_first_where_volume(entries, vol_no)` vol_no=None means 'proto'. Falls back to entries[0] if nothing matches
- L116 `summary(payload)` Port of the live Tab 8 pipeline (Tab8Context + Tab8Computer + Tab8Merger).
- L193 `_compute_revision(rev, rfq_by_cpn_rev, by_cpn, inv_by_cpn, part_qty_by_key, rfq_by_cpn_vol, volume_nos, fg_vol_count, centum_id, proto_qty_global)` 
- L349 `_filter_proto(revisions)` Port of SummaryExportExcelFormula::filterJsonData(): strips 'proto' volume rows.
- L370 `_fill(rgb)` 
- L374 `_style_range(ws, col1, row1, col2, row2, fill, font, alignment)` 
- L386 `_border_all(ws, col1, row1, col2, row2, side)` 
- L393 `_border_outline(ws, col1, row1, col2, row2, side)` 
- L406 `build_summary_sheet(wb, revisions, cbom_row_counts, include_proto, now)` Port of SummaryExportExcelFormula: live-formula 'Summary' sheet.
- L642 `_demo()` 

## Authored formula sites (line: template string; placeholders in braces are Python f-string fields)

- L567: `=IFERROR(INDEX('`
- L567: `=IFERROR(INDEX('{cbom_sheet}'!$F$1:$F${cbom_last_row}, MATCH(Summary!$C{r}, '{cbom_sheet}'!$C$1:$C${cbom_last_row}, 0)),"")`
- L571: `=IFERROR(INDEX('`
- L571: `=IFERROR(INDEX('{cbom_sheet}'!$E$1:$E${cbom_last_row}, MATCH(Summary!$C{r}, '{cbom_sheet}'!$C$1:$C${cbom_last_row}, 0)),0)`
- L576: `=SUBTOTAL(109,Summary!$`
- L576: `=SUBTOTAL(109,Summary!${cost_col}${first_asm_row}:${cost_col}${last_asm_row})`
- L579: `=IFERROR(INDEX('`
- L579: `=IFERROR(INDEX('{cbom_sheet}'!$G$1:$G${cbom_last_row}, MATCH("TOTAL", '{cbom_sheet}'!$C$1:$C${cbom_last_row}, 0)),0)`
- L582: `=IFERROR('`
- L582: `=IFERROR('{ex_inv_sheet}'!$A$2,0)`
- L584: `=IFERROR(`
- L584: `=IFERROR({cost_col}{moq_cost_row}/{cost_col}{ext_vol_conv_price_row},"")`
- L611: `=IFERROR(INDEX('`
- L611: `=IFERROR(INDEX('{cbom_sheet1}'!$F$1:$F${cbom_last_row1}, MATCH(Summary!$C{row}, '{cbom_sheet1}'!$C$1:$C${cbom_last_row1}, 0)),"")`
- L615: `=IFERROR(INDEX('`
- L615: `=IFERROR(INDEX('{cbom_sheet1}'!$E$1:$E${cbom_last_row1}, MATCH(Summary!$C{row}, '{cbom_sheet1}'!$C$1:$C${cbom_last_row1}, 0)),0)`
- L625: `=SUBTOTAL(109,Summary!$`
- L625: `=SUBTOTAL(109,Summary!${cost_col}${first_asm_row}:${cost_col}${last_asm_row})`
- L628: `=IFERROR(INDEX('`
- L628: `=IFERROR(INDEX('{cbom_sheet1}'!$G$1:$G${cbom_last_row1}, MATCH("TOTAL", '{cbom_sheet1}'!$C$1:$C${cbom_last_row1}, 0)),0)`
- L631: `=IFERROR('`
- L631: `=IFERROR('{ex_inv_sheet1}'!$A$2,0)`
- L633: `=IFERROR(`
- L633: `=IFERROR({cost_col}{moq_cost_row}/{cost_col}{ext_vol_conv_price_row},"")`

## Assembly rules read from code

(see section 'Hand analysis' of 4_generation_logic_overview.md for cross-report rules: IFERROR wrapping, bounded ranges, row anchoring)
