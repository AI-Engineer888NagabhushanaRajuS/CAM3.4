# (4) Formula analytics

Data: 364 xlsx/xlsm workbooks, 187 with formulas, 8,324,692 formula cells raw, 6,575,191 after removing duplicate copies (a copy is a workbook with identical formula count, template count and sheet count). Authored code: 298 formula-string sites (SRIM) plus 24 distinct items (CAM). Workbook class comes from file name. Dates come from dates inside file names (27 unique formula workbooks carry one), so the time series is thin.

## 1. Workbook classes (unique copies)
| Class | Workbooks (unique) | Formula cells (unique) | Leading functions |
|---|---|---|---|
| Internal workbook (human-built) | 48 (45) | 3,227,417 | IF, INDEX, MATCH, IFERROR, VLOOKUP |
| BOM Matrix (tool output) | 32 (29) | 1,524,972 | INDEX, IF, IFERROR, MATCH, UPPER, TRIM |
| Other | 37 (27) | 1,085,795 | IF, INDEX, MATCH, IFERROR, VLOOKUP |
| CBOM Report (tool output) | 20 (20) | 731,891 | IFERROR, INDEX, IF, MATCH, UPPER, TRIM |
| QuoteWin / awards | 9 (2) | 3,346 | VLOOKUP (3,345 external-workbook lookups) |
| Scrub BOM | 41 (25) | 1,770 | SUM, COUNT, SUMPRODUCT |
Full function table: 4_function_usage_by_class.csv.

## 2. Hand-built versus tool-generated
- VLOOKUP appears in 353,748 Internal cells and 0 cells of the BOM Matrix and CBOM Report outputs. Tool outputs replace it with INDEX/MATCH inside IFERROR, and wrap keys in UPPER(TRIM()) (145,690 and 110,937 cells).
- Whole-column references: 813,476 BOM Matrix cells and 309,928 CBOM Report cells, against 2,982 Internal cells. Tool formulas are slower to recalculate on large files.
- External-workbook references: 3,345 in one QuoteWin awards listing (all cells), 1,301 in Internal workbooks.

## 3. Evolution over time (file-name dates, unique workbooks)
| Month | Workbooks | Cells | VLOOKUP | INDEX | IFERROR | UPPER | SUMIFS |
|---|---|---|---|---|---|---|---|
| 2025-09 | 1 | 3,345 | 100% | 0% | 0% | 0% | 0% |
| 2025-12 | 4 | 412,548 | 0% | 49.6% | 34.6% | 10.1% | 9.2% |
| 2026-01 | 2 | 55,957 | 0% | 53.0% | 35.0% | 11.8% | 9.4% |
| 2026-07 | 7 | 322,884 | 0% | 54.9% | 55.8% | 16.0% | 7.8% |
| 2026-08 | 3 | 103,298 | 0% | 58.2% | 64.6% | 16.3% | 8.5% |
| 2026-09 | 9 | 297,203 | 0.2% | 54.2% | 54.7% | 13.9% | 9.5% |
| 2026-10 | 1 | 8,506 | 0% | 54.3% | 56.1% | 15.3% | 9.7% |
Percent is the share of formula cells using the function. Reading: one switch from VLOOKUP to INDEX/MATCH by Dec 2025, then error wrapping roughly doubled by Jul 2026 and has stayed flat. Regression of formula count on file date: BOM Matrix slope -3,168 cells/day (n=6, R2 0.51), CBOM Report slope -403 cells/day (n=20, R2 0.24). Both are weak and sample sizes are small, so no trend in output size can be claimed.

## 4. Crosswalk to authored templates
- SRIM authored function signatures (first six functions in order): 53. 41 occur in at least one workbook; 12 never occur: IFERROR>IF, IFERROR>IF>UPPER>TRIM, IFERROR>INDEX, ISBLANK, ROUND>SUMIFS, IFERROR>ABS>INDEX, IF>INT, IFERROR>ROUNDUP>MAX, IF>IFERROR, IF>IFERROR>INDEX, IFERROR>IFERROR, NOT>AND. These are candidates for dead or never-triggered branches.
- Workbook cells whose signature matches an authored signature: Internal 42.9%, BOM Matrix 47.3%, CBOM Report 49.7%, Other 44.5%. The rest use signatures with no authored equivalent (62 signatures, 3,619,660 cells). Largest: INDEX>MATCH>INDEX (644,154), VLOOKUP (461,363), IFERROR>IF>UPPER>TRIM>INDEX>MATCH (225,125).
- Limits: authored formulas that are built by helper functions are only partly visible in the source scan, and signatures are cut at six functions, so the true uncovered share is probably lower. Two sources are not reachable: older Laravel exporter and the 88 Google Sheets. Full table: 4_srim_template_crosswalk.csv.

## 5. Anomalies
- #REF! inside formulas: 14 cells in Internal workbooks (6 in each copy of CE-005673 Internal output, 2 in Zeta and Leopard). 0 in tool outputs.
- Volatile functions (OFFSET, INDIRECT, TODAY, NOW, RAND): 4,706 Internal cells; 0 in tool outputs. Largest: CE-005673 with 762, Zeta and Leopard with 643, 5661 Interlock Controller Internal with 534.
- Formulas longer than 500 characters: 71,036 in Internal workbooks, 52,308 in BOM Matrix, 31,766 in CBOM Report. Largest single workbook: CE-005603 LMC-6 Internal with 9,249.
- Duplicates: 187 workbooks hold formulas and 148 are unique, so 39 are repeat copies (6.58M of 8.32M cells are unique). Sample BOM files appear in 5 variants of about 12 MB each.

## 6. How the system works (reading of the evidence)
1. Roughly 300 formula templates are written in code (SRIM reports) and expanded down rows. The 8.3M cells are expansion output.
2. Human-built Internal workbooks predate the tool and use a different style (VLOOKUP, volatile functions, #REF! risks). The tool reproduces their result with a stricter, error-wrapped style.
3. Test fixtures (the 20 synthetic sheets) are value-only, so formula correctness is never exercised by them. A regression suite would need golden outputs from the project workbooks.

## 7. Method notes
Formulas were read from the XML of each sheet (shared formulas expanded). Counts were re-checked by counting lines of the extraction files (8,324,692, equal to the sum of per-workbook counts).
