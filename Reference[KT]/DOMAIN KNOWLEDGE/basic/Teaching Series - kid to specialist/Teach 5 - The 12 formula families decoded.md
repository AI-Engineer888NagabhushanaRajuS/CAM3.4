# Teach 5 - The 12 formula families, decoded line by line

Level: engineer+. The sample workbook holds **422,645 formula cells across 43 tabs** (XML-verified count, not a guess). But they collapse into ~12 families. Learn the families and you can read any cell in any tab. Every formula below is REAL, copied from the workbook.

First, the two structural facts that make 422k formulas manageable:

1. **Columns repeat by row.** A CBOM tab has ~1,730 rows; each formula column is the same formula copied down. 48 columns x 5 CBOM variants x 1,700 rows explains most of the count.
2. **The workbook re-computes everything per scenario.** Proto/VL-1/VL-2/VL-3/VL-4 versions of the same tab are the same formulas on different volume inputs. Multiply families by 5.

## Family 1 - Header-aware value pass-through (the `IF($C25="Part Number",...)` pattern)

REAL (CBOM Proto N25):
```
=IF('CBOM Proto'!$C25 = "Part Number", "Ext Price (Splits) #1 (Conv.)",
    IF('CBOM Proto'!$AF25, 'CBOM Proto'!$I25 * 'CBOM Proto'!$K25, ""))
```
Every computed column carries its own header: if this row is the header row, emit the column title; else if the row is a live data row (flag AF, family 3), compute; else blank. This lets the same formula blanket the whole range including headers. O25 is the volume twin: `$J25 * $K25`. The computation itself is Teach 4's extended cost - the IFs are just armor.

## Family 2 - Currency conversion

The K-column values (2.1505 from 2.0 EUR) come from a lookup of the row's currency code (column M) against the 'Currency' settings tab and a divide. One family, ~35k instances across Raw CBOM tabs.

## Family 3 - The row-alive flag (AF) and key building (AT/AU)

REAL:
```
AT25 = CONCATENATE($B25, "_", $AH25)   ->  87093547V00_Line_10
AU25 = CONCATENATE($C25, "_", $AE25)   ->  79046185_Line_10
```
Composite text keys: Assembly + line-id, CPN + line-id. These keys are how every downstream SUMIFS/COUNTIFS targets exactly the right rows across 1,700-row tabs. AH25 derives the line id from a source string with a genuinely gnarly idiom:
```
LEFT($AE25, FIND("@", SUBSTITUTE($AE25, ".", "@", LEN($AE25)-LEN(SUBSTITUTE($AE25,".",""))))...)
```
Read it inside-out: count the dots in the string (length with dots minus length without), SUBSTITUTE the LAST dot with "@", FIND the "@", and take what's left of it. "Find the last occurrence" has no native Excel function - this is the classic workaround. You will meet this idiom in production spreadsheets everywhere.

## Family 4 - Same-part consistency checks (AL/AM)

REAL:
```
AL25 = ROUND(SUMIFS($K$25:$K$1754, $C$25:$C$1754, $C25) / COUNTIFS($C$25:$C$1754, $C25), ...) = $K25
```
"Average the converted price across every row with my CPN, and check it equals my own price." If the same CPN was awarded two different prices in two assemblies, AL goes FALSE and the validation block counts it. AM25 does the same for MPNs with a `COUNTIFS(... "<>"&$G25 ...)` pattern: "count rows with my CPN but a DIFFERENT MPN - must be zero."

## Family 5 - The priced-and-buyable checks (AN/AQ/AR/AS)

AN25: `AND($K25<>"", $K25<>0)` - has a real price. AQ/AR: MOQ and Pkg Qty present and non-zero (waived when the row failed earlier checks). AS25: `$Q25 <= $R25` - Pkg Qty must not exceed MOQ. Each is one boolean column; the validation block just counts the FALSEs (Teach 4's scoreboard). This layered-flags design - many simple boolean columns, one counting block - is the workbook's central engineering pattern. It is also exactly the set of checks CAM's FastMCP report tool must reproduce in code.

## Family 6 - The validation counters (COUNTIFS over flag columns)

REAL:
```
J10 = COUNTIFS($AO$25:$AO$1754, "=1", $AF$25:$AF$1754, TRUE)   -> 1029  (total CPNs)
J15 = COUNTIFS($AN$25:$AN$1754, FALSE, $AF$25:$AF$1754, TRUE)  -> 546   (uncosted)
J18 = COUNTIFS($AP$25:$AP$1754, FALSE, $AF$25:$AF$1754, TRUE)  -> 6     (wrong MPNs)
```
And derived cells: J11 = J10 - J12 (unique = total - shared), J13 = J14 - J11 (occurrences = rows - unique). Note `COUNTIFS(..., "=1", ...)` on an occurrence-counter column AO: 1 = appears once, 2+ = shared.

## Family 7 - Cross-tab aggregation (SUMIFS with composite-key criteria)

REAL (Ex Inv Proto F5/G5):
```
F5 = SUMIFS('CBOM Proto'!$AV$25:$AV$1754, 'CBOM Proto'!$C$25:$C$1754, $A5, 'CBOM Proto'!$AG$25:$AG$1754, FALSE)
```
"Sum the per-row part qty in CBOM Proto where the CPN equals my part AND the row is not excluded (AG=FALSE)." Two-criteria SUMIFS against another tab's helper columns is how every report tab pulls its base data. The A CLASS PARTS tab does the same but deliberately mixes sources (`'7.0 CBOM VL-1'!$AW...` summed with criteria on `'7.0 CBOM VL-4'!$C...`) - cross-scenario pulls, worth a second look when auditing (see Teach 6 on why subtle cross-tab references are where incidents live).

## Family 8 - Excess / shortage clamps

REAL (Ex Inv Proto):
```
I5 = MAX($H5 - $G5, 0)   -> excess after considering stock
J5 = MAX($G5 - $H5, 0)   -> shortage
```
`MAX(x,0)` turns a signed difference into a one-sided quantity. Need 45, stock 0 -> shortage 45, excess 0. The inverse pair on adjacent columns is the idiom.

## Family 9 - The matrix cell (BOM MATRIX tabs)

Each matrix tab is parts (rows, ~1,026) x assemblies (columns, 11) with volume row 2. The cell is a lookup of "qty of part P in assembly A" and the row-1 guards like `=T2=T3` check the volume headers stay consistent. Grand Total column M sums across assemblies; column N (EAU - Estimated Annual Usage) scales by volume. The project's canonical matrix bug, from the Matrix BOM Issue deck: **CPNs must be unique down column A - a repeated CPN is the error state.** When a repeated CPN appears, one of its rows silently wins any VLOOKUP against the matrix.

## Family 10 - Reconciliation sums (Sum & Count)

REAL:
```
B2 = SUMIFS('Sum & Count Detailed'!$C$2:$C$1394, 'Sum & Count Detailed'!$A$2:$A$1394, $A2)
N2 = Is Sum Same  ->  FALSE for most assemblies in this sample
```
Per assembly: total cost from the scrub side vs each scenario's CBOM side, plus row counts. Counts equal + sums differ = price change, not lost parts (Teach 4, Q3). This tab is the auditor's first stop.

## Family 11 - String-parsed business logic (Cashflow)

REAL:
```
C4 = $B4 * IFERROR(NUMBERVALUE(LEFT($A4, FIND(" ", $A4))), 0)
```
"30 DAYS" -> LEFT up to the space -> "30" -> NUMBERVALUE -> 30; weight the spend. IFERROR(...,0) swallows the "Advance" bucket (no number). Fragile by nature - a label like "NET 30 DAYS" breaks it - but this is real-world Excel.

## Family 12 - Grand totals and ratio cells

`A2 = 'Ex Inv Proto'!$V$1030` (pull a computed total from the bottom of a range up to the headline), `A3 = SUM($A$2)`, `R1 = $R$1028 / $K$1028` (excess ratio). Totals anchored at fixed end-row addresses ($V$1030) are a fragility signature: insert rows past 1030 and the headline quietly goes stale.

## Check yourself

1. Write the AL25 check from family 4 for MPN instead of price (compare with AM25's actual approach - why is COUNTIFS-with-not-equal more robust than average-and-compare for text?)
2. Why do families 4-6 compute booleans per row and count them centrally, instead of one mega-formula? (Debuggability: you can filter a column and SEE the failing rows.)
3. A matrix VLOOKUP returns the price for CPN X. The matrix has X twice. What do you get, and which project document warned about it?

Next: Teach 6 - how the professionals catch the mistakes.
