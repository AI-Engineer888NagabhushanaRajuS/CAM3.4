# Generation logic overview: SRIM report builders

Scope: mcp-tools/reporting/superset/reports/*.py (16 report modules) at commit 540918090b1b2c64efcb6472caffefacc17da6ff, read statically and executed against real workbooks.
Per-report documents: logic_<report>.md in the Generation Logic subfolder (docstring, constants, function list, every authored formula site with line number).
Labels: FACT = read in code or measured. INFERENCE = deduced, not stated in code.

## 1. Cross-report assembly rules (FACT, from bom_matrix, ex_inv_vl, aclass_parts, mech_em_nre, pcb_nre_fai_charge, cbom_vl)

1. Formulas are strings built with f-strings. One Python function emits one formula template for one cell; the row number is substituted per data row (`A{r}`, `H{r}`). There is no fill-down copy at the Excel level. Every row receives its own written string.
2. Row anchoring: the current row is computed as `len(rows)+1` (ex_inv_vl_rows) or `data_start + index`. Part-number cell is always column A of the same row (`pn_cell = A{r}`).
3. Lookup shapes:
   - Text/numeric attribute: `=IFERROR(INDEX(<bounded CBOM col>, MATCH(<cpn>, <bounded CBOM C>, 0)),0)` or `...,"") & ""` when coerce_text is true (`_index_lookup`, `_index_formula`).
   - Sum across duplicate CPN rows: `=SUMIFS(<value col>, <C col>, <cpn>, <AH col>, "<>TRUE")` (`_sumifs_lookup`).
   - Two-key lookup: `MATCH(1, INDEX((A=fg)*(C=cpn)*(UPPER(TRIM(AF))="TRUE"),0),0)` (`_fg_price_lookup`, `_cbom_lookup_if_af_true`).
   - Delta against previous volume: `=IFERROR(ABS(INDEX('<prev sheet>'!O$5:O$1029, MATCH(...)) - O{r}),0)` (Ex Inv AH, AI). Volume 1 references `Ex Inv VL-proto` only when has_proto is true (code comment: avoids a latent #REF!).
4. Error handling: every lookup is wrapped in IFERROR. Numeric columns fall back to 0, text columns to "" (commented in `_index_lookup`). This is why tool outputs contain no #REF!/#N/A in the measured set.
5. Bounded ranges, not full columns: `_bounded()` builds `INDEX(sheet!$C:$C,$AL$1):INDEX(sheet!$C:$C,$AK$1)` in Ex Inv, with AL1/AK1 written as literal integers computed in Python by `cbom_vl_bounds()` (docstring says they previously were LOOKUP/MATCH full-column scans). Mech & EM NRE and PCB use fixed `$27:$282` (`_CBOM_ROW_START`, `_CBOM_ROW_END`). BOM Matrix uses per-sheet row counts passed in.
6. When a template fires: by column key (`if key == "Cost #1": ...` chains in aclass_parts), by position in a list (`_data_row` in ex_inv_vl returns a 36-element list; formula strings at fixed positions, blanks as ""), and by volume (volume loop creates one sheet per volume; proto first).
7. Not formulas: Price Validity and Effective Date in BOM Matrix are written as values. Conditional-format rules (e.g. `=NOT(AND($X2=TRUE,$Y2=TRUE))` in sum_and_count and sum_and_count_detailed) are stored as FormulaRule objects, not as cell formulas.

## 2. Proof of the generation function (FACT, measured)

Method: for 4 real CBOM_Report workbooks (Test_05 25-Aug-2026, CE_005862 21-Sep, CE_005870 22-Sep, CE_005864C 05-Oct), rebuild the builder input from the workbook's static cells, call the real builder from the repository file, compare every generated formula string with the actual cell string. Currency/DB helper imports were stubbed (they affect values, not formula text).

| Report | Cells compared (formula cells generated) | Exact | Mismatch | Present on one side only |
|---|---|---|---|---|
| BOM MATRIX (4 workbooks, data rows 9+ and the row-7 header SUMs) | 13,586 | 13,586 | 0 | 0 |
| A CLASS PARTS (11 CBOM_Report workbooks with literal AK1/AL1 bounds, grand-total row, header and data rows) | 39,281 actual formula cells | 38,805 | 0 | 476 in actual only, 0 in generated only |
| PCB NRE & FAI Charge (4 workbooks, 1 data row each) | 20 | 20 | 0 | 0 |
| Ex Inv VL-n (Test_05: proto, 1, 2) | 11,253 | 11,253 | 0 | 0 |
| Ex Inv VL-n (CE_005870, CE_005862, CE_005864C: VL-1, VL-2) | 15,872 | 14,848 | 1,024 | 0 |
| Ex Inv VL-n total | 27,125 | 26,101 | 1,024 | 0 |

Combined exact: 13,586 + 20 + 26,101 + 38,805 = 78,512 of 80,012 compared formula cells (98.1 percent). Every mismatch has a stated cause below (1,024 Ex Inv guard difference; the 476 A CLASS PARTS one-sided cells are two extra formula columns per data row in one older workbook, CE_005603, 238 rows).

Notes:
- BOM MATRIX needs the Ex Inv last-row bound equal to Ex Inv max_row minus 1 to reach 13,575/13,575. With max_row, 1,200 Net Excess Cost formulas differ (360, 360, 60, 90). INFERENCE: the bound is the last data row.
- Ex Inv mismatches are confined to two columns (L and N, "Ext Vol with Scrap" style columns): 364, 58 and 90 rows times 2 columns per sheet. Actual cell: `=IF(INT(F5)=F5, ROUNDUP(J5*(1+IF(K5="",0,K5)),0), J5*(1+IF(K5="",0,K5)))`. Code at the commit: `=IF(INT(F{r})=F{r}, ROUNDUP(J{r}*(1+K{r}),0), J{r}*(1+K{r}))`. The Aug 25 workbook matches the commit; the Sep 21, Sep 22 and Oct 5 workbooks carry the `IF(K="",0,K)` guard. INFERENCE: the generating deployment for these later workbooks ran a code version different from this commit (a blank-scrap guard that is not in the commit). The commit may be older than the Sep/Oct deployment, or the guard was removed after. Git history for the file was not inspected, so direction is unknown.
- Mech & EM NRE could not be tested: the sheet is named `Mech &EM NRE` in the workbooks (53 workbooks) and `Mech & EM NRE` in my lookup, and the sample workbooks showed 0 data rows under the name used. Not proven.
- RESOLVED: the row-7 header SUMs (e.g. `=SUM(R9:R128)`) ARE produced by the builder: reports_bom_matrix.py L329, `ws.cell(row=7, column=col).value = f"=SUM({col_letter}9:{col_letter}{last_data_row})"` in the FG price matrix header. The earlier comparison covered rows 9 onward only. Including row 7: 13,586/13,586 exact (5,283 + 5,762 + 962 + 1,579).
- Ex Inv version direction (see section 2b).
- Mech & EM NRE could not be tested: the sheet is named `Mech &EM NRE` in the workbooks and the sample workbooks showed 0 data rows under the name used. Not proven. PCB NRE & FAI Charge was proven (20/20).
- Reports not tested: cbom_vl, summary, price_control, batchwise_cashflow, revision_history, sum_and_count(+detailed), lead_time(+consolidated), missing_notes, part_num_vs_mfg_num, Mech & EM NRE. Reason: these builders take payloads derived from database queries; the inputs cannot be rebuilt from the sheet's static cells without a per-report inverse mapping that was not written.

## 2b. Code version direction for the Ex Inv L/N difference (FACT + INFERENCE)

FACT: GitHub get-file-content for solutionsDigibull/BuLLMQuote_SRIM, path mcp-tools/reporting/superset/reports/ex_inv_vl.py, returns identical content (md5 8a6bd10f...) for ref `main` and ref 540918090b1b; neither has the `IF(K="",0,K)` guard (line 156 reads `ROUNDUP(J{r}*(1+K{r}),0)`). Repository metadata: private, updated_at 2026-09-21T11:31:56Z. No pull requests exist (state all, 0). The connector offers no commit-listing action, so line-level history is not available.
FACT: workbooks dated 2026-08-25 match main exactly; workbooks dated 2026-09-21 (CE_005862), 2026-09-22 (CE_005870) and 2026-10-05 (CE_005864C) carry the guard.
FACT: the CAM exporter (backend/reporting_module/exporter.py, harvest zip) imports `reports.lead_time_fg_aclass`, `reports.price_control_aclass`, `reports.lead_time_consolidated_aclass`, `reports.batchwise_cashflow_aclass`. These module names do not exist in the SRIM commit (which has lead_time_fg, price_control, lead_time_consolidated, batchwise_cashflow). The `reports` package itself is not in the CAM harvest zip.
INFERENCE: the Sep/Oct workbooks were produced by a newer variant of the reports package than SRIM main (the CAM-side `*_aclass` family or a later branch), which added a blank-scrap guard after the Aug 25 build. Evidence for direction: SRIM main behaves like the Aug 25 workbook and unlike the later ones, so SRIM main is not newer than the Sep/Oct generator. It is not proven that the guard was added rather than that main was reverted, and the producing repository was not found.

## 3. Dead-template autopsy (12 never-seen signatures)

Context: the signatures in 4_srim_template_crosswalk.csv are the first six function names of a formula, extracted from authored strings with placeholders collapsed. Many authored strings are fragments (a string split across f-string lines), so the signature of the fragment differs from the signature of the whole formula. Re-testing with the substring in the 8.32M-cell workbook set (reference-normalised, 364 workbooks):

| Signature | Code location | Verdict | Workbook evidence (cells / workbooks) |
|---|---|---|---|
| IFERROR>IF | aclass_parts.py L311, ex_inv_vl.py L171 | ALIVE, signature artefact. aclass fires in the `Cost #1` column branch; ex_inv fires per data row (Excess column AA) | Ex Inv: part of IF(INT...) and ROUNDUP families, see below |
| IFERROR>IF>UPPER>TRIM | bom_matrix.py L125 (`_cbom_lookup_if_af_true`) | ALIVE | 231,313 cells / 49 workbooks (`IFERROR(IF(UPPER(TRIM(INDEX(...AF...))="TRUE"`) |
| IFERROR>INDEX | bom_matrix L463, ex_inv_vl L297/L377, revision_history L548, summary L567-628 | ALIVE as the fragment of longer signatures; the plain two-function form is the Ex Inv/Summary attribute lookup | present inside nested families; exact 2-function-only form not counted separately |
| ISBLANK | cbom_vl.py L577, L1155 | ALIVE. Fires once per CBOM sheet in a SUMPRODUCT counter (row 22, Commodity Missing Count) | 51 cells / 20 workbooks |
| ROUND>SUMIFS | cbom_vl.py L879, L1025 | ALIVE. Fires per data row in "Is Price Same" (column 39) when AF is TRUE and K is not blank | 117,890 cells / 91 workbooks |
| IFERROR>ABS>INDEX | ex_inv_vl.py L293, L399, L408 | ALIVE. Fires in AH (cost delta vs previous volume), only when a previous-volume sheet exists | 1,571 cells / 10 workbooks (low: few workbooks have 2+ volumes in Ex Inv with the delta columns) |
| IF>INT | ex_inv_vl.py L156, L158 | ALIVE. Fires per data row in columns L and N | 152,592 cells / 106 workbooks (in the guarded `IF(K="",0,K)` variant for Sep/Oct) |
| IFERROR>ROUNDUP>MAX | ex_inv_vl.py L167 | ALIVE. Fires in column W per data row | 78,595 cells / 106 workbooks |
| IF>IFERROR | mech_em_nre.py L152, pcb_nre_fai_charge.py L147 | ALIVE by construction (`_lookup_formula`); PCB test matched 20/20 | counted under the NRE sheets; strict regex on the normalised form found 0 because of spacing, so the count is not established here |
| IF>IFERROR>INDEX | mech_em_nre L239, pcb L246 | ALIVE, same code path as above | same |
| IFERROR>IFERROR | revision_history.py L316, L334 (base with fallback) | ALIVE | 88,588 cells / 53 workbooks |
| NOT>AND | sum_and_count.py L300, sum_and_count_detailed.py L302 | DEAD AS A CELL FORMULA, ALIVE AS A RULE. It is a conditional-formatting FormulaRule applied to the data range when both "Is Sum Same" and "Is Count Same" columns exist. It is never written to a cell, so it cannot appear in cell-level extraction | 0 cells, as expected |

Conclusion (FACT for code paths, INFERENCE for counts): 11 of the 12 are live code paths; the "never seen" status came from matching by 6-function signature on truncated fragments. Only NOT>AND is genuinely absent from cell formulas, because it is a conditional-format rule. Counts in the table come from substring matching on normalised formulas and are looser than the signature crosswalk.

## 4. Laravel-era reconstruction (INFERENCE throughout)

Evidence (FACT):
- Every report module docstring names a PHP source it ports: BomMatrixFormatExportExcelFormula.php, CBOMVolumeSheetExcelFormula::generateRows, ExcessInventoryVolumeSheetExcelFormula, BlockthreeController methods (aclass_json, lead_time_fg, nrecharge, faiCharge, revision_history_json, cpnvsmpn_json, sum_and_count), MissingNotesController, PriceControlController::processPriceControl, Tab8Context/Computer/Merger (Summary), SumAndCountExportExcelFormula, NreChargeExportExcelFormula.
- CAM stubs name ProcessTab16Job and CBOMWorkbookExport / CBOMVolumeSheet / CBOMIntroSheet; the stub says GitHub access to the PHP source is pending.
- Workbook dating: the only Sep 2025 workbook with formulas is a QuoteWin AWARDS_PART_NUMBER_LISTING (3,345 formula cells, all VLOOKUP into external workbooks). From Dec 2025 onward, tool outputs use INDEX/MATCH inside IFERROR with UPPER/TRIM. "Internal" human-built workbooks use VLOOKUP.

Reconstruction (INFERENCE):
1. The PHP exporters built each sheet as an array of rows (`array()`/`generateRows`) where formula cells were strings with the row index interpolated, mirroring the Python `ex_inv_vl_rows` (docstring: "Port of ExcessInventoryVolumeSheetExcelFormula::array()"). The Python row-list structure is therefore likely a direct translation.
2. ProcessTab16Job (INFERENCE) most plausibly orchestrates the tab-16 (final report) build: it receives per-RFQ JSON (CPNs, volumes, FG keys), calls the CBOM workbook export (CBOMVolumeSheet per volume, then Ex Inv, BOM Matrix, Summary, etc.), and writes one xlsx. The Python exporter.py in the CAM harvest zip plays this role now.
3. The VLOOKUP era (INFERENCE): lookups of the form `VLOOKUP(key, sheet!range, col, FALSE)` imply column-index addressing, so the early PHP likely wrote numeric column indexes. The later INDEX/MATCH + IFERROR + UPPER(TRIM(AF)) style implies a rewrite that addressed columns by letter and added error guards (the Python comments describe #N/A propagation fixes). This ordering is inferred from dates only.
4. Caveat: the Sep 2025 VLOOKUP workbook is a QuoteWin-side award listing referencing external workbooks, so it is not evidence about the Laravel exporters. No Laravel-generated workbook from the VLOOKUP era was identified. The PHP source is not accessible, so nothing in this section can be verified.
