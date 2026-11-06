# (3) Internal sheets - formula extraction and analytics

Scope
A. Synthetic Scrub and QuoteWin files (Drive folder owned by sriniketh.s, 20 Google Sheets). Each sheet was exported to xlsx and every sheet part was scanned for formulas.
B. The human-built "Internal" workbooks found in the project folders (name contains "Internal"): 48 workbooks, extracted at cell level in folder (1).

Result A
- 20 files, 58 sheets, 4,323,125 cells.
- Formula cells: 0. Every cell is a static value. Distinct templates: 0.
- Verification: XML scan of all 20 exports shows no formula tags. A live read with formula render of "SCRUB BOM" (Mar 2026), "Scrub BOM" (Jan 2026) and "QuoteWin" (Jan 2026) returned 0 formulas in the first 300 rows.
- Meaning: these files are input fixtures (synthetic BOMs and QuoteWin award tables) for testing Scrub BOM and QuoteWin processing. They carry no formula logic. Sheet inventory: 3_internal_sheets_inventory.csv.

Result B
- 48 Internal workbooks: 3,426,957 formula cells raw, 3,227,417 after removing 3 duplicate copies (45 unique).
- Largest: CE-005673 LAM Research Set 2 Node Board Assembly "Internal output file" (167,858 cells, two copies), CE-005657 Thales SharpView internal (129,463), CE-005605 Thales Zeta and Leopard (105,359), CE-005632 Crane Cabin System (94,458), CE-005663 Thales LPS PCBA (92,330).
- Function mix: IF 1,429,624 cells, INDEX 1,169,995, MATCH 1,104,407, IFERROR 364,761, VLOOKUP 353,748, AND 348,502, NOT 253,843, SUMIFS 216,928 (function counted once per cell).
- Table: 3_internal_workbooks_formula_table.csv (all classes, with class column; filter class = Internal).

Not covered
- Cached values and number formats (extraction holds formulas only).
- Google Sheets other than these 20 (88 exist in the corpus) and workbooks inside zip archives.
