# Encyclopedia 3 - Every abbreviation and full form

Alphabetical. Every term attested in the real files/docs; source noted. When expansion is inferred from context rather than stated in a source, it is marked (inferred). Nothing invented.

## Identifiers and parts
- BOM - Bill of Materials: the complete parts list of a product. (everywhere)
- CPN - Centum Part Number: Centum's internal part ID; the master key. (Scrub BOM col D)
- MPN - Manufacturer Part Number: the part maker's catalog ID. (Scrub BOM col G)
- MFR - Manufacturer (the company that makes the part; not the seller). (col F)
- FG - Finished Good: the final sellable product. (col A)
- EAU - Estimated Annual Usage: annual consumption of a part = per-unit qty x annual volume. (matrix col N)
- AVL - Approved Vendor List; "ANY AVL" in MFR = any approved manufacturer acceptable. (SBOM upload, inferred expansion - standard industry term; the files use it as a value, not spelled out)
- AML - Approved Manufacturer List (related concept; appears in industry usage, not explicitly in these files - listed because buyers use it interchangeably with AVL; mark as context, not file-attested)

## The pipeline artifacts
- RFQ - Request for Quotation: asking suppliers to quote prices for a parts list. (everywhere)
- SBOM - Scrubbed BOM: the cleaned, standardized BOM. Also written Scrub BOM. ('3.3 SBOM Upload to QW')
- CBOM - Costed BOM: the BOM with awarded prices and computed costs. ('CBOM Proto' etc.)
- QW - QuoteWin: the legacy quoting tool (supplier quotes, awards, exports). ('3.4 QW with Prices')
- NQW - Non-QuoteWin: pricing that bypasses QuoteWin (manual costing sheet, customer prices, in-house PCBA). ('4.0 Merged BOM (QW&NQW)')
- LOA - Letter of Award / Letter of Authorization: the document committing the award; the +245% incident was an LOA value error. (QW long comment "NEED LOA WITH PART#", discrepancy report)
- VL / VL-1..VL-4 - Volume Level: pricing scenario at a given build volume. Proto = prototype volume. (Batch Qty tab)
- FLOAT - a QW project/RFQ status tag used in project names (CE-005405... FLOAT VL-04): the open/quoted stage in QW's workflow (expansion of the tag itself not spelled out in sources - mark OPEN).
- Rev - Revision of a BOM/quote (Rev 0..4). Revisions re-run the pipeline and feed Revision History.

## Buying and pricing
- MOQ - Minimum Order Quantity: smallest quantity a supplier will sell. (col L/R)
- SPQ - Standard Package Quantity: parts per package/reel; you buy whole packs. Same concept as Pkg Qty in these files. (validation block "SPQ Missing Count" vs column "Pkg Qty" - both used)
- LT - Lead Time: weeks from order to delivery. (col M/S)
- NRE - Non-Recurring Engineering: one-time setup/engineering charge. (col R/T; Mech & EM NRE tab)
- FAI - First Article Inspection: validation of the first produced units; charged once. (PCB NRE & FAI Charge tab)
- NCNR - Non-Cancellable Non-Returnable: order can be neither cancelled nor returned (X = yes). (col W)
- CNP - Customer Negotiated Price (price-control category; attested as a value, expansion inferred from Price Control context: customer-set pricing). Also seen: Centum (Centum-negotiated), CONTRACT (contract price), CUSTOMER SUPPLY (customer provides the part).
- DNQ - Do Not Quote: commodity/part class excluded from quoting. (5530 Internal Review commodity bucket)
- ESD - Electrostatic Discharge (ESD bags/covers in packing rows). 
- UOM - Unit of Measure. Values: NUM / NO / EA (count), M (meters).
- NC / NA - (not attested; skip)
- ABC Classification - value class of a part by unit cost: A > $1.25, B $0.25-1.25, C < $0.25 (drives scrap 1%/2%/5%). (Scrap factor tab)
- MOQ turns - how many times annual usage covers the MOQ-driven buy; "Average MOQ turns in days" = days of stock the MOQ forces. (A CLASS PARTS)
- Price Control - who set the price: Centum / CNP / CONTRACT / CUSTOMER SUPPLY. (Price Control tab)
- Price Type - contract status: e.g. NO CONTRACT. (QW export col T)
- No Bid - supplier declined to quote; reason recorded (e.g. "KINDLY PROVIDE THE QTY"). (col U)
- Ex Inv - Excess Inventory: stock bought beyond need (MOQ/SPQ/scrap rounding). (Ex Inv tabs)

## Sourcing channels (from Internal Review pivots)
- Disty - Distributor (Avnet, Mouser...). MFR = bought direct from manufacturer. Consolidator - a bundling intermediary. Online - catalog e-commerce (no stock in online = unavailable). (5646/5530 Internal Review, real percentages)

## Companies, tools, systems
- EMS - Electronics Manufacturing Services: Centum's industry (building electronics designed by customers).
- OEM - Original Equipment Manufacturer: the customer who designed the product (Thales, Hitachi, Knorr Bremse, Lam Research, Mahle, Crane, Idemia, Rafael, Signata, TI Clean Mobility - all real project customers).
- ERP - Enterprise Resource Planning; Centum's is InforLN (Infor LN). Feeds ERP-side price/UOM columns (attr_erp). 
- SupplyWin - Centum's supplier-portal/RFQ channel ("SupplyWin(Secure)", quotes arrive "SupplyWin User=..."). (Supplier tab, QW Source col)
- Drills - legacy internal reporting tool being replaced by CAMerge. (project docs)
- Findchips - component search/pricing service used in the toolchain. (project docs)
- CAM - Centum Automation Modules: CAMview (BOM validation), CAMail (email RFQs), CAMerge (merging/Drills replacement), CAMind (Q&A/index), CAMintel (intelligence). (project docs)
- LDM - Logical Data Model: Part (49 fields), Supplier (21), RFQ tables. (LDM sheet)
- MCP / FastMCP - Model Context Protocol / the Python server framework CAM 4.0's report tool is built on. (FastMCP artifacts doc)
- DB - DuckDB / database layer in the enrichment pipeline (BOM.zip). DigiKey/Mouser/element14 - component distributors with pricing APIs used for enrichment.
- SOW - Scope of Work (CAM Original Scope of Work.pdf).
- SLA - Service Level Agreement (used generally; not file-attested - context only).

## Output/incident vocabulary
- Sum & Count - reconciliation report (scrub-side vs CBOM-side totals per assembly). 
- Part Num vs Mfg Num - identity reconciliation report.
- Internal Review - management pivot tab (quote-age, sourcing channel, commodity, payment terms).
- Jig - test fixture for board testing (Jig List, 5677-Jigs).
- RTU - Remote Terminal Unit (Hitachi project). BMS - Battery Management System (TI Clean Mobility). PCBA - Printed Circuit Board Assembly; PCB - the bare board. CCA - Circuit Card Assembly (Rafael). HCV - Heavy Commercial Vehicle. LVVFD - Low Voltage Variable Frequency Drive (Hitachi Hirel product, inferred). HEC - (Knorr project code, expansion not attested - OPEN). PAAG - Thales LAS_UK product code (expansion OPEN).

## Software/data terms in these files
- Splits - volume price breaks: the price valid for a given volume tier ("Price (Splits) #1"). "#1" = first volume break.
- Conv. - Converted (to USD at the settings-tab rate).
- Ext - Extended (qty x price).
- Vol - Volume.
- Magic URL - the per-supplier one-click quote link CAMail emails. (issues matrix)
- Manifest - the JSON skill/spec that generates a CAM 4.0 tool (manifest -> Jinja2 -> AST -> FastMCP). (architecture docs)
- Golden file - a known-good output used as a regression baseline (RE 2 recommendation).
