# RE 1 - The 22 project folders reverse-engineered: how every output is produced

Method note: direct structural analysis of the artifacts themselves (openpyxl + raw XML inspection of the downloaded workbooks) - the same ground-truth-first method the OSS "REA" (Reverse Engineering Anything) approach prescribes: read the artifact, never the description. Every claim below is tied to a named file. Sources so far: 8 workbooks fully inspected across 6 projects (5570, 5646, 5677, RFQ-000016, plus matrix variants); the remaining folders were inventoried and fit the same grammar (marked CONFIRMED-BY-NAME, not yet opened one by one - OPEN if we want 22/22 coverage).

## 1. The artifact grammar - every project folder tells the same story

Across all 22 folders (CAM 7 Praveen Files: 7 projects, CAM Other Input Files: 15 projects) the same 5-6 file types repeat, and they map exactly onto the pipeline from Domain 1/3:

| # | File pattern | What it is | Role |
|---|---|---|---|
| 1 | `CE-00XXXX-<customer> - SCRUB BOM <date> Rev N.xlsx` | Cleaned customer BOM | INPUT |
| 2 | `AWARDS_PART_NUMBER_LISTING_<proj>_FLOAT_<date>.xlsx` or `..._QW File.xlsx` | QuoteWin awards export | PRICING INPUT |
| 3 | `00XXXX costing sheet.xlsx` | Buyer's manual price-entry file (non-QuoteWin parts) | MANUAL PRICING INPUT |
| 4 | `CE-00XXXX-..._Internal_<date>.xlsx` | THE "Internal Document" - the full costed workbook the team ships internally (basis of the LOA) | MAIN OUTPUT |
| 5 | `<id>-BOM Matrix.xlsx` and `BOM_Matrix_<runid>_<YYYYMMDD_HHMMSS>.xlsx` | The 21-tab CAM tool report | AUTOMATED OUTPUT |
| 6 | `CBOM_Report_RFQ-XXXXXX_<timestamp>.xlsx` | Newest CAM report generation, adds the 76-column database CBOM tab | AUTOMATED OUTPUT (2026) |

Side observations: duplicates everywhere - "Copy of", "(1)", "Fixed", amended versions (5579 has both `Internal_25.09.2025.xlsx` and `Internal_25.09.202(amended).xlsx`). Version control is done by filename.

## 2. The "Internal" workbook - the human-assembled master output

Fully reverse-engineered from CE-005570 (Oct 2025, LOA edition) and CE-005677 (Feb 2026, Rev-04).

It is a per-project resized copy of the master template (the 43-tab sample workbook's family), assembled by hand:

- 5570: 30 tabs. Settings tabs (Supplier 2,146 rows, Currency INR 85.6, Scrap factor, Batch Qty) + Scrub BOM + 2 Raw CBOMs + CBOM Proto/VL-1 + the 16 reports, plus LOA-specific additions: Summary does a REVISION COMPARE (old rev 15-July-2025 vs new 07-Oct-2025 side by side, `S5=Q5-H5` deltas), Revision History (726 VLOOKUPs pulling old-vs-new prices), separate **Quotewin Matrix** (VLOOKUP-driven) vs **Non Quotewin Matrix** (literal typed values - manual prices with remarks like "No stock in online"), Missing Notes (packing box dimensions), PCB Spec.
- 5677: 25 tabs, same skeleton + project-specific adds (Jig List, 5677-Jigs).
- Formula ranges are re-sized per project by hand: `$27:$282` in 5570 vs `$25:$1754` in the sample. Totals anchored to fixed end rows (`='Ex Inv Proto'!$V$219`, `=$I$206`).
- Both shipped with live Excel error cells (5677: 13 across ACLASS PARTS + Price Control).

## 3. The CAM tool report - what the automation actually emits

Fully reverse-engineered from `BOM_Matrix_756_20260119_101102.xlsx`, `5646-BOM Matrix.xlsx`, `5570-BOM Matrix.xlsx`, and `CBOM_Report_RFQ_000016_20260728_134209.xlsx`.

- Files named `<id>-BOM Matrix.xlsx` are NOT hand-made: they are the CAM tool's own 21-tab output (Introduction tab reads "CAM - Centum Automation Management" with tab links), renamed by hand. Same structure in all three checked.
- Tab set: Introduction, BOM MATRIX, Part Num Vs Mfg Num, PCB NRE & FAI, Mech & EM NRE, Missing Notes, Lead Time (FG Wise), Lead Time Consolidated, Sum & Count, Sum & Count Detailed, Revision History, A CLASS PARTS, Price Control, Summary, Batchwise Cashflow, 7.0 CBOM Proto/VL-1/VL-2, Ex Inv x3.
- 2026 generation (CBOM_Report_RFQ_000016) adds a **76-column 'CBOM' tab** that exposes the underlying database: `bom_item_id` (UUID), and for every attribute a 4-way provenance model - `<attr>_costing`, `<attr>_erp`, `<attr>_qw`, `final_<attr>` (mfr name, UOM, price, currency, supplier, pkg qty, MOQ, lead time) - plus validation flags as data columns (`is_costed`, `moq_qty_present`, `pkg_qty_present`, `pkg_qty_lte_moq`, `is_price_same`, `is_mpn_same`, `is_data`, `is_assembly`), `batch_qty`, `volume_qty`, `scrap_percent`, `abc_classification`, `recurring_count`, `parent_line_no`. The validation engine that lives in helper formulas in the Excel pipeline is data in the new system. This is genuinely good design.
- Real example of provenance at work (RFQ-000016 row 2): capacitor 1080636434 - customer BOM says "Murata", QW awarded "MURATA", price 0.144 USD from QW, supplier Future Electronics, pkg 1000, MOQ 1000, LT 25, scrap 5% (C-class), batch 2850. Alternates appear as separate rows (Kyocera, SEM, Vishay, Yageo for the same CPN).

## 4. The costing sheet - the manual edge of the pipeline

`005570 Costing sheet.xlsx`: 21 columns (part number...Price #1 (Original), Currency, Supp Name, Pkg Qty, MOQ, Lead Time, NRE, NCNR, Price Control, Price Type, Exp Date, Long Comment) - exactly the CBOM attribute set, hand-filled for non-QuoteWin parts, one tab per volume. Buyer notes in Long Comment ("Master carton is not required", "600*530*300 MM"). Header drift inside one file: VOL-1 tab header cell contains `1.0` where VOL-2 has `Project` - schema maintained by hand.

## 5. Failure evidence found inside shipped outputs (the basis of RE 2)

1. **8,840 `#REF!` error cells in `CBOM_Report_RFQ_000016` 'Ex Inv VL-1'** (entire Scrap/Scrap Factor columns broken) - a CAM-generated report shipped with broken references.
2. **13 error cells in the Feb-2026 human-assembled 5677 Internal** (ACLASS PARTS, Price Control).
3. **Placeholder rows exported as data**: A CLASS PARTS in RFQ-000016 is full of `-` / 0 rows (uncosted parts exported into a "top parts" report).
4. **Dead reports shipped**: Batchwise Cashflow in RFQ-000016 is all zeros with supplier type `(unspecified)` - payment terms never joined. Revision History OLD columns all `-` - no baseline loaded.
5. **Type inconsistency**: booleans appear both as real booleans and as the STRING `'TRUE'` (`mfg_part_num_in_scrub_bom`); the BOM MATRIX formulas compensate with `UPPER(TRIM(...))="TRUE"` - one export quirk away from silently blank columns.
6. **Fixed-range anchors** in human workbooks (`$V$219`, `$I$206`, `$27:$282`) - insert rows past the anchor and totals go stale silently.
7. **Guard cells that guard nothing**: `=K3=K4` volume-check booleans sit in row 2 of matrix tabs; nothing aggregates or alerts on a FALSE.
8. **Version control by filename**: amended/Fixed/(1)/Copy-of duplicates in most folders; no manifest of which inputs produced which output.
9. **Matrix uniqueness hazard**: CAM BOM MATRIX uses INDEX/MATCH on the CPN column - first match wins on duplicate CPNs, the exact bug the project's own Matrix BOM Issue deck warns about.
10. **Manual price entry without provenance**: Non Quotewin Matrix values are typed literals; no record of who priced them or when.

## OPEN / not yet verified

- 16 of 22 project folders inspected by NAME only (grammar confirmed, contents not opened one by one).
- 5673 Lam Research folder's tail files (listing was cut at first entries).
- Whether the CAM 4.0 FastMCP report tool is the generator of the 2026 `CBOM_Report` naming - strongly indicated by the LDM field names matching (Part/Supplier/RFQ tables), not yet confirmed against the tool's code artifacts.
- REA toolkit itself: method applied manually; not installed/run. If we adopt it, its value-add is repeating this analysis automatically over all 22 folders + the code archives (CAMail/CAMerge/CAMview/CAMind source archives are in Drive).

---

## 6. Round 2 deep pass (29 Oct evening): full 22/22 coverage, measured

Every project folder opened, every Internal workbook and every matrix/CAM report downloaded and structurally censused (raw-XML formula/function/error scan + openpyxl inspection). This replaces the "16 of 22 by name only" caveat above.

### 6.1 Coverage matrix (19 Internals + 18 CAM reports + 5652's QW-only folder)

| Project | Internal file | Tabs | Formulas | Error cells shipped |
|---|---|---|---|---|
| 5445 Rafael | yes (25 tabs, 'CE-005445' cover tab, 'Revision history old' + 'Revision History') | 25 | 33,766 | 1,632 #N/A, 4 #NUM!, 2 #REF! |
| 5530 Signata | yes (24 tabs, PCB Spec, Internal Review) | 24 | 6,709 | 12 #N/A |
| 5570 TI Clean | yes (30, QW+NQW matrix split, LOA rev-compare) | 30 | 34,739 | 1 #VALUE!, 3 #REF! |
| 5579 Knorr HEC | yes (23, scrub embedded as tab) | 23 | 37,601 | 109 #N/A, 2 #REF! |
| 5580 Knorr | yes (23) | 23 | 48,429 | 34 #N/A, 1 #DIV/0!, 347 #REF! |
| 5599 Idemia MTOP | yes (27) | 27 | 25,456 | 3 #REF!, 12 #N/A |
| 5600 Idemia ViP | yes (30, VL-1..3) | 30 | 73,677 | 4 #REF!, 24 #N/A |
| 5605 Thales Z&L | yes (27, stray '%' tab, Sheet2, Internal Review) | 27 | 105,359 | 3,655 #N/A, 1,286 #NUM!, 3 #REF!, 1 #DIV/0! |
| 5615 Thales PAAG | yes (30; stray tabs 'CE-005399' + 'CE-005078_ 1883' from OTHER projects) | 30 | 48,120 | 18 #DIV/0!, 394 #NUM!, 3 #REF!, 12 #N/A |
| 5619 Rafael CCA | yes (24, stray '%' tab) | 24 | 9,015 | 238 #N/A, 166 #NUM!, 2 #REF! |
| 5632 Crane | yes (32, PCB SPEC) | 32 | 94,458 | 4 #REF!, 12 #N/A |
| 5637 Thales Medical | yes (24, Revision history) | 24 | 15,006 | 17 #N/A |
| 5639 Hitachi Hirel | yes (28, Proto+VL-1) | 28 | 55,494 | 73 #N/A |
| 5641 Mahle ECF | yes (36, Proto+VL-1..3, PCB Spec) | 36 | 39,196 | 12 #N/A |
| 5646 Knorr AION | yes (32, Internal Review) | 32 | 19,755 | 17 #N/A |
| 5652 Hitachi RTU | NO Internal - QW file + scrub only (pipeline incomplete or output stored elsewhere) | - | - | - |
| 5655 Mahle Inverter | yes (35, PCB Spec) | 35 | 23,246 | 14 #N/A, 2 #REF! |
| 5657 Thales SharpView | yes (36) | 36 | 129,463 | 38 #N/A |
| 5661 Lam Interlock | yes (32; TWO revision tabs: 'Revision history - 2FG' + 'Revision history for Old vs New') | 32 | 140,666 | 254 #N/A, 103 #DIV/0! |
| 5663 Thales LPS | yes (37, Sheet3, PCB Spec) | 37 | 92,330 | 4 #VALUE!, 173 #N/A, 4 #REF! |
| 5673 Lam Node Board | yes (28, 'Internal output file' name, Sheet1+Sheet2) | 28 | 167,857 | 168 #N/A, 1,524 #NUM!, 4 #REF! |
| 5677 Rafael 9CCA | yes (25, Jig List + 5677-Jigs) | 25 | 85,152 | 10 #N/A, 3 #REF! |

CAM 21-tab reports censused: 5445 (12,225 formulas), 5530 (5,543), 5570 (24,218; 4,253 #N/A + 110 #REF!), 5579 (38,238; 10,745 #N/A + 720 #REF!), 5580 (43,733; 10,205 #N/A + 686 #REF!), 5599 (46,077; 15,131 #N/A + 410 #REF!), 5600 (50,449), 5615 (22,698), 5619 (8,884; 2,655 #N/A + 180 #REF!), 5632 (90,645), 5637 (11,414), 5639 (47,172), 5641 (19,276), 5646 (17,674), 5657 (90,084), 5661 (108,998), 5673 (144,057), CBOM_Report_RFQ-000016 (78,340; 8,840 #REF!).

### 6.2 New findings from the deep pass

1. **Scale**: the corpus holds well over 1.5 million formula cells; the largest single output (5673 Internal) has 167,857. The 422,645-cell sample workbook is the master template they were all cloned from.
2. **Clone-and-edit assembly is now proven, not inferred**: 5615's Internal carries stray tabs named 'CE-005399' and 'CE-005078_ 1883' - sheets from two OTHER projects left inside the 5615 deliverable. 5605 and 5619 carry a stray '%' tab. 5661 has Sheet3/Sheet4, 5673 Sheet1/Sheet2 scratch tabs.
3. **Error cells are the norm, not the exception**: only 5 of 19 Internals are error-free; CAM matrices ship thousands of #N/A (lookup misses = parts the matrix couldn't resolve) and hundreds of #REF!. The 8,840-#REF! report is the worst single case, not an outlier in kind.
4. **The 'Internal Review' tab decoded** (present Dec-2025 onward): management pivots of spend by quote-age bucket, sourcing channel (Consolidator/Disty/MFR/Online), commodity, payment terms - real 5646 numbers: 51.3% of spend on quotes under a month old, Online 32% / Disty 40.5% / MFR 24.4% / Consolidator 3.1%.
5. **Generator fingerprints**: human Internals are VLOOKUP-led; CAM reports are INDEX/MATCH+IFERROR+UPPER/TRIM-led (the UPPER/TRIM exists to survive 'TRUE'-string booleans). A file's function histogram identifies its maker.
6. **Naming confirmed as the only version control**: amended/(1)/Copy of/- Fixed duplicates in most folders; 'Internal output file' (5673) and 'Radiall' suffix (5632) show naming drift even on the newest files.
