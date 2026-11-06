# Teach 4 - The money math: engineer level

By the end you can recompute any cost cell in the workbook by hand and know whether it is right. All numbers REAL from CE-005405.

## The four building blocks

### 1. Currency conversion - divide by the settings rate

Settings tab 'Currency': EUR 0.93, INR 83.5, USD 1.0 (rates are "units of that currency per 1 USD").

`Price_USD = Price_original / rate`

- Washer 79046185: 2.00 EUR / 0.93 = **2.1505 USD** (matches cell K25, 'CBOM Proto')
- ESD bag 87093547V00-ESD: 14.00 INR / 83.5 = **0.16766 USD** (row 29)
- Master carton: 160 INR / 83.5 = **1.91617 USD** (row 30)
- Connector A1215767: 1.05 EUR / 0.93 = **1.12903 USD** (row 33)

Direction matters. Divide, because the rate is "foreign per USD". Divide the wrong way on a 16,206-row sheet and nothing looks obviously broken - until someone reconciles (Teach 6).

### 2. Extended cost - quantity x price, at two grains

- **Ext Price** = Part Qty x Unit Price: washer: 1 x 2.1505 = 2.1505
- **Ext Vol Price** = Ext Vol Qty x Unit Price: washer: 5 x 2.1505 = **10.7527** (cell O25)

Part Qty is per-assembly; Ext Vol Qty multiplies by the batch volume of the scenario. Watch for fractional quantities: the pallet row has Part Qty 0.0055556 and Ext Vol Qty 0.0277778 - extended math still just multiplies.

### 3. Scrap factor - buy extra for the parts you will lose

From the settings tab: class A (unit cost > $1.25) +1%, class B ($0.25-1.25) +2%, class C (< $0.25) +5%.

REAL from 'Ex Inv Proto' row 5: connector A1211920, need 45 for the volume, scrap factor 0.01 -> buy **46**. Row 7: PCB F1287581, need 5, factor 0.01 -> buy **6** (5 x 1.01 = 5.05, rounded up). Rounding up to whole purchasable units is where MOQ and SPQ bite next.

### 4. MOQ, SPQ, and the real purchase quantity

- **MOQ (Minimum Order Quantity)**: supplier will not sell fewer than N.
- **SPQ / Pkg Qty (Standard Package Quantity)**: parts come in reels/packs of N; you must buy whole packs.

REAL from 'A CLASS PARTS': FPGA A2028039 (MICROCHIP A3P1000-FGG256I): needed 4,418 across the volume; MOQ = 90, Pkg = 90; supplier AVNET. If the computed buy is 4,418, the real buy rounds up to the next multiple of 90 = 4,410? No - 4,418/90 = 49.09 -> 50 packs = **4,500**. The 82 extra chips are **excess inventory** - and tracking its cost is a whole report tab: 'Ex Inv Proto' headline cell = **$53,470.19** of MOQ-driven excess for this scenario. The validation block divides that by total spend (L9 = 53470.19 / 18454.45... - see the tab for the ratio) so management sees excess as a proportion, not just a number.

## The validation block - the workbook's own scoreboard (REAL, 'CBOM Proto' I9:J22)

| Metric | Value | Reading |
|---|---|---|
| Count of Total CPNs | 1029 | distinct CPNs costed |
| Count of Unique CPNs | 846 | appearing once |
| Count of Shared CPNs | 183 | used in 2+ places (1029 - 846) |
| Total Occurrences | 628 | shared-part rows beyond first |
| Total Line Items | 1474 | costed rows |
| Uncosted Line Items | 546 | NO valid price - the danger number |
| CPNs with diff. prices | 0 | same CPN, two prices - must be 0 |
| CPNs with diff. MPNs | 0 | identity conflict - must be 0 |
| Wrong MPNs w.r.t Scrub | 6 | MPN drifted from the scrub BOM - investigate |
| MOQ / SPQ Missing | 0 / 0 | missing supplier pack data |
| PKG > MOQ | 0 | packaging inconsistency |
| Commodity Missing | 0 | unclassified parts |

546 of 1,474 line items uncosted is normal for a real run (suppliers do not quote everything; some parts are customer-priced elsewhere) - but it is the number a buyer chases down. The specialist question is never "is the total right?" but "which validation counters moved and why?"

## Cashflow - when the money actually leaves

'Batchwise Cashflow' buckets awarded spend by supplier payment terms, REAL: 30 DAYS $10,856.14, 60 DAYS $55,159.80, Advance $720.00 - Grand Total **$66,735.94** for this batch. Formula trick used: `=B4 * NUMBERVALUE(LEFT(A4, FIND(" ",A4)))` parses "30 DAYS" into 30 to weight the payment timing. Excel string-parsing as business logic - remember this pattern for Teach 5.

## Check yourself

1. A part costs 250 INR. What is it in USD here? (Ans: 2.994)
2. Need 1,030 of a part, SPQ 250, MOQ 500, scrap class C. What do you buy? (1,030 x 1.05 = 1,081.5 -> round to packs of 250 -> 1,250. Excess = 168.5 units of overbuy vs need.)
3. 'Sum & Count' shows Scrub Bom Sum 128.136 for 87093547V00 but CBOM sums 126.2416 across all 5 scenarios, count constant at 26. Sums differ, counts match - what class of error does that signature point to? (A price-side change between scrub expectation and awarded cost, not a dropped part - Teach 6.)
4. Why must "CPNs with diff. prices" be 0 in a correct run?

Next: Teach 5 - the 12 formula families, decoded line by line.
