# Teach 6 - How mistakes get caught: specialist level

You now know the pipeline, the math, and the formulas. This last lesson is the difference between someone who can run the workbook and someone the team trusts with a quote: knowing how it fails.

## The incident that teaches everything (REAL, from the 1 Nov 25 Discrepancy Analysis Report)

A CAM output run produced a Letter of Award value **+245%** above the correct quote. Not 2.45% - two hundred forty-five. The report's analysis is the masterclass: totals that big do not come from a wrong price; they come from structural faults - duplicated aggregation, a join fanning out rows, a volume multiplier applied twice. The lessons the project took from it:

1. **Never trust a grand total you cannot decompose.** The Sum & Count tab exists so every assembly total can be split scrub-side vs CBOM-side. A +245% would light it up instantly.
2. **Counts before sums.** A duplicated join inflates row counts first. 'Is Sum Same' FALSE with equal counts = price problem; unequal counts = row problem. That one diagnostic split is the fastest triage in the domain.
3. **Cross-tab references are the danger zone.** Recall the A CLASS PARTS formula summing a VL-1 column with criteria on VL-4 columns (Teach 5, family 7). When scenarios get cross-wired, numbers stay plausible while being wrong. Audit by checking every cross-tab reference names the scenario the tab claims to be.

## The error-behavior rules of the automation (REAL, from Possible Issues & Fixes)

These tell you what the system does with bad input - which is what you must know before trusting its output:

- **CAMview upload**: header matching is exact and typo-intolerant - a mislabeled column is rejected or shows as NOT AVAILABLE, but extra columns are ignored and column order does not matter. File must be CSV/XLS/XLSX.
- **CAMail**: a supplier upload with ALL prices missing is recorded as **No Bid**. A second, conflicting upload from the same supplier **supersedes** the first - latest wins. Partial prices are accepted and reminders go out for the rest. Quotes arriving after the deadline are stored but **miss the merge window**. A manual-override upload exists for stuck suppliers.
- **CAMerge**: proceeds even if the QuoteWin file is missing or partial - merging with CAMail data alone. The Matrix BOM can be generated at any time; you do not wait for all quotes.
- Consequence for the auditor: "the system ran fine" never means "the inputs were complete." Check No Bids, late quotes, and superseded uploads before believing a CBOM.

## The six audit checks to run on any costing output

1. **Validation block scan** - uncosted line items vs expectation (546 in the sample run), diff-prices and diff-MPNs = 0, wrong-MPNs explained (6 in sample), MOQ/SPQ gaps = 0.
2. **Sum & Count triage** - for every assembly: counts match? sums match? Classify every FALSE.
3. **Matrix uniqueness** - column A of every BOM MATRIX tab has no repeated CPN. (The Matrix BOM Issue deck's canonical bug.)
4. **Currency spot checks** - pick 3 rows per currency and redo the division by hand (Teach 4). Thirty seconds, catches inversion bugs.
5. **Scenario isolation** - confirm each VL tab's cross-references point at its own Raw CBOM.
6. **Fixed-anchor totals** - any total that points at a hard-coded end row (like $V$1030) gets re-verified after any row insertion.

## The human process around the tools

The scrub instructions doc, the expert-feedback doc on costed-BOM checking, the master edge-cases doc, and the module-wise status tracker together describe a review culture: every automated output has a named human check, and every known failure mode has a row in a register. When you find a NEW failure mode, the professional move is not just fixing the number - it is adding the row to the register so the next person catches it in seconds.

## Where CAM is going (so your knowledge ages well)

The Excel pipeline you just mastered is the *specification*, not the future. CAM 4.0's single FastMCP "report" tool reproduces these 16 output tabs from a data model (LDM: Part 49 fields, Supplier 21, RFQ) via manifest -> Jinja2 -> AST-generated Python. Every formula family in Teach 5 becomes code; every validation counter becomes an automated gate. The synthesis doc and the FastMCP artifacts doc in this folder cover that architecture - read them after this lesson and you will see the workbook's shadow in every design decision.

## Final check - you are done with the series when you can

1. Take a raw client BOM and name every transformation that turns it into a CBOM row.
2. Recompute any K, N, O cell by hand.
3. Read any of the 422,645 formulas and name its family and purpose.
4. Given a wrong total, state your triage order (counts -> sums -> cross-refs -> currencies) and mean it.
5. Explain to the next newcomer why "latest upload wins" and "late quotes miss the merge" are the two supplier behaviors most likely to silently change a quote.

Series complete. The Domain 0-4 docs remain your reference shelf - keep them open while you work in the real files.
