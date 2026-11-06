# Domain 1 - RFQ and the enquiry-to-quote process at Centum

As of: 29 Oct 2026. Grounded in the CAM shared Drive folder, the CAM - Sample Supplier Files folder, the CAM 7 Praveen Files / CAM Other Input Files folders, the user's CAM (Internal) folder (BOM.zip, BOM-Centum (1).xlsx, Synthetic Scrub & QW Files), and the CAM project docs (BOM Automation Summary 21-22 Nov 2024, CAM Flow & Benefits, CAM FAQ, CAM AI Project Update 2 Mar 2025, Logical Data Model, Instructions for Creating a Scrub BOM). Conflicts and unknowns are marked, never guessed.

## 1. What an RFQ is in this business

RFQ = Request for Quotation. Centum Electronics is an EMS company (Electronics Manufacturing Services) in Bangalore: it builds PCB assemblies and box-build products for OEM customers (aerospace, defense, industrial, medical). When a customer wants Centum to manufacture a product, they send an RFQ package. Centum must answer with a price: what it will cost to build the product at each requested volume, and when.

The RFQ package from the customer contains, in real files seen:
- A BOM (Bill of Materials) in the customer's own Excel layout: part numbers, descriptions, manufacturers, manufacturer part numbers, quantities, reference designators, drawing references.
- Volume requirements: prototype quantity plus production volume tiers (seen as Vol 1-4 / VL-1..VL-4) and EAU (Estimated Annual Usage).
- Sometimes drawings (PDF references appear in the Drawing Reference column) and target requirements.

Centum's answer is the sales quote. Everything between "customer RFQ lands" and "sales quote goes out" is the process CAM is automating. Internally this is called the "enquiry-to-quote" process (also referred to as the KOGC process in the CAM AI Project Update doc; the KOGC expansion itself is not spelled out in any source - marked unknown).

## 2. The players

- Customer (OEM): Thales, Knorr Bremse, Idemia, Rafael, Hitachi (Hirel, Energy), Mahle, Crane Aerospace, Lam Research, Signata-VW, TI Clean Mobility, Siemens Industrial (all seen as CE-xxxxx project folder names).
- Centum CE team (Cost Engineering): registers the enquiry, creates the Scrub BOM, owns the quote file. The "CE Remarks" and "Part Status" columns in the Scrub BOM are theirs.
- Centum sourcing team / commodity leads: run supplier RFQs per commodity, select suppliers, negotiate. Menaka is named as Sourcing Head (CAMview Risk Report). Commodity owners named in the Logical Data Model: Sathish, Spoorthi, Kavi, Srinivas.
- Suppliers / distributors: Mouser, Arrow, TTI, Future, Rutronik, Avnet, WPG, Ecomal, Digi-Key, Newark, Rochester, plus local Indian suppliers (JC Gupta, Stronic, Premier Packing, Pushkar Insulation, Satinox, Elvia...). Supplier master fields include Supplier ID (e.g. S4811), currency, supplier type (Manufacturer/Distributor/Local/Consolidator), and RFQ Method, which in the real supplier master is "SupplyWin(Secure)" for every row.
- Sales: receives the costed BOM and turns it into the customer-facing sales quote (SBOM side).

## 3. The end-to-end flow (with the real artifacts at each step)

Step 0 - Customer enquiry arrives. Customer sends their BOM (any Excel layout) + volumes. Example seen: BOM-Centum (1).xlsx with a Requirement tab (CPN, Description, MPN, Vl1, Vl2) and a BOM tab (CPN, Description, MPN, Commodity, Quantity, UOM, Drawing Reference, Reference Designators, VL 1, Vl2), 122 lines of cable/connector parts.

Step 1 - Project registration. The enquiry becomes a project with an ID like CE-005405 (Thales FLX), CE-005646 (Knorr Bremse AION Timer Card), CE-005652 (Hitachi Energy RTU), CE-006001 (Siemens Industrial). Older numbering also appears as plain 4-digit folders (5570, 5579, 5632...) in the CAM 7 Praveen / CAM Other Input Files folders. Which CRM holds registration today is an open item (17 Oct 2026 OPEN items list, Skill 1).

Step 2 - Scrub BOM creation (input standardization). The CE team converts the customer BOM into Centum's standard Scrub BOM workbook. Rules from "CAM - Instructions for Creating a Scrub BOM (INPUT)":
- Sheet names are case-sensitive. First tab must be SCRUB BOM with headings on row 1.
- Mandatory columns with no blanks: FG, CPN, MPN, Commodity, Quantity, Inventory Stock.
- Second tab Settings: unique FG values + V# Qty columns (volume per FG).
- Third tab Batch: unique FG values + V# Batch Qty columns.
Real full column set (Harish Testing BOM, 3,443 rows): FG, Level, Assembly, CPN, Description, MFR, MPN, Commodity, Sourcing Commodity, Quantity, UOM, Part Status, CE Remarks, Drawing Reference, Reference Designators, Item #, Part Type, LTB Date, Common (AML), Common (ANP 25), Inventory Stock. The Idemia scrub BOM (1,526 rows) adds customer-specific columns (Component Product Family, Idemia Controlled Material, Unit Price -UP (CUR)). CAM 3.0 has a formal skill for this step (cam.input_bom.template_standardization.v1): find the BOM sheet and header row, map columns to the standard template, highlight missing mandatory cells in yellow, save a reusable mapping profile per client.

Step 3 - Internal quote file. The scrub BOM is reduced to the "SBOM Upload to QW" format (Assembly, Sub Assembly Flag, CPN, Description, MFR, MPN, Commodity, Quantity, UOM) and volumes are attached. This is what gets priced.

Step 4 - RFQ float to suppliers. For each commodity group, sourcing sends RFQ sheets to the relevant suppliers. Real RFQ sheet layouts seen (three generations in CAM - Sample Supplier Files):
- RFQ_1_12-1.xlsx (22 cols): S. No, MPN, Part Description, Request UOM, Quoted UOM, EAU, Proto Qty, Proto Pricing, Vol 1-3 Qty/MOQ/Pricing, SPQ, Lead Times, Requested Delivery Timeline, Quote Validity (in Weeks), RFQ Comment.
- rfq.xlsx / "2 - supplier response rfq.xlsx" (32 cols, sheet "RFQ Data"): adds FG, Corrected MPN, Commodity, No Bid, Package Qty, Is L1, Currency, Monthly Exchange Rate, Freight Cost, Inco Terms, Effective From Date, Expiry Date, Bid Response Type, Delivery Confidence, Consolidated Order, Unit Price.
- "Supplier quote with prices.xlsx" (38 cols, sheet "Project"): the response format with Proto + Vol 1/2/3 Pricing and MOQ triplets.
Historically this ran through QuoteWin/SupplyWin (supplier master RFQ Method = "SupplyWin(Secure)"). CAM replaces it with CAMail: automated RFQ emails, a magic link per supplier to download/update/upload the quote sheet, automatic follow-ups, and response catching.

Step 5 - Quotes come back. Suppliers fill pricing per volume tier, MOQ per volume, SPQ (standard package quantity), lead time, quote validity, currency, and can mark No Bid. CAMail tracks who responded; QuoteWin required a single MOQ while CAM supports MOQ per volume.

Step 6 - Awards and L1 selection. QuoteWin historically "awards" parts to suppliers (the Awards Part Number Listing export). The ACQ assignment from the Nov 2024 F2F: A = Arrow-handled suppliers, C = CAM suppliers (non-QuoteWin, non-Arrow commodity suppliers), Q = QuoteWin-handled suppliers. L1 = the winning (lowest landed cost) source per part per volume. The enhanced multilevel L1 logic (Multilevel BOM Logic CAM doc) compares for every CPN at every volume: Direct Price (buy the assembled part, existing RFQ logic incl. MOQ/SPQ/currency/excess) vs Build Price (sum of child quantities x best child costs, fully recursive down the BOM tree). Cheaper option wins: if Direct wins, the parent is L1=True and its subparts L1=False; if Build wins, children become L1 instead. FG-based rule prevents double counting: same FG repeating an Assembly-CPN pair counts once; different FGs sum.

Step 7 - Costed BOM (CBOM). QW (QuoteWin) and NQW (non-QuoteWin) data merge into the "Awards Costed BOM" (4.0 Merged BOM (QW&NQW) tab, template "Centum Costed BOM_Internal"). Costs compute per volume: Raw CBOM Proto + Raw CBOM VL-1..4 feed the finished CBOM Proto + 7.0 CBOM VL-1..4 tabs. This is where the formula layer lives (see Domain 4 doc): currency conversion, MOQ/SPQ rounding, excess inventory, scrap, NRE, build-vs-buy.

Step 8 - Reports. The output workbook carries 16 report tabs (the "CBOM Output Tabs"): Summary, Revision History, Missing Note, BOM Matrix (per volume), Excess Inventory (per volume), A-Class Parts, Batchwise Cashflow, Lead Time Consolidated, Lead Time FG Wise, Price Control, New Suppliers, Mech & EM NRE, PCB NRE & FAI Charge, Sum & Count (Detailed + regular), Part Num vs Mfg Num. Originally 13 PHP/Laravel reports built by Ultiweb; now also generated by the CAM RFQ single FastMCP tool (R01-R16 in fixed order from the ISATVON manifest).

Step 9 - Sales quote + revision cycles. The internal costed BOM goes to sales for the customer quote (LOA = Letter of Award is the customer's acceptance document the output gets reconciled against). Internal approval chain and buffer/margin rules are undefined as of 17 Oct 2026 (OPEN items, Skill 10). Revision History tabs compare quote revisions (OLD vs NEW system prices, delta, % delta).

## 4. Glossary (terms the files actually use)

- CPN: Customer/Centum Part Number. Internal part identifier; becomes the Centum item number with a CE prefix variant if the order is won (per LDM Table 1).
- MPN: Manufacturer Part Number. The buyable part identity. "Corrected MPN" = cleaned/normalized MPN.
- FG: Finished Goods assembly (top level of a BOM, Level 0).
- Level / Assembly: BOM hierarchy; Level 0 = FG, 1 = sub-assembly, 2+ = deeper.
- EAU: Estimated Annual Usage.
- Proto / VL-1..VL-4: prototype quantity and production volume tiers.
- MOQ: Minimum Order Quantity. SPQ / Pkg Qty: Standard Package Quantity (buy multiples of this).
- L1: winning (cheapest landed-cost) supplier for a part at a volume. L2 = runner-up.
- QW / NQW: QuoteWin-handled vs non-QuoteWin sourcing paths.
- AML / AVL: Approved Manufacturer List / Approved Vendor List ("Common (AML)" column marks parts common with the AML).
- NCNR: Non-Cancellable Non-Returnable.
- NRE: Non-Recurring Engineering charge. FAI: First Article Inspection charge (PCBs).
- Price Control: who controls the price - CNP (Centum Negotiated Price) vs TNP (customer/Target Negotiated Price; seen values "CNP"/"TNP" in CBOM tabs).
- Scrap factor: attrition adder by part value class: A (>= 1.25 USD) 1%, B (0.25-1.25) 2%, C (< 0.25) 5% (Scrap factor tab).
- LTB / EOL / NRFND: Last Time Buy / End of Life / Not Recommended For New Design (lifecycle risk).
- PCN / PDN: Product Change / Discontinuance Notification.
- Excess inventory: stock already on hand that offsets what must be bought (Ex Inv tabs).
- RFQ TAT: turnaround time, a named pain point.

## 5. Known pain points this process has (from the project docs)

- Manual BOM and RFQ email handling; commodity leads each reducing cost in separate spreadsheets and merging them by hand.
- No version control on Excel BOMs (multiple people editing different copies).
- Scrub BOM to Matrix BOM took ~2 days; CAM target is 2 hours.
- Not all parts managed via QuoteWin; heavy dependence on non-contracted parts adding cost.
- Supplier prices change annually; quote data goes stale.
- Discrepancies between computed output and the customer LOA (see the 1 Nov 25 discrepancy report: one project computed 3.45x the expected total).
