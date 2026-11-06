# Encyclopedia 2 - Every formula kind decoded

The complete formula census of the corpus: 43-tab sample workbook (422,645 formula cells) + 19 Internal workbooks + 18 CAM report workbooks - together well over 1.5M formula cells. This doc decodes every function used and every distinct formula pattern, with real formulas. Domain 4 owns the 12 high-level families; this doc is the exhaustive under-iceberg version.

## Part A: the function census (what functions exist and what each DOES here)

Measured across the whole corpus (function occurrences from raw XML):

| Function | What it does in this domain | Where |
|---|---|---|
| INDEX + MATCH | The CAM generator's lookup pair: MATCH finds the row of a CPN in a CBOM column, INDEX pulls the attribute. Wrapped in IFERROR so misses return "" | every CAM 'BOM MATRIX', report tabs |
| IF | The universal gate: `IF(Is Data, compute, "")` - decides whether a row computes at all | everywhere |
| IFERROR | Converts any failure to "" or 0 - the corpus's error-suppression blanket (hides real problems: see RE 1/2) | everywhere |
| VLOOKUP | The human-era lookup (Revision History, QW Matrix, older Internals). First-match semantics = the duplicate-CPN hazard | Revision History, Quotewin Matrix, older files |
| SUMIFS | Multi-criteria aggregation: sum ext cost where CPN=X and not-excluded | Ex Inv, A CLASS, Sum & Count |
| COUNTIFS | The validation counters (1029 total CPNs, 546 uncosted...) | CBOM validation block |
| SUMPRODUCT | Conditional sum over arrays: `SUMPRODUCT(N27:N282, --(B27:B282=C11), --(AF27:AF282=AI27:AI282))` = sum Ext Price where assembly matches AND flag-equality holds. Also EAU = SUMPRODUCT(qty row, volume row) | CBOM assembly summary, matrix EAU |
| MAX | One-sided clamps: MAX(stock-need,0)=excess, MAX(need-stock,0)=shortage | Ex Inv |
| SUBTOTAL(9/109,...) | Filter-aware sums (9 includes hidden, 109 excludes) in matrix/summary totals | QW Matrix, Summary |
| TEXT | Number/date formatting for report text columns | Internals (2,816-14,400 uses per file) |
| UPPER(TRIM(...)) | Boolean-string normalization: `UPPER(TRIM(INDEX(...AF...)))="TRUE"` - copes with 'TRUE' strings vs booleans | CAM matrix pulls |
| AND / OR / NOT | Compound boolean flags (priced AND moq-present...) | validation columns |
| ISERROR | Pre-IFERROR-era guard: `NOT(ISERROR(MATCH(...)))` = "found" | validation columns |
| ROUND | Price-average comparison rounding (Is Price Same) | AL column |
| ROUNDUP | Buy-quantity rounding (scrap/MOQ -> whole units) | Ex Inv / ACLASS (496-5,496 uses/file) |
| CONCATENATE | Composite keys: `CONCATENATE(B25,"_",AH25)` -> 87093547V00_Line_10 | AT/AU key columns |
| LEFT / LEN / FIND / SUBSTITUTE | String surgery: the find-the-last-dot idiom (below); cashflow term parsing | AH line-id, cashflow |
| NUMBERVALUE | "30" from "30 DAYS" for cashflow weighting | cashflow |
| AVERAGEIFS / ABS | Average price/terms per bucket; absolute deltas | CAM report tabs |
| SUM | Plain totals (grand totals, matrix row sums R9+S9+T9...) | everywhere |
| COUNTIF | Duplicate detection, single-criteria counts | CAM Sum & Count |
| Array formulas (ArrayForm) | Dynamic-array spills in newer files (5570 Summary row 5, ACLASS descriptions) - modern Excel creeping into a legacy book | 5570, CAM reports |

## Part B: the distinct formula PATTERNS (the real grammar)

1. **The armored compute**: `=IF($C25="Part Number", "Ext Price (Splits) #1 (Conv.)", IF($AF25, $I25*$K25, ""))` - emits its own header on the header row, computes on data rows, blank otherwise. Lets one formula blanket a whole column.
2. **The key builder**: `=IF($AF25, CONCATENATE($B25,"_",$AH25), "")` -> `87093547V00_Line_10`.
3. **The last-dot idiom**: `LEFT($AE25,FIND("@",SUBSTITUTE($AE25,".","@",LEN($AE25)-LEN(SUBSTITUTE($AE25,".","")))))` - replace the LAST dot with @ (count dots via LEN difference, substitute only the Nth), then split. Generic "find last occurrence" recipe.
4. **The same-price check**: `ROUND(SUMIFS(K,C,C25)/COUNTIFS(C,C25),n)=K25` - average price for my CPN must equal my price.
5. **The not-equal count**: `COUNTIFS(G,"<>"&G25,C,C25)>0` - any row with my CPN but a different MPN?
6. **The waived check**: `IF(OR($AG25, NOT($AN25)), TRUE, AND($R25<>"",$R25<>0))` - assemblies and uncosted rows auto-pass MOQ presence.
7. **The validation counter**: `COUNTIFS($AO$25:$AO$1754,"=1",$AF$25:$AF$1754,TRUE)` and derived arithmetic (Unique=Total-Shared, Occurrences=Rows-Unique).
8. **The cross-tab pull**: `SUMIFS('CBOM Proto'!$AV..,'CBOM Proto'!$C..,A5,'CBOM Proto'!$AG..,FALSE)` - report tabs aggregate the CBOM via composite-key + exclusion-flag criteria.
9. **The clamp pair**: `MAX(H5-G5,0)` / `MAX(G5-H5,0)` - excess / shortage.
10. **The volume guard**: `=T2=T3` in matrix row 1 - adjacent volume headers must match (unaggregated: nobody reads the FALSE).
11. **The headline hoist**: `='Ex Inv Proto'!$V$1030` / `=SUM($A$2)` - pull a bottom-of-range total to the top. Fragile fixed anchor.
12. **The string-parsed term**: `=$B4*IFERROR(NUMBERVALUE(LEFT($A4,FIND(" ",$A4))),0)` - "30 DAYS" -> 30 x spend.
13. **The CAM matrix cell**: `=IFERROR(IF(UPPER(TRIM(INDEX('7.0 CBOM VL-1'!$AF:$AF,MATCH($A9,'7.0 CBOM VL-1'!$C:$C,0))))="TRUE",INDEX('7.0 CBOM VL-1'!$D:$D,MATCH($A9,'7.0 CBOM VL-1'!$C:$C,0)),""),"")` - whole-column INDEX/MATCH gated on the text-typed boolean.
14. **The zero-safe ratio**: `=IF($B$35=0,0,B2/$B$35)` (CAM Lead Time) - the newer generator's improvement over `=$B5/SUM($B$5:$B$29)` (older, DIV/0-prone).
15. **The reconciliation pair**: `=IFERROR(SUMIFS('Sum & Count Detailed'!$C:$C,...),0)` + `=AND(B2=D2)` - whole-column sums + equality flags.
16. **The rev-compare delta**: `=Q5-H5` (Summary), `=K9*I9`, `=L9*J9`, `=N9-M9` (Revision History: old vs new extended price).
17. **The scenario fan-out**: the same patterns re-instantiated per Proto/VL-1..VL-4 tab - one semantic computation, 5 physical copies. Combined with pattern 1's column-fill, this is why 12 families become 422,645 cells.

## Part C: measured scale (raw-XML census, this pass)

- Human-assembled Internals: 6,709 (5530, smallest) to 167,857 formulas (5673 Internal). Function leaders: IF (up to 118,870), INDEX (up to 97,485), MATCH, VLOOKUP (human files), AND/NOT/TEXT.
- CAM 21-tab reports: 5,543 (5530) to 144,057 (5673 matrix). Leaders: INDEX (up to 262,853), MATCH, IFERROR, IF, UPPER/TRIM (boolean-string handling), SUMIFS, MAX, ROUNDUP.
- The style difference is a fingerprint: human workbooks lean VLOOKUP; CAM outputs lean INDEX/MATCH + IFERROR + UPPER/TRIM. You can tell who made a file from its function histogram alone.
- Error cells in shipped files (cached values): CBOM_Report_RFQ_000016 8,840 #REF!; 5599 matrix 15,131 #N/A + 410 #REF!; 5579 matrix 10,745 #N/A + 720 #REF!; 5580 matrix 10,205 #N/A + 686 #REF!; 5605 Internal 3,655 #N/A + 1,286 #NUM!; 5673 Internal 1,524 #NUM!; 5615 Internal 394 #NUM! + 18 #DIV/0!. (#N/A on lookups = parts not found; #NUM! typically bad numeric coercion; #REF! = broken range after edits.)

OPEN: ArrayForm dynamic-array formulas are only partially decoded (openpyxl exposes them as objects, not text) - their individual expressions not enumerated. The supplier RFQ sample files' formulas (3 generations) are not censused here (they are input templates, mostly formula-free).
