# Domain 4 - The formula layer: what the formulas actually compute

As of: 29 Oct 2026. Method: the 12MB CAM - Sample BOM.xlsx (project CE-005405 Thales FLX) was unzipped and every worksheet XML scanned for formula elements; formulas were grouped into families and read in context (column headers from the same file). No formula was guessed.

## 1. How many formulas, really

Heard number: "~50K Excel formulas". Measured in the reference workbook:
- 422,645 formula cells across 43 tabs (each shared/array-fill formula counts once per cell that carries it).
- Where they concentrate:
  - 5 CBOM tabs (CBOM Proto + 7.0 CBOM VL-1..4): 28,878-28,889 each = ~144,000
  - 5 BOM MATRIX tabs: ~17,200 each = ~86,000
  - 5 Excess Inventory tabs: 23,579-32,803 each = ~154,000
  - A CLASS PARTS: 18,456; Sum & Count Detailed: 16,716; Part Num vs Mfg Num: 1,061; Sum & Count: 630; Summary: 165; Revision History: 42; everything else: < 100 each
- De-duplicated, these collapse into roughly 12 formula families (below). So "50k" understates the cell count but overstates the complexity: the whole engine is about a dozen patterns repeated per row, per volume, per assembly.

This repetition is exactly why the 4.0 plan (one manifest-driven report generator) is feasible - and why a single wrong pattern amplifies into a 3.45x wrong total (see section 4).

## 2. The settings tables every formula reads

- Currency: EUR 0.93, INR 83.5, USD 1 (to-USD rates as of file date).
- Scrap factor: by unit-value class - A (>= $1.25): 1%, B ($0.25-1.25): 2%, C (< $0.25): 5%.
- Batch Qty: per assembly, per volume: requirement qty, batch qty, batch count.
- Supplier: supplier master with currency, type, RFQ method.

## 3. The formula families (with real formulas from the file)

F1. Currency conversion (per line, in every CBOM tab)
  =INDEX(Currency!$B$2:$B$4, MATCH('CBOM Proto'!$J3, Currency!$A$2:$A$4, 0))
Looks up the FX rate for the line's original currency. Converted price columns ("(Conv.)") = original price x this rate. Wrong or stale rates here were a confirmed incident cause.

F2. Extended cost (line roll-up)
  ='CBOM Proto'!$F10 * 'CBOM Proto'!$E10        (qty x unit price)
  =$L$11 / 'CBOM Proto'!$G$21                    (per-unit from extended)
Ext Vol Qty = Part Qty x volume; Ext Price = unit price x qty; Ext Part Vol Price = unit x volume qty. Assembly summary = sums of these.

F3. Volume/batch pull (per assembly)
  =INDEX('Batch Qty'!$C$2:$C$12, MATCH('7.0 CBOM VL-1'!$C10, 'Batch Qty'!$A$2:$A$12, 0))
Each CBOM VL tab pulls its own volume column (C/F/I/L for V1-V4) from Batch Qty by assembly name.

F4. Shared-CPN conditional roll-up (the multi-assembly parts)
  =SUMPRODUCT('CBOM Proto'!$N$25:$N$1754, --('CBOM Proto'!$B$25:$B$1754 = 'CBOM Proto'!$C10), --('CBOM Proto'!$AE$25:$AE$1754 = 'CBOM Proto'!$AH$25:$AH$1754))
Sums extended prices only for lines belonging to this assembly where the line number matches its parent line (the AE=AH guard prevents double-counting shared CPNs across assemblies). This is the formula class behind "incorrect BOM levelling" failures - get the guard wrong and shared parts multiply.

F5. Validation counters (the QA block on every CBOM tab)
  =COUNTIFS('CBOM Proto'!$AO$25:$AO$1754, "=1", 'CBOM Proto'!$AF$25:$AF$1754, TRUE)
Counts: total/unique/shared CPNs, line items, uncosted lines, price/MPN mismatches vs Scrub BOM, missing MOQ/SPQ/commodity, Pkg > MOQ violations. Real values in the sample: 1,474 line items, 1,029 total CPNs, 846 unique, 183 shared (628 occurrences), 546 uncosted lines, 6 wrong MPNs w.r.t. Scrub BOM. The flag columns behind these (Is Data, Is Assembly, Parent Line No., Is Costed, Is Price Same, Is MPN Same, Mfg. Part Num in Scrub Bom, MOQ Qty Present, Pkg Qty Present, PKg Qty <= MOQ, Assembly+Parent Line, Part Num+Line) are themselves computed helper columns.

F6. Excess inventory (Ex Inv tabs, ~30k formulas each)
  =INDEX('7.0 CBOM VL-1'!$D$25:$D$1754, MATCH(1, INDEX(('7.0 CBOM VL-1'!$C$25:$C$1754 = 'Ex Inv VL-1'!$A5) * ('7.0 CBOM VL-1'!$AH$25:$AH$1754 = FALSE), 0), 0)) & ""
  =SUMIFS('7.0 CBOM VL-1'!$AW$25:$AW$1754, '7.0 CBOM VL-1'!$C$25:$C$1754, 'Ex Inv VL-1'!$A5, '7.0 CBOM VL-1'!$AH$25:$AH$1754, FALSE)
  =MAX('Ex Inv VL-1'!$H5 - 'Ex Inv VL-1'!$G5, 0)   /   =MAX(G5 - H5, 0)
First-match lookup (excluding assembly lines, AH=FALSE) to pull part identity, SUMIFS to total the requirement, then MAX(demand,stock) arithmetic: excess in stock, shortage, net ordering qty, net excess qty/cost, final buy value. This is where "Excess Cost #1" (Rs 53,470 in the sample) comes from.

F7. A-Class parts (spend concentration)
  =INDEX(...$D$25:$D$1754, MATCH(1, INDEX((...$C$25:$C$1754 = $A3) * (...$AH$25:$AH$1754 = FALSE), 0), 0))
  =SUMIFS(...AW..., ...C..., $A3, ...AH..., FALSE)
  MOQ turns = Ext Vol / MOQ;  Average MOQ turns in days = K/R ratio columns; X = % of total spend.
Identifies the few parts that carry ~80% of cost (A class) for negotiation focus, plus how many times per year the MOQ forces over-buying.

F8. Revision history (quote-vs-quote comparison)
  =VLOOKUP($D6, '7.0 CBOM VL-4'!$C$24:$AW$1080, 2..5, 0)
  =L6 * I6   (qty x price)
  =SUBTOTAL(9, O6:O10)
Pulls the same CPN from the current CBOM, sets OLD system columns against NEW system columns, computes delta and % delta per part and per volume.

F9. BOM Matrix (the customer-facing matrix view, ~17k formulas per tab)
  T2=T3 chains carry header state; the body is:
  =VLOOKUP(T$4, 'CBOM Proto'!$C$1:$G$22, 3, FALSE)   (repeated ~6,900x per tab - one per part x assembly cell)
  plus SUMPRODUCT grand totals and a cross-check row comparing CBOM Summary vs BOM Matrix Summary per assembly. obs1.png shows this cross-check failing ("Not Matching") on a live project - the matrix is where levelling errors surface.

F10. Sum & Count (structural reconciliation)
  Detailed: =IFERROR(AVERAGEIFS('Scrub BOM (1)'!$G$2:$G$4920, ...A..., $A2, ...B..., $B2), 0)
           =IF(SUM(INDEX((...A... = $A2) * (...B... = $B2), 0, 1)) > 0, 1, 0)
  Rollup:  =SUMIFS('Sum & Count Detailed'!$C$2:$C$1394, ...A..., $A2)
Per assembly: does the Scrub BOM sum/count equal the Proto and VL-1..4 sum/count? Is Sum Same / Is Count Same flags. Catches dropped or duplicated lines between input and output.

F11. Part Num vs Mfg Num (identity check)
  =SUM(INDEX((TEXT('Scrub BOM (1)'!$B$2:$B$4920,0) = TEXT($A2,0)) * (TEXT('Scrub BOM (1)'!$E$2:$E$4920,0) = TEXT($B2,0)), 0, 1)) > 0
For every Part Number + MPN pair in the output: does that exact pair exist in the Scrub BOM? TEXT() both sides to survive number-vs-text formatting drift - a direct response to the known MPN formatting failure mode.

F12. Cashflow and lead-time analytics
  Batchwise Cashflow: =$B4 * IFERROR(NUMBERVALUE(LEFT($A4, FIND(" ", $A4))), 0)  (payment-term days parsed from text x buy value, summed per batch)
  Lead Time Consolidated: =$B5 / SUM($B$5:$B$40)  (share of parts per LT bucket)
  Price Control: =IF($C3="", "", $C3 / GETPIVOTDATA("Sum of Ext Vol Cost (Splits) #1", $A$2))  - pivot-driven spend split by Centum/TNP/CNP. (Live #REF! errors observed here in the sample file.)

## 4. How this layer fails in production (documented incidents)

From the 1 Nov 25 discrepancy report (CE-005570, output Rs 20.0 lakh vs LOA Rs 5.8 lakh, +245%) and the expert feedback doc:
1. Wrong formulas: extended cost != Qty x Price x FX x Scrap; MOQ logic applied to the wrong quantities (MOQ cost was 84.68% of the wrong total vs 5.25% expected).
2. Incorrect levelling: quantity-per-assembly not multiplied correctly across BOM levels (assembly costs 5-7x off).
3. Scrub/quote mismatch: MPN formatting (dashes, spaces, case) breaks joins; alternates not mapped to awarded lines.
4. Currency errors: wrong FX date (31-Oct vs 07-Oct rate), double conversion, USD treated as INR.
5. Price breaks: single-unit price used where the 3,000-unit tier applied.
6. UoM/pack-size confusion: per-reel vs per-piece.
7. Award precedence: cheapest or first match chosen instead of the QuoteWin-awarded supplier.
8. Phantom/duplicate lines (201 vs 199 matrix rows), revision-date mismatch.
9. Rounding policy differences (line vs assembly vs grand total).

The expert fix patterns (now the guardrails any rebuild must encode):
- mpn_norm = UPPER(TRIM(REGEXREPLACE(MPN,"[^A-Z0-9]",""))) and join order: (mpn_norm+mfr_norm) -> mpn_norm -> fuzzy-with-flag.
- buy_qty = MAX(MOQ, CEILING(required_qty / pack_size) * pack_size); effective unit = lot_price / pack_size when quoted per pack.
- FX rate from the LOA/contract date, never "today".
- rolled_qty(child) = product of all parent qty-per x top-level build qty; scrap = CEIL(rolled_qty x (1+scrap%)).
- Ext = ROUND(Qty_final x Unit_price_foreign x FX x (1+Scrap%), 2); Grand total = sum(lines) + NRE + freight + duty + packaging + testing.
- Award match check: IF(ISBLANK(Award_UnitPrice), "NO_AWARD", "OK").

## 5. What this means for CAM 4.0

- The 12 families are the complete computational contract of today's system. The FastMCP single-tool design (R01-R16 tab builders) only has to reproduce these deterministically, plus enforce the guarded variables (25 of 33 unconfirmed as of 16 Oct - mostly the business rules behind F5-F12).
- Every formula family above is a candidate acceptance check: F5's counters, F9's matrix-vs-summary cross-check, F10's sum/count flags, F11's identity check are already "tests" - they just live in Excel where they can silently rot (the #REF! errors and obs1 "Not Matching" grids are the proof).
- The Excel engine has no versioning and no recalculation guarantees (files carry cached values; several tabs are stale pastes). Moving the 12 families into code with the same names and the validation block intact is the lowest-risk migration path.
