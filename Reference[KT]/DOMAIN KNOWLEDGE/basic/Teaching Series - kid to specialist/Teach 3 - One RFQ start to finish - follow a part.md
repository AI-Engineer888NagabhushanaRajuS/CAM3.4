# Teach 3 - One RFQ, start to finish: follow a part

Level: intermediate. We follow one real part - CPN `79046185`, a washer ("ROND 3.2X10X0.6", a fastener made by SATINOX) - through every stage of the pipeline in the CE-005405 sample workbook. Every number below is REAL, pulled from the tabs.

## Stage 0 - The customer asks

Thales sends the FLX_ PCBA project BOM: 11 finished goods, ~4,900 scrub rows. Centum's job: cost it. This particular unit of work is volume scenario 4, so its QW project name is CE-005405-THALES FLX_ PCBA 11 FG - VOL - 4.

## Stage 1 - Scrub BOM (tab '1.0 Scrub BOM')

The cleaned list: 4,921 data rows, 10 columns (Teach 2). Our washer is in there with its quantity per assembly.

## Stage 2 - Upload to QuoteWin (tab '3.3 SBOM Upload to QW')

The scrub list is reshaped to QuoteWin's import format: `Assembly | Sub Assembly Flag | CPN | Description | MFR | MPN | Commodity | Quantity | UOM`. Note the extra column: **Sub Assembly Flag** - 0 means "buy this part", a sub-assembly flag means Centum builds it in-house (a make-vs-buy marker). MFR is often `ANY AVL` - any available approved manufacturer.

## Stage 3 - QuoteWin prices it (tab '3.4 QW with Prices')

QuoteWin (the legacy quoting tool, being replaced by CAMail+CAMerge) holds the supplier quotes and applies the awarded price per part. Its export - "Awards Part Number Listing" - comes back with a header block: `Project: CE-005405-THALES FLX_ ... VOL - 4`, `Volume: 1`, `Currency: USD`, `Report On: All Prices`, then per-part award rows. 16,206 rows - awards exist per part per assembly occurrence, not just per part.

## Stage 4 - Merge QW + non-QW (tab '4.0 Merged BOM (QW&NQW)')

Not everything goes through QuoteWin. Customer-supplied prices, in-house PCBA costs, and parts suppliers did not quote (NQW = non-QuoteWin) are merged in here. Output: the "Awards Costed BOM" using template "Centum Costed BOM_Internal". Its assembly summary, REAL:

| Assembly | Ext Price #1 (Conv.) | Ext Vol Qty |
|---|---|---|
| 87093547V00 | 468.04 | 5 |
| E16233DA | 298.998 | 5 |
| E17888AA | 1561.56 | 5 |

Behavior rule from the project's issues-and-fixes matrix: if the QW file is missing or incomplete, merging proceeds with the CAMail (email-quote) data alone - the pipeline degrades gracefully instead of stopping.

## Stage 5 - Settings tabs (Supplier, Currency, Scrap factor, Batch Qty)

Four small tabs steer all the math that follows (Teach 4 does the arithmetic):
- **Currency** (REAL): EUR 0.93, INR 83.5, USD 1.0 - every price is converted to USD by dividing by these.
- **Batch Qty**: per-assembly volumes per variant level.
- **Scrap factor** (REAL): parts costing > $1.25 (class A) get 1% scrap allowance; $0.25-1.25 (class B) 2%; under $0.25 (class C) 5%. Cheap parts get lost/damaged proportionally more on the line, so you buy extra.
- **Supplier**: awarded supplier attributes (payment terms etc., feeding the cashflow tab).

## Stage 6 - Raw CBOM x5 (tabs 'Raw CBOM Proto' ... 'Raw CBOM VL-4')

The merged awards fanned out per volume scenario: one tab each. This is where currency conversion and volume extension happen per part row.

## Stage 7 - CBOM x5 (tabs 'CBOM Proto', '7.0 CBOM VL-1' ... 'VL-4')

The finished product of the pipeline: per assembly, an assembly summary plus the fully costed 48-column part listing (structure in Domain 3; formula anatomy in Teach 5). Our washer's REAL row in 'CBOM Proto':

| Field | Value | Meaning |
|---|---|---|
| Part Number (C) | 79046185 | the washer |
| Part Qty (I) | 1 | one per assembly |
| Ext Vol Qty #1 (J) | 5 | 1 x 5 assemblies in this volume scenario |
| Price #1 Original (L) | 2.0 | supplier's price in original currency |
| Price #1 Conv. (K) | 2.1505 | converted to USD |
| Ext Price #1 Conv. (N) | 2.1505 | 1 x 2.1505 |
| Ext Part Vol Price (O) | 10.7527 | 5 x 2.1505 - what the washers cost across the batch |

Wait - 2.0 original became 2.1505 USD. The original was EUR: 2.0 / 0.93 = 2.1505. (Compare row 29: 14 INR / 83.5 = 0.1677 USD.) One formula family - divide by the settings-tab rate - applied hundreds of thousands of times.

## Stage 8 - The report tabs (16 of them)

From the CBOMs, the workbook derives every report the business consumes: BOM MATRIX x5 (part x assembly quantity grid), Excess Inventory x5, A CLASS PARTS (the high-value parts list), Batchwise Cashflow, Lead Time Consolidated / FG Wise, Price Control, New Suppliers, Mech & EM NRE, PCB NRE & FAI, Sum & Count (+Detailed), Part Num vs Mfg Num. Teach 4-6 dissect these.

## The pipeline in one line

Client BOM -> scrub -> QuoteWin upload -> quotes awarded -> merge QW+NQW -> 5 volume scenarios -> CBOM -> 16 reports. CAM's job is to automate every arrow: CAMview validates the input, CAMail collects supplier quotes by email, CAMerge replaces QuoteWin merging, CAMind/CAMintel handle indexing and intelligence.

## Check yourself

1. In '3.4 QW with Prices', why are there ~16k rows when the scrub BOM has ~5k?
2. What happens to a part no supplier quoted? Trace where it would surface. (Hint: J15 in the CBOM validation block - 546 uncosted line items in this run.)
3. Why does merging proceed even if the QW file is missing, and what risk does that create?

Next: Teach 4 - the arithmetic behind every money cell.
