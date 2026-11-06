# Encyclopedia 4 - The rules and the web around the files

The domain logic a specialist carries in their head: procurement rules, costing rules, supplier management, and how the toolchain interlinks. Everything grounded in the files; unknowns marked.

## 1. The procurement rules

**R1. Awarding.** Per part, QuoteWin records the awarded supplier, Award share % (100 = sole source; splits possible), and the awarded volume tier. Award criteria visible in the data: price, MOQ, lead time, quote validity, NCNR, and whether the supplier answered at all (No Bid reasons logged verbatim, e.g. "KINDLY PROVIDE THE QTY").

**R2. Price breaks ("Splits").** Suppliers quote per volume tier. The system re-prices every part per scenario: REAL washer 79046185 - Proto 2.0 EUR (MOQ 100), VL-1/VL-2 0.8 EUR (MOQ 1000), VL-3/VL-4 1.0 EUR (MOQ 500). Note the non-monotonic real-world mess: a middle tier can be pricier than a lower one; the pipeline takes what QW awards, it does not sanity-sort tiers.

**R3. Buy quantity = f(need, scrap, MOQ, SPQ).** Need = part qty x scenario volume (+ batching). Scrap adds class-based extra (A 1%, B 2%, C 5%). Then round UP to MOQ and whole packages. The difference between buy and need is excess inventory, costed per part and totalled (sample: $53,470.19; RFQ-000016: $131.47 on a mostly-uncosted run).

**R4. Currency normalization.** Every price converts to USD by dividing original by the settings rate (EUR 0.93, INR 83.5 in the sample; INR 85.6 in 5570 - rates are per-project, per-day). NRE charges convert the same way (NRE Charge vs NRE Charge Conv.).

**R5. Payment terms drive cashflow.** Supplier master types (30 DAYS / 60 DAYS / ADVANCE) bucket the awarded spend; the report weights by parsed days. Advance payment is a supplier-selection cost factor, not just finance trivia.

**R6. Quote validity and expiry.** Eff Date / Exp Date / Quote Validity (e.g. 3 MONTHS) bound how long a price can be used. The Internal Review tab's quote-age buckets (Within A Month / One Month / Two Month / Above 2-3 Month) exist because stale quotes are a real risk: cost share by quote age is a management health metric (5646: 51.3% within a month, 0.2% above 2 months).

**R7. NCNR changes the risk profile.** An NCNR (X-flagged) award commits Centum regardless of the customer's final order - buyers treat NCNR parts specially in review.

**R8. No Bid is data, not absence.** CAMail records all-missing-price uploads as No Bid; partial quotes are accepted with reminders for the rest; latest upload supersedes; post-deadline quotes are stored but miss the merge window; manual override exists. (Possible Issues & Fixes, verified.)

## 2. The costing rules

**R9. Two cost grains.** Per-assembly (Ext Price = qty x unit) and per-scenario (Ext Part Vol Price = ext vol qty x unit). The assembly summary and all roll-ups use the SUMPRODUCT filtered-sum pattern.

**R10. ABC classification.** By converted unit cost: A > $1.25, B $0.25-1.25, C < $0.25. Drives scrap % and the A CLASS watch list (with MOQ turns: how long MOQ-forced stock lasts - an inventory-risk metric).

**R11. Price Control split.** Spend is attributed by who set the price: Centum / CONTRACT / CNP / CUSTOMER SUPPLY. Real split RFQ-000016: Centum 61.6%, CONTRACT 38.4%. This is a negotiating-leverage KPI: the more spend under Centum's control, the more room to negotiate.

**R12. NRE and FAI are one-time.** Kept on separate tabs (Mech & EM NRE, PCB NRE & FAI) so unit-cost analysis isn't polluted by one-offs.

**R13. Make vs buy.** Sub Assembly Flag = in-house assemblies, priced by PCBA costing, not supplier quotes; they appear as PCBA-commodity rows with ANY MANUFACTURER and zero/rolled-up cost.

**R14. Revision deltas are the business conversation.** Summary compares revisions (S=Q-H per assembly), Revision History itemizes part-level old-vs-new with remarks ("Price reduction"). The +245% incident is why any large unexplained delta is a stop-the-line event.

## 3. Supplier management

**R15. The supplier master is the backbone.** 2,146 suppliers with ID, region, currency, payment terms (Supplier Type), RFQ method (SupplyWin(Secure)) and RFQ emails. New Suppliers tab flags awarded suppliers missing from the master - master-data hygiene is a costing dependency, not admin trivia (unmapped = zeroed cashflow bucket "(unspecified)").

**R16. Channel mix is managed.** Consolidator / Disty / MFR / Online split is reviewed per project (Internal Review). Each channel has different LT, MOQ and price-type behavior; online quotes carry "No stock in online" availability caveats.

**R17. Commodity taxonomy drives ownership.** ACTIVE, PASSIVE (D&A), ELECTROMECHANICAL -1/-2, PCB, PCBA, FASTENERS, PACKING, DOCUMENT, Software, Sub Assembly Active/Electromech, Consumable, DNQ... The Commodity Master & Data Cleansing project exists because commodity naming drifted across projects (SUB PART-ELECTROMECH vs ELECTROMECHANICAL -1 vs Sub Assembly Electromech) - and scrap class, buyer assignment and A-classing all key off it.

## 4. The toolchain web (how the systems connect)

Customer BOM -> (scrub, CAMview validation) -> SBOM upload -> QuoteWin/SupplyWin collect quotes -> awards export (FLOAT) + manual costing sheet (NQW) + customer prices -> merge (CAMerge, tolerates missing QW) -> Raw CBOM per scenario -> CBOM (48/49 cols, validation engine) -> 16 reports -> Summary/Revision compare -> Internal workbook -> LOA. InforLN ERP supplies ERP-side attributes (attr_erp in the 76-col model). Findchips + distributor APIs (DigiKey/Mouser/element14 in BOM.zip) enrich part data. CAM 4.0 re-implements the whole chain on the LDM (Part/Supplier/RFQ) via FastMCP tools generated from JSON manifests.

**R18. Every hop is a place where identity can break.** CPN vs MPN vs Corrected MPN vs MFR-in-customer-BOM vs awarded MFR: five identities per part. The validation counters (diff MPNs, wrong MPNs w.r.t. scrub, Part Num vs Mfg Num report) exist because each hop can silently re-map a part.

**R19. Volume scenarios multiply everything.** 5 scenarios x every computation. The Batch Qty tab's per-assembly volumes (850/630/420/210...) drive the fan-out; matrix row-2 volume headers and their =T2=T3 guards keep scenarios aligned.

**R20. Human gates remain.** Scrub (human+CAMview), costing sheet (buyer), Non-QW matrix (buyer), Internal assembly (buyer/reviewer), expert check, discrepancy analysis, edge-case register. CAM automates hops; the accountability pattern is gates + registers (Teach 6).

## 5. Interlinked-but-outside topics a specialist also knows (grounded leads, not deep-dives)

- Export control: End Use Statement column - defence customers (Rafael, Thales) require end-use declarations; this constrains which suppliers/quote data can flow where. (column attested; process detail OPEN)
- GST/tax: supplier comments "GST EXTRA" - quoted prices exclude Indian GST; comparison must normalize. (attested value)
- INCOTERMS/freight: not attested in these files - mark OPEN; real Centum costing surely handles freight, but these workbooks don't show where.
- Quality/inspection: FAI charges and PCB spec tabs are the visible edge of the quality process.
- Data enrichment: corrected MPN, commodity cleansing, distributor API enrichment (BOM.zip) - the part-data quality layer that everything above silently depends on.
