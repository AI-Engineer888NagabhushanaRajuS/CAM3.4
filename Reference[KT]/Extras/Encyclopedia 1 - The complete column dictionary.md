# Encyclopedia 1 - The complete column dictionary (every sheet, every column, real values)

The definitive column-by-column reference. For each sheet: what the sheet IS, then every column with meaning and a REAL example value. Sources: CAM - Sample BOM.xlsx (CE-005405), the 19 Internal workbooks, the CAM 21-tab reports, CBOM_Report_RFQ_000016, QW awards exports, costing sheets, scrub BOMs. Sister docs: Encyclopedia 2 (formulas), 3 (abbreviations), 4 (rules). Domain 3 has file-level structure; this doc owns column semantics.

## 1. Scrub BOM ('1.0 Scrub BOM', 10 cols)

| Col | Header | Meaning | Real example |
|---|---|---|---|
| A | FG | Finished Good - the final sellable product this row belongs to | E16233DA |
| B | Level | Depth in the product tree; 0 = the FG itself, 1 = direct children, 2 = parts inside sub-assemblies | 0 |
| C | Assembly | The (sub-)assembly this part is consumed by | E16233DA |
| D | CPN | Centum Part Number - Centum's internal part ID; the master key for everything | 79046185 |
| E | Description | Free-text part description (often French on Thales projects) | ROND 3.2X10X0.6 |
| F | MFR | Manufacturer name as requested | ATI / ANY AVL |
| G | MPN | Manufacturer Part Number - the maker's catalog ID | A3P1000-FGG256I |
| H | Commodity | Part family; drives buyer assignment and scrap class | PCBA, Packing, FASTENERS |
| I | Quantity | Units of this part per ONE assembly | 1 |
| J | UOM | Unit of measure: NUM/NO/EA = count, M = meters | NUM |

Variant seen in the wild ('Scrub BOM (1)', 5570): 7-8 col form `Assembly Name | CPN | Description | Manufacture (Name) | MPN | Commodity | Qty | UOM` - no FG/Level; the upload step re-derives them.

## 2. SBOM Upload to QW ('3.3 SBOM Upload to QW', 9 cols)

Same as Scrub BOM minus FG/Level, plus:
| B | Sub Assembly Flag | 0 = buy this part; non-zero = Centum builds it in-house (make-vs-buy marker; priced via PCBA costing, not supplier quotes) | 0 |

## 3. QW with Prices ('3.4 QW with Prices' - the QuoteWin "Awards Part Number Listing" export, 28 cols)

Header block rows 1-8 first: Template, Project, Volume, Currency, Report On (All Prices / Selected Cost), Group By, Sort By. Then:

| Col | Header | Meaning | Real example |
|---|---|---|---|
| A | Project | Full QW project id incl. volume tag | CE-005405-THALES FLX_ PCBA FLOAT VL-04 |
| B | Part Number | CPN | A1172726 |
| C | Part Description | | 3M SCOTCH-WELD 2214 REGULAR COLLE... |
| D | Commodity | | SUB PART-ELECTROMECH |
| E | Mfg Name | Awarded manufacturer | 3M |
| F | Mfg Part Number | Awarded MPN | 2214N (150ML) |
| G | Cost #1 (Conv.) | Awarded unit cost converted to project currency (USD) | 267.48923 |
| H | Price (Original) #1 | Supplier's quoted price in their currency | 17386.8 |
| I | Currency (Original) | | INR |
| J | Supp Name | Awarded supplier | AMAR RADIO CORPCORATION (sic - real typo) |
| K | Pkg Qty | Standard package quantity (parts per reel/pack) | 6 |
| L | MOQ | Minimum order quantity | 6 |
| M | Lead Time | Weeks | 22 |
| N | Awarded Volume #1 | Volume this award applies to | 0 |
| O | Award #1 | Award share % (100 = sole winner; split awards divide) | 100 |
| P | Part Qty | Per-assembly qty echoed back | 0 |
| Q | Corrected MPN | MPN normalized/corrected by the buyer | 2214 HI-TEMP, GRAY 6 OZ CARTRIDGE, 3M |
| R | Long Comment | Supplier's free-text quote notes | QUOTE # 20966912;:NEED LOA WITH PART#... |
| S | Source #1 | Which channel/user the quote came through | SupplyWin User=alvin@amarradio.com |
| T | Price Type | Contract status of the price | NO CONTRACT |
| U | No Bid Reason | Why a supplier declined | KINDLY PROVIDE THE QTY |
| V | Short Comment | | GST EXTRA |
| W | NCNR | Non-Cancellable Non-Returnable flag (X = yes) | X |
| X | RFQ Number | | None |
| Y | Eff Date | Price effective date | 15/06/24 |
| Z | Exp Date | Price expiry date | 15/07/24 |
| AA | Quote Validity | | 3 MONTHS |
| AB | Part Status | | None |

## 4. Merged BOM ('4.0 Merged BOM (QW&NQW)', 28 cols) and Raw CBOM x5

The QW awards + non-QW manual prices merged into "Awards Costed BOM" (Template: Centum Costed BOM_Internal). Columns = QW set minus quote-process fields, plus:
| H | Ext Vol Qty #1 | Part Qty x scenario volume | 210 |
| I | Price (Splits) #1 (Conv.) | Unit price after volume-split selection + currency conversion | (computed) |
| L | Ext Price (Splits) #1 (Conv.) | I x Part Qty | |
| M | Ext Part Vol Price (Splits) #1 (Conv.) | I x Ext Vol Qty | |
| Y | MFR in Customer BOM | Manufacturer the CUSTOMER specified (vs awarded) | |
| AA | End Use Statement | Export-control/end-use declaration text | |
| AB | Supplier Type | Payment-terms bucket from supplier master | 60 DAYS |

"Splits" = volume price breaks: each Raw CBOM tab (Proto, VL-1..VL-4) picks the price valid at that volume. REAL proof across tabs, washer 79046185: Proto price 2.0 EUR/MOQ 100, VL-1 0.8 EUR/MOQ 1000, VL-2 0.8, VL-3 1.0/MOQ 500, VL-4 1.0 - the same part re-priced per volume tier.

## 5. Settings tabs

- Supplier (17 cols): Region, Supplier ID (e.g. 20001E), Name, Phone, Fax, Address #1/#2 (often misused for contact lines - real data quality mess), City, State, Postal Code, Country, Supplier Type (ADVANCE / 30 DAYS / 60 DAYS - payment terms), Currency, RFQ Method (SupplyWin(Secure)), RFQ Email(s), Notes, Time Stamp.
- Currency: code + rate-to-USD (EUR 0.93, INR 83.5, USD 1). Conversion = original / rate.
- Scrap factor: Class (A/B/C), Currency, Min/Max Value (unit-cost bands in USD), Scrap Ratio (0.01/0.02/0.05).
- Batch Qty: per Assembly, per volume scenario V1..V4: Qty (annual/batch volume), Batch Qty, Batch Count (production batching).

## 6. CBOM tabs ('CBOM Proto', '7.0 CBOM VL-1..4') - the 48-49 column core

Cols A-AD = Merged BOM fields + FG part number (A) and Assembly (B). Then the computed engine:

| Col | Header | Meaning | Real example (Proto row 25) |
|---|---|---|---|
| AE | Line No. | Stable line id within the source BOM (Line_N) | Line_10 |
| AF | Is Data | TRUE for real data rows (gates every other formula) | True |
| AG | (Proto: Is Assembly / VL tabs: Batch Qty) | assembly marker, or batching multiplier | False / 1 |
| AH/AI | Is Assembly / Parent Line No. | whether row is an assembly row; its parent line | False / Line_10 |
| AI/AJ | ABC Classification | Value class of the part: A (>$1.25), B ($0.25-1.25), C (<$0.25) - from Scrap-factor bands | A |
| AJ/AK | Scrap | Scrap ratio applied to this row | 0.01 |
| AK/AL | New Supp | Supplier not in the master list? | False |
| AL/AM | Is Price Same | Same CPN, one price everywhere? | True |
| AM/AN | Is MPN Same | Same CPN, one MPN everywhere? | True |
| AN/AO | Is Costed | Has a non-zero converted price | True |
| AO/AP | Recurring Count | How many rows share this CPN (1 = unique, 2+ = shared) | 1 |
| AP/AQ | Mfg. Part Num in Scrub Bom | MPN matches the scrub BOM | True |
| AQ/AR | MOQ Qty Present | MOQ on record (waived if uncosted/assembly) | True |
| AR/AS | Pkg Qty Present | Package qty on record | True |
| AS/AT | PKg Qty <= MOQ | Packaging consistency check | True |
| AT/AU | Assembly+Parent Line | Composite key: assembly_line | 87093547V00_Line_10 |
| AU/AV | Part Num+Line | Composite key: cpn_line | 79046185_Line_10 |
| AV/AW | FG Part Qty | Qty rolled up to FG level for report SUMIFS | 1 |

(Column letters shift by one between CBOM Proto (48) and 7.0 CBOM VL-x (49) because VL tabs insert Batch Qty at AG. This one-column shift is a classic copy-paste bug source - see Encyclopedia 2/4.)

Above the data (rows 9-22): the Assembly Summary block (per-assembly Ext Price / Ext Vol Qty / Ext Part Vol Price) and the Validation block (Count of Total CPNs 1029, Unique 846, Shared 183, Occurrences 628, Line Items 1474, Uncosted 546, diff-prices 0, diff-MPNs 0, Wrong MPNs 6, MOQ/SPQ missing 0, PKG>MOQ 0, Commodity missing 0, MOQ Cost 53470.19).

## 7. BOM MATRIX tabs (35 cols, sample; up to 44 in CAM reports)

Two-side layout. LEFT: Part Number (A), one column per Assembly (qty of part in that assembly), Grand Total, EAU (Estimated Annual Usage = Grand Total x volume). RIGHT: Description, Commodity, Mfg Name, Mfg Part Number, Unit Price in $, then per-assembly COST columns (qty x unit price), Grand Total cost, Pkg Qty, MOQ, Lead Time, Price Control. Row 2 holds scenario volumes; row 1 holds `=T2=T3` consistency guards. Rule: column A must be unique CPNs (duplicates = the documented matrix bug).

## 8. Report tabs

- Ex Inv (Excess Inventory) x5: Part Number, Description, Commodity, Mfg Name, Mfg Part Number, Part Qty, Ext Vol (Splits) #1, Excess In Stk, Excess after considering (stock), Shortage Qty, Scrap, Scrap factor, Cost #1, Ext Vol Cost (Splits) #1 - e.g. connector A1211920: need 45, scrap 1% -> buy 46, cost 3.559, ext 160.16. Headline: total MOQ/excess cost.
- A CLASS PARTS: the high-value watch list: Part Number...Cost #1, Ext Price, X (share of total spend, J=I/SUM), Ext Vol Cost, Supp Name, Pkg Qty, MOQ, Lead Time, ABC Classification, MOQ turns, Average MOQ turns in days, Price control, Remarks. Real top row: F1363842 PLATINE CONNEXIONS, $424,650 ext vol cost, 7.4% of spend.
- Batchwise Cashflow: Supplier Type buckets (30 DAYS $10,856.14 / 60 DAYS $55,159.80 / Advance $720.00, Grand Total $66,735.94) x Proto and per batch; weighted-days column.
- Lead Time Consolidated: LT in weeks | Count of Part Number | In % (histogram). Lead Time FG Wise: same per FG.
- Price Control: spend by pricing authority: Centum 61.6% / CONTRACT 38.4% / CNP 0 (RFQ-000016 real).
- New Suppliers: parts awarded to suppliers not in the master.
- Mech & EM NRE / PCB NRE & FAI Charge: one-time Non-Recurring Engineering and First Article Inspection charges per part.
- Sum & Count Detailed (16 cols): per part x per tab sums feeding Sum & Count (per assembly: Scrub sum vs Proto/VL-1..4 sums + counts + Is Sum Same).
- Part Num vs Mfg Num: Part Number | MPN | In Scrub BOM - identity reconciliation.
- Revision History: Sl No, Assembly, Part Number, Description, Commodity, Mfg, MPN, OLD System QTY, New System QTY, EAU, OLD Unit Price $, New Unit Price $, In %, OLD System Price $, New System Price $, Delta, Remarks ("Price reduction"). Variants: 'Revision history old', 'Revision history - 2FG', 'Revision history for Old vs New'.
- Summary: per assembly, per scenario: Volume + CBOM Cost; sample workbook has 3 generations side by side (cols C-N, O-X, Y-AH) + Delta + in% + CBOM Ref No. Internal versions compare two revisions (old rev vs new rev, S=Q-H deltas).
- Missing Note(s): numbered sections - uncosted parts with Quoted MFR/MPN/Price vs New MFR/Price/MOQ considered, packing-box sizes, buyer remarks.

## 9. Internal-workbook-only tabs (from the 19 real Internals)

- Quotewin Matrix / Non Quotewin Matrix (5570): same 18-col layout (Part Number, per-assembly qty, Grand Total, EAU, Description, Commodity, Mfg, MPN, Unit price, per-assembly cost, Grand Total, Pkg Qty, MOQ, Lead Time, Stock/Quote Validity, Remarks). QW side VLOOKUP-driven; NQW side hand-typed (real remark: "No stock in online").
- Internal Review (Dec-2025+ files): management pivot: cost by quote-age bucket (Within A Month 51.3%, Two Month 40.5%, One Month 8%, Above 2 Month 0.2% - 5646 real), by sourcing channel (Online 32%, Disty 40.5%, MFR 24.4%, Consolidator 3.1%), by commodity, by payment terms (CUSTOMER SUPPLY, with in 90 days, Advance Supplier).
- PCB Spec / PCB SPEC: board specs for PCB costing. Jig List / 5677-Jigs (5677): test-jig costing. '%' tabs (5605, 5619): leftover template cruft. 'CE-005399'/'CE-005078_ 1883' tabs in 5615: leftovers copied from OTHER projects - evidence of clone-and-edit assembly.

## 10. CAM 2026 'CBOM' tab (76 cols, CBOM_Report_RFQ_000016)

Cols A-N identity: bom_item_id (UUID), volume_no, fg, assembly, cpn, description, commodity, unit_of_measure_costing/_erp/_qw, final_unit_of_measure, part_qty, line_no, display_order. O-T manufacturer: mfr_in_customer_bom, mfg_name_costing/_erp/_qw, final_mfg_name, mfg_part_number. U-V volumes/prices: ext_vol_qty, price_conv_costing, price_conv_qw, final_price_conv, price_original_costing/_erp/_qw, final_price_original, currency_original_costing/_erp/_qw, final_currency_original, supp_name_costing/_erp/_qw, final_supp_name, pkg_qty_costing/_erp/_qw, final_pkg_qty, moq_costing/_erp/_qw, final_moq, lead_time_costing/_erp/_qw, final_lead_time. Then: ncnr, long_comment, price_type, exp_date, corrected_mpn, supplier_type, batch_qty, volume_qty, nre_charge, end_use_statement, scrap_percent, ext_price_conv, ext_part_vol_price_conv, price_control, is_costed, moq_qty_present, pkg_qty_present, pkg_qty_lte_moq, is_data, is_assembly, parent_line_no, abc_classification, recurring_count, mfg_part_num_in_scrub_bom, new_supplier, is_price_same, is_mpn_same. The whole helper-column engine of the Excel CBOM, as first-class database fields, with 3-source provenance per attribute.

## 11. Costing sheet (manual NQW pricing input, 21 cols)

Project, part Number, Description, Commodity, Mfg Name, Mfg Part Number, Unit, Part Qty, Price #1 (Original), Currency (Original), Supp Name, Pkg Qty, MOQ, Lead Time, NRE Charge, NRE Charge (Conv.), NCNR, Price Control, Price Type, Exp Date, Long Comment. Real: M3X8_BOLT, LPS BOSSARD, 2.43 INR, pkg 1000, MOQ 1000, LT 6.

OPEN: supplier RFQ sample formats (22/32/38-col generations) are mapped in Domain 3 - not repeated here. 'Sheet1/Sheet2/Sheet3/Sheet4' scratch tabs in Internals carry no dictionary value.
