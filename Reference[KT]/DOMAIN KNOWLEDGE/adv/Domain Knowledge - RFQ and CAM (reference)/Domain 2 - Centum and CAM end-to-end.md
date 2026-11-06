# Domain 2 - What Centum does and what CAM does, end to end

As of: 29 Oct 2026. Sources: CAM FAQ Document, CAM Flow & Benefits, CAM - BOM Automation Summary (Internal, F2F 21-22 Nov 2024), CAM AI Project Update (2 Mar 2025), CAM Original Scope of Work, Win-More-Deals-with-CAM, Logical Data Model, CAM component API Parameters, Tools Used in CAM, plus the existing BRAIN architecture write-ups (which this doc does not replace - see section 6).

## 1. What Centum (the company) does

Centum Electronics is an EMS (Electronics Manufacturing Services) company headquartered in Bangalore. Customers in aerospace, defense, industrial, medical and automotive send it product designs; Centum sources the components, builds PCB assemblies and finished products, and delivers. The commercial front door of that business is the enquiry-to-quote process described in the Domain 1 doc: win the RFQ with a fast, accurate, competitive quote and the build order follows.

Why quoting is hard here: a single project BOM has 1,000-5,000 line items (the real sample workbook carries 1,474 line items across 10 assemblies; the synthetic test BOMs go to 10k), each line needs a supplier, a price at each volume tier, MOQ/SPQ handling, currency conversion, lead time, and risk flags - and the answer must reconcile to the rupee against the customer's LOA.

## 2. The legacy toolchain CAM replaces

From the CAM AI Project Update: "CAM is built to eliminate many of Centum's existing tools like Scrub BOM, QuoteWin, SupplyWin, Drills (BOM Conversion tool), and PCN (pending Accuris API integration)."

- QuoteWin (QW): the legacy quoting/awards system. Suppliers are floated RFQs, quotes come back, parts get "awarded" to winning suppliers. Its export format (Awards Part Number Listing) is still the canonical awards input to costing (seen in CE-005652 QW file and the Synthetic QW files). Limitations noted: one MOQ per part, manual supplier selection, no per-volume MOQ.
- SupplyWin: the secure supplier communication channel (supplier master RFQ Method = "SupplyWin(Secure)" on every row).
- Drills: the BOM Conversion tool that turned scrub BOMs into costed BOM outputs. CAMerge is its replacement and exceeds it (QW+NQW integration, one-tab multi-volume output).
- Findchips: website used for component data extraction; CAM plans API-based enrichment instead (Mouser, Digikey, Accuris evaluated in CAM component API Parameters.xlsx - 6 API options compared across ~50 parameters).
- InforLN ERP: ~43,000 MPNs of raw ERP data (1 year) transformed for the CAM commodity master / spend analysis (CAMind).
- PCN/Accuris (previously IHS): lifecycle/change notifications; integration was pending API access as of Mar 2025.
- Volza: import/customs duty insights (roadmap item from the F2F).

## 3. CAM = Centum Automation Modules

CAM is a modular AI project sponsored by Centum Electronics (sponsor named: Mr. Jagadish Singh) and built by DigitalBull AI (DBAI). Kickoff was the 21-22 Nov 2024 face-to-face; the first modules rolled out by Mar 2025. CAM stands for Centum Automation Modules and has 5 modules:

1. CAMview - BOM management. Unified BOM listing with live status, version control and revision history, BOM audit reports (missing components, compliance, supplier info), data validation and error detection before processing. Solves: Excel version chaos, no change tracking, wrong BOMs loaded.
2. CAMail - RFQ management. Automated RFQ distribution by commodity, magic-link quote submission for suppliers (download sheet, fill, upload; only the updated sheet is saved), AI-based response tracking, auto follow-up to non-responsive suppliers, automatic L1/L2 identification, unlimited quote volumes, per-volume MOQ, mail templates for initial/rejection/selection. SMTP integration with Centum's Outlook server was pending in Mar 2025.
3. CAMerge - BOM conversion (Drills replacement). Merges quotes from multiple sources, standardizes and levels the BOM, QW + NQW integration, matrix BOM generation (proto + volumes in one view), duplicate detection, single-tab multi-volume output.
4. CAMind - self-serve sourcing analytics. Tabular dashboard of BOM/ERP data, AI chat for sourcing questions, custom report generation from chat, embedded analytics, commodity classification, search by make/manufacturer, ERP data cleanup (stronger MPN-Mfr-Supplier links). Tools Used in CAM.xlsx records: original 13 CBOM report tabs in PHP Laravel by Ultiweb; Metabase partially implemented through CAMind (no chat support, licensing concerns); Hex.tech shortlisted for testing.
5. CAMintel - parts intelligence and risk. BOM audit (unique MPNs/CPNs/FGs/assemblies, missing fields), ECN/PCN notifications via Accuris (needed API access), Mouser API integration planned for BOM completion, risk reports (see CAMview - Risk Report.docx: lifecycle status, compliance, NCNR, risk per MPN).

Stated benefits (CAM AI Project Update): clean up of existing data, fewer enquiry-to-quote steps, reduced time per process, less manpower, insights from more resources via API. The headline target: Scrub BOM to Matrix BOM from 2 days to 2 hours.

## 4. The data model behind it (Logical Data Model)

The CAM Automation Project Logical Data Model defines the canonical entities. Highlights:

- Table 1 Part (49 fields): Part_Number_ID (PK; CPN variant with CE prefix once the order is won), Description, Part_Type (22 electronics categories), Manufacturer_Name, MPN, CPN, Custom_Part, Assembly_ID, Subcontractor, Sub_Assembly_Level (0-3), Commodity_Type_Level_1..4 (Level 1 values: Active, Consumable, DNQ, Electromechanical, Packing, Passive, PCB, PCBA, Sub Assembly PTH, Sub Assembly SMT), ABC_Category (A=80% of cost, B=15%, C=5%), Cost, MOQ, SPQ, Price_Control, NCNR, lifecycle fields (EOL, NRFND, LTB, Single_Source), risk fields, compliance (RoHS, REACH, Dangerous Goods, MSD level, Shelf life), Defect_Rate (aka Adders/Attrition), Lead_Time (calendar weeks), Inventory_Turns, Alternates, Commodity_Owner.
- Table 2 Supplier (21 fields): Supplier_ID (PK, aka BPCode), company/contact details, location, Geopolitical_Risk, Supplier_Category (Manufacturer/Distributor/Consolidator), Lead_Time_Performance, Reliability_Score, AML/AVL flags, Credit_Limit, Payment_Terms, ISO_Certification, Capacity_Utilization.
- Table 3 RFQ: Project_ID, Part_Number_ID, Supplier_ID, Volume_Batch_Quantity, Volume_EAU_Quantity, Unit_of_Measure, Currency...
- Commodity taxonomy is a maintained master: CAM component API Parameters.xlsx carries Commodity Mapping 1.0, 2.0 and Combined (Electrical > Wires and Cables > Wire > Single-Core/Multi-Core/Shielded... mapped across Centum, Mouser, FindChips, Accuris taxonomies). The Commodity Master & Data Cleansing doc describes the cleansing project over the 43k-MPN ERP extract.

## 5. Where CAM stands now (3.3 vs 4.x) - pointer, not repetition

The version-separated current state is already documented in this BRAIN folder and stays the source of truth for architecture:
- "CAM Centum synthesis - current state vs 4.x target - 2026-10-28.md"
- "Version map.md", "CAM 3.3 to 3.4 - JSON manifests, Jinja2+AST, and what to do" (Doc), and the CAM walkthrough videos.

The one-paragraph version: CAM 3.3 is the working system (PHP Laravel reports by Ultiweb, Dify + MCP Jungle + Bifrost running, 16-tab Excel outputs). CAM 4.0 is the in-build redesign on the BuLLM platform: 10 ISATVON skills for the RFQ pipeline plus a single FastMCP report tool (cam_report_generate) that regenerates the whole 16-tab workbook from one manifest, with 33 edge-case variables (8 confirmed defaults, 25 guarded/unconfirmed as of 16 Oct 2026). Do not mix versions: per the standing rule, every artifact in this doc series is labeled with the system it belongs to.

## 6. What this means concretely

When you read any CAM artifact, place it on this map:
- Excel workbook with Scrub/CBOM/16 report tabs = the current production output format (3.3 and earlier). The 12MB CAM - Sample BOM.xlsx is the reference specimen.
- ISATVON JSON / FastMCP skeleton / skill docs = the 4.0 build that must reproduce and exceed that output.
- QW CSV exports (Awards Part Number Listing) = the legacy awards feed both worlds consume.
- Supplier RFQ xlsx samples = the CAMail input/output formats.

## 7. How the modules behave on bad input (from CAM - Possible Issues & Fixes.xlsx)

A 34-row module-by-module error matrix. The operational rules it records:
- CAMview BOM upload: header-name matching is exact but typo-intolerant (correct fields accepted, typos not recognized - user must name fields properly); extra columns are ignored; column order does not matter (reads by header); missing mandatory columns are rejected per column; wrong file type rejected (CSV/XLS/XLSX only); missing/mislabeled Settings tab shows as NOT AVAILABLE.
- CAMail: SMTP not yet on Centum's network - a temporary Gmail rfq@centum.bullmailai.com was created for the interim; wrong/outdated supplier emails are corrected by DigitalBull in the DB; suppliers must whitelist the sender; lost magic URLs get automated reminders + manual resend; an all-missing-prices upload is treated as No Bid; a second conflicting upload supersedes the first (latest wins); partially missing prices are accepted and reminders sent; quotes after deadline are stored but miss the merge window; manual override upload exists for stuck suppliers.
- CAMerge: if the QuoteWin file is missing or has missing data, merging proceeds with CAMail data alone; Matrix BOM can be generated at any time (no need to wait for all quotes); multi-tab costed outputs beyond the single combined tab were still being built at that date.
- Matrix BOM correctness rule (CAM - Matrix BOM Issue.pptx): CPNs must be unique in the matrix - repeating CPNs are the canonical matrix error.
