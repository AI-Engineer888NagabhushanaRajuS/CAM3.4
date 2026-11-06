# Domain 3 - The Excel files: every input and output mapped

As of: 29 Oct 2026. Every structure below was read from the real files (openpyxl/XML inspection), not inferred. File locations: CAM shared folder, CAM - Sample Supplier Files, CAM 7 Praveen Files, CAM - copy 28 Oct archive, and the user's CAM (Internal) folder.

## 0. The pipeline at a glance (which file feeds which)

Customer BOM (any layout)
  -> [CAM 3.0 standardization skill] -> Standard client template (Standard_Template_for_Client_C01)
  -> Scrub BOM workbook (SCRUB BOM + Settings + Batch tabs)   [INPUT to the system]
  -> SBOM Upload to QW (flat quote file)
  -> RFQ sheets out to suppliers (rfq.xlsx family) -> supplier response sheets back
  -> QuoteWin awards export (Awards Part Number Listing CSV)
  -> 4.0 Merged BOM (QW&NQW) = "Awards Costed BOM"
  -> Raw CBOM (Proto, VL-1..VL-4) -> CBOM Proto + 7.0 CBOM VL-1..4 (formula-computed)
  -> 16 report tabs (Summary, BOM Matrix, Ex Inv, A-Class, Revision History, ...)
  -> Sales quote / LOA reconciliation

## 1. INPUT: the client BOM and the standard template

### Standard_Template_for_Client_C01_Updated (1).xlsx (CAM 7 Praveen Files)
The canonical client-facing template, structured as a data dictionary (row 1 = columns, row 2 = DB column name, row 3 = data format, row 4 = schema notes, row 5 = valid values). 21 columns:
Columns: FG, Level, Assembly, CPN, Description, MFR, MPN, Commodity, Quantity, UOM, Part Status, CE Remarks, Drawing Reference, Drawing Reference (sic, appears twice), Item #, Part Type, LTB Date, Common (AML), Change Remarks, Inventory Stock.
- FG: finished goods, whole number/text (example HCV_BMS_MB). Level: hierarchy depth 0-3. Assembly: parent assembly name/ID (example CB_PCBA).
- CPN: unique number Centum assigns per MPN. Description: as per customer. MFR: manufacturer (example "Molex (Waldom)"). MPN: manufacturer's part number.
- Commodity: enum at second level. Quantity: volumes required by client. UOM enum: Number, Grams, ml.
- Part Status: boolean. LTB Date: DD/MM/YYYY. Common (AML): boolean (part on the Approved Manufacturers List). Inventory Stock: whole number.
Plus Settings (FG + V1 Qty) and Batch (FG + V1 Batch Qty) tabs.

### Real client BOMs (user-shared 29 Oct)
- Centum_BOM.xlsx / BOM-Centum (1).xlsx: 122 cable/connector lines. Columns: CPN (e.g. AD4ASOH100024000-B01), Description, MPN, Commodity (e.g. "Sub Assembly Electromechanical"), Quantity, UOM (NUM), Drawing Reference (PDF filename), Reference Designators (e.g. Z2), VL 1, Vl2. BOM-Centum (1) adds a Requirement tab listing just the FG-level demand (CPN, Description, MPN, Vl1, Vl2). Note the same CPN repeating with different MPNs = alternate sources for one slot.

## 2. INPUT: the Scrub BOM workbook (the most important file in the system)

Rules (CAM - Instructions for Creating a Scrub BOM): sheet names case-sensitive; first tab SCRUB BOM with headers on row 1; mandatory non-blank: FG, CPN, MPN, Commodity, Quantity, Inventory Stock; Settings tab = unique FG + V# Qty; Batch tab = unique FG + V# Batch Qty.

Full production layout (Harish Testing BOM, 3,443 rows):
FG | Level | Assembly | CPN | Description | MFR | MPN | Commodity | Sourcing Commodity | Quantity | UOM | Part Status | CE Remarks | Drawing Reference | Reference Designators | Item # | Part Type | LTB Date | Common (AML) | Common (ANP 25) | Inventory Stock
- Level 0 row = the FG itself (e.g. A161KHW001223R0003_P4LTc, Commodity PCBA, Part Status "Not Required"); level 1+ rows are its parts.
- Same CPN can appear on consecutive rows with different MPNs = approved alternates (e.g. CPN A163BHC110021R0005 with MPNs MC100EPT23DTG and MC100EPT23DTR2G).
- Common (AML)/(ANP 25) values: Match / blank - flags whether the part is common with the AML or another project.
- Idemia variant adds: Component Product Family, Idemia Controlled Material, Unit Price -UP (CUR) - customer-specific extras are expected per client.

The Scrub BOM is where multilevel structure lives: Assembly + CPN + Quantity define parent-child recipes used by the build-vs-buy logic and quantity roll-ups.

## 3. THROUGH: SBOM Upload to QW

Sample workbook tab "3.3 SBOM Upload to QW": Assembly | Sub Assembly Flag | CPN | Description | MFR | MPN | Commodity | Quantity | UOM. The scrub BOM flattened for the quoting system (MFR filled "ANY AVL" when any approved vendor is acceptable).

## 4. RFQ sheets to/from suppliers (CAM - Sample Supplier Files)

Three generations, all data-only (no formulas):
- RFQ_1_12-1.xlsx (22 cols): S. No, MPN, Part Description, Request UOM, Quoted UOM, EAU, Proto Qty/Pricing, Vol 1-3 Qty/MOQ/Pricing, SPQ, Lead Times, Requested Delivery Timeline, Quote Validity (in Weeks), RFQ Comment.
- rfq.xlsx and "2 - supplier response rfq.xlsx" (32 cols, sheet "RFQ Data"): adds FG, Corrected MPN, Commodity, No Bid, Package Qty, Is L1, Currency, Monthly Exchange Rate, Freight Cost, Inco Terms, Effective From Date, Expiry Date, Bid Response Type, Delivery Confidence, Consolidated Order, Unit Price.
- Supplier quote with prices.xlsx (38 cols, sheet "Project"): the returned quote - Proto Qty/Pricing + Vol 1/2/3 (Qty, Pricing, MOQ) triplets + SPQ, Lead Times, validity, and the same commercial tail as the 32-col format. Example row: C0603C104K5RACTU quoted Proto 8.7, Vol1 (10) 17.4, Vol2 (100) 139.0, Vol3 (1000) 1130.0 (lot pricing).

Key commercial semantics in these sheets: No Bid flag, per-volume MOQ (a CAM improvement over QuoteWin's single MOQ), SPQ = buy multiple, Quote Validity in weeks, Is L1 marks the winner, Currency + Monthly Exchange Rate for FX, Freight Cost + Inco Terms for landed cost.

## 5. QuoteWin awards export (the QW feed)

Real file: CE-005652-HITACHI_ENERGY-RTU_QW_FILE (CSV, 1,980 lines). Structure:
- Header block: Template ("Awards Parts number listing all parts centum"), Project, Volume "1-3", Currency USD, Report On "All Prices", Sort By Cost, Time Generated.
- *** Assembly Summary: Ext Vol (Splits) #1-3, % Qty, Ext Part Vol Cost (Conv.) per split, % cost.
- *** Group Detail columns (37): Project, Part Number, Part Description, Commodity, Mfg Name, Mfg Part Number, Cost #1-3 (Conv.), Price (Original) #1-3, Currency (Original), Supp Name, Pkg Qty, MOQ, Lead Time, Awarded Volume #1-3, Award #1-3, Part Qty, Corrected MPN, Long Comment, Source #1-3, Price Type, No Bid Reason, Short Comment, NCNR, RFQ Number, Eff Date, Exp Date, Quote Validity, Part Status.
- One row per supplier quote per part: the same MPN appears 5-9 times (ECOMAL, RUTRONIK, FUTURE, TTI, ARROW, MOUSER...), Award # = 100 marks the winner per volume split, losing rows have empty Award. Source #1-3 = the SupplyWin user's email. Price Type example: NO CONTRACT.
The synthetic QuoteWin CSVs in the user's CAM (Internal) folder follow the identical format (project "testing123" etc.) - they are test fixtures.

## 6. THE WORKBOOK: CAM - Sample BOM.xlsx tab inventory (43 tabs, project CE-005405 Thales FLX)

Input/data tabs (pasted values, no formulas):
- 1.0 Scrub BOM: FG, Level, Assembly, CPN, Description, MFR, MPN, Commodity, Quantity, UOM (production scrub format).
- 3.3 SBOM Upload to QW (see section 3).
- 3.4 QW with Prices: the QuoteWin awards export pasted in (Awards Part Number Listing layout).
- 4.0 Merged BOM (QW&NQW): "Awards Costed BOM", template "Centum Costed BOM_Internal" - QW awards merged with non-QuoteWin quotes.
- Supplier: supplier master (Region, Supplier ID, Name, ... Country, Supplier Type, Currency, RFQ Method, RFQ Email(s), Notes, Time Stamp).
- Currency: EUR 0.93, INR 83.5, USD 1 (rates to USD as of the file date - stale rates are a known incident cause).
- Scrap factor: class A (>=1.25 USD) 1%, B (0.25-1.25) 2%, C (<0.25) 5%.
- Batch Qty: Assembly x (V1-4 Qty, V1-4 Batch Qty, V1-4 Batch Count).
- Raw CBOM Proto + Raw CBOM VL-1..4: "Awards Costed BOM" per volume (template Centum Costed BOM_Internal, Volume 1..4) - pre-computation staging.
- Scrub BOM (1): flattened Assembly Name | CPN | Description | Manufacture Name | MPN | Commodity | Qty - used by the check tabs.

Computed tabs (formulas - details in Domain 4):
- CBOM Proto + 7.0 CBOM VL-1..4: the costed BOM per volume. Each carries the report header (Awards Costed BOM / project / volume / currency / sort), an Assembly Summary block, a Validation block, and the line table with 48 columns:
  FG part number, Assembly, Part Number, Description, Commodity, Mfg Name, Mfg Part Number, Unit, Part Qty, Ext Vol Qty #1, Price (Splits) #1 (Conv.), Price #1 (Original), Currency (Original), Ext Price (Splits) #1 (Conv.), Ext Part Vol Price (Splits) #1 (Conv.), Supp Name, Pkg Qty, MOQ, Lead Time, NRE Charge, NRE Charge (Conv.), NCNR, Price Control, Long Comment, Price Type, Exp Date, MFR in Customer BOM, Corrected MPN, End Use Statement, Supplier Type, Line No., Is Data, Is Assembly, Parent Line No., ABC Classification, Scrap, New Supp, Is Price Same, Is MPN Same, Is Costed, Recurring Count, Mfg. Part Num in Scrub Bom, MOQ Qty Present, Pkg Qty Present, PKg Qty <= MOQ, Assembly+Parent Line, Part Num+Line, FG Part Qty.
  The validation block counts: Total CPNs, Unique CPNs, Shared CPNs, occurrences of shared, Total Line Items, Uncosted Line Items, CPNs with diff price, CPNs with diff MPNs, Wrong MPNs w.r.t Scrub BOM, MOQ Missing, SPQ Missing, PKG > MOQ, Commodity Missing.

The 16 report tabs:
1. Summary: per assembly, per revision - Proto/VL-1..4 volumes and CBOM costs across up to 3 revisions side by side + Delta + in% + CBOM Ref No. (INDEX/MATCH pulls from each CBOM tab.)
2. Revision History: S.No, Revision, Assembly, CPN, Description, Commodity, Manufacturer, MPN, EAU, V1/V2 OLD vs NEW system Qty, OLD vs NEW unit price $ with % delta, price per volume with Delta. (VLOOKUPs into 7.0 CBOM VL-4.)
3. Missing Note: uncosted lines with reason (e.g. "Uncosted-Due to customer Support"), Quoted MFR/MPN, Remarks.
4-8. 6.0 BOM MATRIX Proto + VL-1..4: part x assembly matrix - rows = Part Number, columns = each assembly + EAU, Description, Commodity, Mfg Name, Mfg Part Number, Unit Price in $, per-assembly extended values, Grand Total, Pkg Qty, MOQ, Lead Time, Price Control. Cross-check row compares CBOM Summary vs BOM Matrix Summary per assembly.
9-13. Ex Inv Proto + VL-1..4 (excess inventory): Part Number, Description, Commodity, Mfg, MPN, Part Qty, Ext Vol (Splits) #1, Excess In Stk, Excess after considering..., Shortage Qty, Scrap, Scrap factor, Cost #1, Ext Vol Cost, Supp Name, New Supp, Pkg Qty, MOQ, Lead Time, Net Ordering qty, Net Excess Qty/Cost #1, Final buy value, Supplier Type, Remarks, Pkg <= MOQ.
14. A CLASS PARTS: the cost-driving parts (A = top 80% of spend): Part Number, Description, Commodity, Mfg, MPN, Part Qty, Ext Vol, Cost #1, Ext Price, X (% of spend), Ext Vol Cost, Supp Name, Pkg Qty, MOQ, Lead Time, ABC Classification, MOQ turns, Average MOQ turns in days, Price control, Remarks.
15. Batchwise Cashflow: payment-term buckets (30 DAYS / 60 DAYS / Advance) x Sum of Final buy value x average payment terms - when money goes out per production batch.
16. Lead Time Consolidated: LT in weeks x Count of Part Number x In % (distribution).
17. Lead Time FG Wise: per FG, LT bucket x count + grand total per FG.
18. Price Control: Centum vs TNP vs CNP spend splits with % of total (uses GETPIVOTDATA; live #REF! errors seen in this tab).
19. New Suppliers: new-supplier spend analysis per volume (pulls from Ex Inv tabs).
20. Mech &EM NRE / 21. PCB NRE & FAI Charge: non-recurring charges by commodity rule (FAI = first-article inspection, PCBs only; NRE for mechanical/electromechanical).
22. Sum & Count Detailed + 23. Sum & Count: per-assembly reconciliation of Scrub BOM vs Proto vs VL-1..4 - sums and line counts with Is Sum Same / Is Count Same flags.
24. Part Num vs Mfg Num: existence check of each Part Number + MPN pair in the Scrub BOM (TRUE/FALSE).

## 7. BOM.zip (Harish's enrichment workstream, shared 29 Oct)

A working folder, not a report: Python scripts that take a BOM (BOM_power_pack_V3_30mA example) and enrich it from distributor APIs - digikey_enrichmnet.py, mouser_client.py, element14.py / element14_enrichment.py, enriched.py, distributer.py, bom_to_database.py (DuckDB), consolidated_bom.py, export_consolidation.py, setup_enrichment.py, view_duckdb.py, enrichment_schema.py. Outputs: Standardized_BOM.xlsx, Expanded_BOM.xlsx, Volume_Expanded_BOM.xlsx, Consolidated_BOM.xlsx, duckdb_export.xlsx, Multiple_bom.xlsx, output/results.xlsx. Plus "vibe-architect", a Next.js scaffold (spec-compiler, llm-client, ui-parser, system-prompt) - an early UI experiment. Config via config.env (API keys - not inspected, secrets stay untouched). This maps to the CAMintel/Findchips-replacement direction: API-driven BOM completion.

## 8. Synthetic test fixtures (user's CAM (Internal) > Synthetic Scrub & QW Files)

20 files: synthetic scrub BOMs (SCRUB BOM, Scrub_BOM, Scrub BOM, Synthetic Scrub BOM Sample, Syn_Scrub1-10, Synthetic_Scrub_BOM_10k) and QuoteWin-format CSVs (QuoteWin x3). All match the real formats (section 2 and 5) with invented parts (ECU-PWR-M01 etc.), letting CAM be tested at 10k-row scale without exposing customer data. The 17 Oct open-items list calls for exactly such a mock-data library for certification runs.

## 9. QA evidence (Centum_observation screenshots)

- obs1 (CE-005646 Knorr Bremse AION Timer Card): validation grids cross-checking BOM MATRIX vs Summary (Total Value, Proto - "Not Matching"; CPN Count, CPN Qty, SPQ/MOQ/LT - "Matching"), LEAD TIME Consolidated (PIVOT) vs 7.0 CBOM VL-3 ("Not Matching"), PRICE CONTROL Grand Total vs Summary ("Not Matching").
- obs4 (CE-005637 Thales Medical Converter): UI bug - upload completed, no errors shown, BOM Matrix still not generated.
These show the manual validation practice the automated acceptance checks must encode.
