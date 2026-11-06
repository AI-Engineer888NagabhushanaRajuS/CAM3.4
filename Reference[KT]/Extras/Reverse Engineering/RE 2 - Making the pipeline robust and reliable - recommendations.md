# RE 2 - Making the pipeline robust and reliable: recommendations

Basis: RE 1's evidence from the real outputs (22 project folders, 8 workbooks deep-inspected). Ordered by impact. Each item names the evidence it answers.

## A. Ship gates - nothing leaves with a broken cell (highest impact, cheapest)

**A1. Export-time error sweep.** Before any workbook (CAM tool or human-assembled) is delivered, scan every cell for Excel error literals (`#REF!`, `#VALUE!`, `#N/A`, `#DIV/0!`, `#NAME?`, `#NUM!`, `#NULL!`) and FAIL the export. Evidence: 8,840 `#REF!` cells shipped in CBOM_Report_RFQ_000016 'Ex Inv VL-1'; 13 in the 5677 Internal. This single gate would have caught both. In openpyxl this is ~10 lines; the CAM report tool can run it as the last pipeline stage.

**A2. Dead-report detection.** A report tab whose computed content is entirely zeros/placeholders (`-`, `(unspecified)`) should be flagged or suppressed. Evidence: Batchwise Cashflow all-zero with `(unspecified)` supplier type; A CLASS PARTS full of `-` rows; Revision History OLD columns all `-`. Rule: a tab with >90% placeholder content is either fixed or explicitly stamped "NO DATA - reason" before shipping.

**A3. GO/NO-GO reconciliation cell.** The workbooks already compute the checks (Sum & Count `AND(B2=D2)`, the `=K3=K4` volume guards, the validation counters) but nothing aggregates them. Add one health panel on the Introduction tab: total CPNs, uncosted count, error-cell count, sum-match ALL-TRUE, volume-guard ALL-TRUE -> single green/red. Evidence: guard booleans currently sit unread in row 2.

## B. Type and range discipline in the generator

**B1. Booleans as booleans.** The mixed `'TRUE'` string vs `TRUE` boolean (mfg_part_num_in_scrub_bom, the AF flag consumed via `UPPER(TRIM())`) is a silent-blank-column hazard. Fix at the export layer; validate with a type check per column.

**B2. Kill fixed-range anchors.** `='Ex Inv Proto'!$V$219`, `=$I$206`, `$C$27:$C$282` - replaced in CAM output by whole-column SUMIFS (already done in Sum & Count - extend to every tab) or structured tables. For human workbooks, convert ranges to Excel Tables so anchors grow.

**B3. Unique-CPN enforcement at ingest.** The matrix INDEX/MATCH takes the first match on a duplicated CPN - the documented Matrix BOM bug. Make scrub validation reject duplicate CPNs per matrix scope, and have the matrix generator COUNTIF the key column and refuse to build on duplicates.

## C. Provenance and versioning

**C1. Manifest tab in every output.** One tab recording: generator + version, run id, run timestamp, input file names + hashes, settings snapshot (currency rates, scrap table, batch quantities), and the per-tab row counts. The 76-col CBOM tab already has the data model for this (bom_item_id, *_costing/_erp/_qw/final_*) - the manifest just lifts it to the file level. Kills "which inputs made this file?" forever.

**C2. One naming convention, enforced.** `BOM_Matrix_756_20260119_101102` vs `5646-BOM Matrix` vs `Copy of ...` vs `..._25.09.202(amended)`. Convention: `<Project>_<Artifact>_<Rev>_<YYYYMMDD>`; CAM writes it, humans never rename. Folder rule: one project folder, inputs/ and outputs/ subfolders.

**C3. Manual prices need provenance too.** The Non Quotewin Matrix and costing sheets take typed prices with no author/time. Add Priced By / Priced On / Source-ref columns (the costing sheet already has Long Comment - formalize). Otherwise the NQW side stays the audit blind spot.

## D. Data-quality feedback loops

**D1. Payment-terms master data.** Cashflow tabs zero out because supplier_type/payment terms are unmapped (`(unspecified)`). Fix the supplier master join (Supplier tab has Type + currency + RFQ method - add payment terms there, one source of truth), and gate on unmapped suppliers.

**D2. Uncosted-parts SLA.** 546/1474 uncosted line items in the sample run; A CLASS exports carry `-` placeholders. Track uncosted % per run as a KPI on the health panel; distinguish No Bid from not-yet-quoted (CAMail already records No Bid - surface it).

**D3. Revision-delta alarm.** Summary already computes rev-to-rev deltas (`S5=Q5-H5`). Add the rule the +245% incident taught: flag any assembly whose cost moved more than a threshold (say 15%) between revisions without a logged reason. This is the automated version of the incident report's lesson.

## E. Process

**E1. Golden-file regression testing.** The 22 project folders are a perfect test corpus: known inputs, known shipped outputs. Every CAM generator change should re-run all 22 and diff cell-level against the shipped versions; unexpected diffs block release. This converts today's tribal knowledge ("5579 needed an amended file") into executable tests.

**E2. Keep humans out of the computed columns.** The Internal workbook is hand-assembled from CAM parts + manual tabs (Jig List, Missing Notes). Make the tool emit the full Internal format directly, with free-text annex tabs clearly separated from computed tabs, so hand edits can't corrupt formulas (5677's 13 error cells came in through hand assembly).

**E3. Adopt REA-style artifact review as a standing step.** This reverse-engineering pass found 5 distinct shipped defects in 4 files. Running the same structural scan automatically over every project folder after each run (errors, placeholders, type mixes, duplicate keys) is cheap and compounds.

## What is already solid (do not break these)

- The 4-way provenance model (`*_costing / *_erp / *_qw / final_*`) with UUID keys in the 2026 CBOM export - the right foundation.
- Whole-column SUMIFS + IFERROR wrappers + zero-guards (`IF($B$35=0,0,...)`) in the newer CAM tabs.
- The Introduction/tab-link tab, Missing Notes numbered sections, Sum & Count reconciliation concept, and the layered boolean-flag validation design.
- The human review culture: expert feedback doc, discrepancy report, edge-case registers. The recommendations above mostly turn what the best reviewers do by hand into gates the tool enforces.
