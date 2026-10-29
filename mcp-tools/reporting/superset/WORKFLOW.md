# The Complete Reporting Workflow

This document explains the reporting engine end to end — the business and technical
journey from raw input data to a finished, formatted Excel workbook. It is not a
file-by-file code tour; it's the *why* and *what happens* behind each stage. For the
code itself, see the module docstrings referenced throughout, and `README.md` for
setup/usage.

---

## Step 1 — Input Data

### The four input tables, and how they relate

The engine's entire input surface is four DuckDB tables, always scoped by a single
`rfq_id` column present on all four:

| Table | What it holds | Business role |
|---|---|---|
| `scrub_bom_items` | One row per BOM line: FG, Assembly, CPN, Description, Manufacturer, MPN, Commodity, Quantity, Part Status, Inventory Stock, etc. | The customer's engineering BOM — *what* needs to be built, in what quantities, organized into Finished Goods (FGs) and Assemblies. |
| `quote_win` | One row per supplier quote: Part Number, Mfg Name/Part Number, Cost (per volume), Currency, Supplier Name, Pkg Qty, MOQ, Lead Time, Price Type, NCNR, etc. | *What it costs* — every supplier's quoted price for every part, at every volume tier the customer requested pricing for. |
| `batch` | One row per (FG, Volume): the batch build quantity. | How many units of an FG get built *per batch* at a given volume tier — feeds the "Batch Qty" calculations. |
| `volume` | One row per (FG, Volume Name): the FG's total Volume Qty (EAU). | The total annual/volume-tier quantity for an FG — feeds "Ext Vol Qty" and every FG-level quantity multiplier. |

**A confirmed naming quirk worth knowing**: `volume.batch_qty` is *not* a batch quantity —
it holds Volume Qty (EAU) despite the column name (almost certainly copied from the
`batch` table's own DDL). Every query in this module aliases it explicitly (`volume_qty`)
rather than trusting the raw column name at the call site.

### The relationship between the four tables

`scrub_bom_items` is the backbone — every other table joins back to it:

- `quote_win.part_number` joins to `scrub_bom_items.cpn` (a part can have **many** quotes
  from different suppliers; see the tie-break logic in Step 2 for how "the" quote for a
  part gets chosen).
- `batch.fg` / `volume.fg` join to `scrub_bom_items.fg`, further keyed by a volume label
  (`batch.volume` / `volume.volume_name`, e.g. `"V1"`, `"V2"`) that corresponds to the
  numeric volume tiers found in `quote_win`'s `awarded_volume_{n}`/`cost_{n}_conv` column
  suffixes.

### How `rfq_id` scopes the pipeline

Every one of the four input tables, the generated `cbom` table, and all 16 report tables
carries an `rfq_id` column, and every query in the engine filters `WHERE rfq_id = ?`.
This means:

- **Multiple RFQs coexist safely** in the same three databases — generating or exporting
  one RFQ never touches another's rows.
- **Regeneration is scoped and safe**: calling `cbom(rfq_id)` or `generate_reports(rfq_id)`
  again for the same RFQ clears only that RFQ's `cbom`/report rows (respectively) and
  rebuilds them — it's idempotent, not additive (re-running twice produces identical row
  counts, not double the rows).
- **The three public MCP tools need only one input** — `rfq_id` — because everything else
  (which database, which tables, which SQL) is already scoped/resolved internally.

`rfq_id` itself isn't always present in raw exported data — see `migrations.py` and the
README's "Database Setup" section for how it gets backfilled onto a freshly-loaded
`input_db.duckdb` that doesn't have it yet (typically derived from `quote_win.project`,
the one identifier reliably present in a QuoteWin export).

---

## Step 2 — CBOM Generation

CBOM generation (`cbom_generator.generate_cbom`, SQL in `queries.py`) is the heart of the
engine: it takes the four input tables and produces one row per **(BOM line, volume)** —
the merged, priced, classified view every downstream report reads from.

### Table joins

For each detected volume `n` and each `scrub_bom_items` row:
```
scrub_bom_items s
  LEFT JOIN selected_quote q  ON q.part_number = s.cpn AND q.volume_no = n
  LEFT JOIN batch  b          ON b.fg = s.fg AND b.volume = 'V' || n
  LEFT JOIN volume vol        ON vol.fg = s.fg AND vol.volume_name = 'V' || n
```
`selected_quote` is a view built fresh per generation run (see "QuoteWin tie-breaking"
below) — CBOM never joins raw `quote_win` directly.

### QuoteWin tie-breaking

A single part can have dozens of competing supplier quotes in `quote_win` (real test data
showed up to 262 quotes for one part number). Since `cbom` needs exactly one row per
(part, volume), the engine picks a winner with a simple, deterministic rule:

1. Prefer a row where `award_{n}` is populated (an explicitly awarded quote).
2. Otherwise, prefer the lowest resolved cost (`cost_{n}_conv`, falling back to a
   currency-converted `price_original_{n}` if the pre-converted column is empty).

This is implemented once, as a `ROW_NUMBER() OVER (PARTITION BY part_number ORDER BY
(award_n IS NULL), price_conv)` window, keeping only `rn = 1` — see
`queries.build_volume_tie_break_cte`.

### Currency conversion

`quote_win.cost_{n}_conv` is usually already pre-converted to USD by the source system —
but when that column is empty and only `price_original_{n}` + `currency_original` are
populated, the engine converts using a small fixed rate table (`currency.py`):
`USD=1.0, INR=83.5, EUR=0.93`. Any other currency resolves to `NULL` rather than being
silently guessed at.

### Inventory usage

`scrub_bom_items.inventory_stock` (the customer's on-hand stock for a part) is the real
input to the Excess Inventory calculation (Step 3, Ex Inv VL) — it is *not* copied into
`cbom` directly, but joined in at report-generation time.

### Batch & Volume logic

`cbom.batch_qty` and `cbom.volume_qty` are the *raw* per-FG inputs from the `batch`/
`volume` tables, copied through unmultiplied. The *per-part* Batch Qty / Ext Vol Qty
shown in the exported CBOM VL sheet are a further business calculation — see Step 6.

### Supplier selection

The winning quote's `supp_name`, `supplier_type`, `pkg_qty`, `moq`, `lead_time`,
`corrected_mpn`, `ncnr`, and `price_type` all flow straight from `selected_quote` into
`cbom` — this is "the" supplier for that part/volume from here on.

### Every other transformation performed before CBOM is stored

- **Price Control bucket** (`price_control`): `price_type` normalized into
  `Customer` / `CNP` / `Centum` / a passthrough named-contract label.
- **Scrap Factor** (`scrap_percent`): a price-threshold rule —
  `price > 1.25 → 1%`, `price > 0.25 → 2%`, else `5%` (a missing price also defaults to 5%).
- **ABC Classification**: the same price thresholds, bucketed into `A`/`B`/`C`.
- **Is Data / Is Assembly**: derived from `scrub_bom_items.level` (`'0'` = an assembly
  header row, anything else = a real costed part row).
- **Recurring Count**: a running count of how many times this CPN has appeared so far
  within this volume, in true Scrub-BOM row order (`display_order`) — the backend
  equivalent of the CBOM VL sheet's live Excel formula.
- **Is Price Same / Is MPN Same**: whether this row's price/MPN matches the average/only
  value across every row sharing this CPN within this volume — again, backend equivalents
  of live Excel formulas on the exported sheet.
- **Mfg Part Number in Scrub BOM**: a normalized `(CPN, MPN)` set-membership check against
  the *original* Scrub BOM (not just this row's own MPN column).
- **New Supplier**: always `TRUE` for a real data row — this mirrors a confirmed quirk in
  the reference production workbook itself (no real "did the supplier change" comparison
  exists there either, despite the field's name).

The result is inserted into `cbom.duckdb`'s `cbom` table, scoped to this `rfq_id`.

---

## Step 3 — Report Generation

All 16 reports read from `cbom` (plus, for a handful of fields `cbom` doesn't carry, the
raw input tables directly). Each gets its own table in `reports.duckdb`.

| # | Report | Purpose | Input tables | Major calculations | Output table |
|---|---|---|---|---|---|
| 1 | BOM Matrix | Per-part, per-FG, per-volume pricing matrix | `cbom`, `scrub_bom_items`, `volume` | FG occurrence counts, per-FG/volume pricing, Excess Info lookups | `bom_matrix_report` |
| 2 | Part Num Vs Mfg Num | Flags quoted-vs-declared MPN mismatches | `scrub_bom_items`, `selected_quote` | Set-membership check of quoted MPN against every Scrub-BOM MPN for that CPN | `part_num_vs_mfg_num_report` |
| 3 | PCB NRE & FAI Charge | NRE charge rollup for PCB parts | `scrub_bom_items`, `cbom` (volume 1 only) | Filter to `commodity = 'PCB'`, dedup one row per CPN | `pcb_nre_fai_charge_report` |
| 4 | Mech & EM NRE | Same, for Mechanical/EM parts | same as above | Filter to Mechanical/Electromechanical | `mech_em_nre_report` |
| 5 | Missing Notes | 14 independent QA-flag sections (uncosted parts, price-control mismatches, NCNR, expiring quotes, etc.) | `scrub_bom_items`, `selected_quote` | Per-section boolean flags/comparisons | `missing_notes_report` |
| 6 | Lead Time (FG Wise) | Lead-time bucket counts, per FG | `scrub_bom_items`, `selected_quote` | Group by (FG, lead time), count | `lead_time_fg_report` |
| 7 | Lead Time Consolidated | Same, BOM-wide | same | Group by lead time, count + percentage | `lead_time_consolidated_report` |
| 8 | Sum & Count | Per-Assembly quantity/coverage rollup | `scrub_bom_items`, `selected_quote` | Sum/count of Scrub BOM quantity vs. quoted coverage per volume | `sum_and_count_report` |
| 9 | Sum & Count Detailed | Same, at (Assembly, CPN) granularity | same | same, one more grouping level | `sum_and_count_detailed_report` |
| 10 | Revision History | Old-vs-New quote comparison per CPN | `scrub_bom_items`, `cbom` | New-side values from `cbom`; Old-side requires a revision-tracked source not yet available (see README limitations) | `revision_history_report` |
| 11 | A CLASS PARTS | ABC cost classification rollup | `scrub_bom_items`, `cbom` (volume 1) | Dedup one row per CPN, `pct_of_total` cost share | `aclass_parts_report` |
| 12 | Price Control | Centum/CNP/Customer/Contract bucket totals, last volume only | `cbom`, `scrub_bom_items`, `volume` | `price_conv × volume_qty`, grouped by price-control bucket | `price_control_report` |
| 13 | Summary | Per-FG/volume cost + MOQ-cost-percentage rollup | `scrub_bom_items`, `cbom`, `volume`, Ex Inv VL calc | Aggregated BOM qty, ext cost, MOQ cost, percentage | `summary_report` |
| 14 | Batchwise Cashflow | Payment-term cashflow rollup by supplier type | Ex Inv VL calc, `cbom` | Sum of final/after-buy value, grouped by supplier type + volume | `batchwise_cashflow_report` |
| 15 | 7.0 CBOM VL | The master per-part-per-volume table (raw `cbom`, one tab per volume in Excel) | `cbom` | (already computed in Step 2) | `cbom_vl_report` |
| 16 | Ex Inv VL | Excess-inventory / buy-ahead cashflow calculation | `cbom`, `scrub_bom_items.inventory_stock` | Shortage/scrap/net-order/net-excess/final-buy-value chain (see `queries.ex_inv_calc_sql`) | `ex_inv_vl_report` |

All 16 are generated in one pass (`report_generator.generate_reports`), each independently
— one report's SQL failing doesn't stop the others from being attempted, so a single
generation call surfaces every problem at once rather than stopping at the first.

---

## Step 4 — Database Flow

```
input_db.duckdb  (scrub_bom_items, quote_win, batch, volume)
        ↓  read-only
cbom.duckdb      (cbom)
        ↓  read-only
reports.duckdb   (16 report tables)
```

### Why three separate database files, not one

- **`input_db.duckdb` is the system of record for raw uploaded/imported data.** It is
  opened **strictly read-only** by every part of this module except `migrations.py`
  (a separate, explicitly-invoked, one-time setup step — see README). This is a hard
  guarantee, not a convention: `database.connect()` attaches it with `(READ_ONLY)`, so an
  accidental write anywhere in the generation/export code is a DuckDB error, not silent
  data corruption.
- **`cbom.duckdb` is a derived, disposable artifact.** It can be deleted and regenerated
  at any time from `input_db.duckdb` with no data loss — it exists as its own file (not a
  table inside `input_db.duckdb`) specifically so it's obvious it's regeneratable, and so
  regenerating it never risks touching the real input data.
- **`reports.duckdb` is likewise fully derived** — from `cbom.duckdb`, which is itself
  derived from `input_db.duckdb`. Separating it from `cbom.duckdb` keeps the "raw
  per-part-per-volume data" and "the 16 business reports built from it" as independently
  regeneratable stages — you can wipe and rebuild all 16 reports without touching CBOM,
  or vice versa.

### The atomicity consequence of this separation

DuckDB does not allow a single transaction to write to more than one attached database.
So CBOM generation and report generation are two **separate** stages, each its own
transaction, fully atomic on its own database — and, per the MCP tool split below, they
are also independently *callable*, not just internally separate: `generate_reports`
never regenerates CBOM itself, it only reads whatever CBOM data currently exists. If
report generation fails, CBOM (generated by an earlier `cbom` call) is untouched — a
real, deliberate limitation, not hidden; re-running either stage is always safe
regardless, since both clear-then-regenerate rather than append.

---

## Step 5 — MCP Workflow

```
cbom(rfq_id)
        ↓
  clear_cbom_rfq(rfq_id)        [transaction]
  generate_cbom(rfq_id)
        ↓
  cbom.duckdb updated
        ↓
generate_reports(rfq_id)
        ↓
  guard: cbom rows exist for rfq_id? (raises if not -- call cbom first)
        ↓
  clear_reports_rfq(rfq_id)     [transaction]
  generate_reports(rfq_id)       (all 16, one pass, reads existing cbom.duckdb)
        ↓
  reports.duckdb updated
        ↓
export_reports(rfq_id)
        ↓
  read cbom + 16 report tables (read-only, no regeneration)
        ↓
  reshape into each report's payload shape
        ↓
  dispatch into the 16 already-verified sheet builders
        ↓
  Formatted Excel Workbook (.xlsx)
```

The MCP server (`mcp_server.py`) exposes exactly these three entry points as FastMCP
tools, called in order. Internally, `cbom` calls `reporting_pipeline.run_cbom(rfq_id)`,
which orchestrates `cbom_generator` inside its own transaction. `generate_reports` calls
`reporting_pipeline.run_pipeline(rfq_id)`, which orchestrates `report_generator` inside
its own transaction, reading whatever `cbom_generator` last wrote. `export_reports` calls
`exporter.export_excel(rfq_id)`, which never touches `generate_cbom`/`generate_reports` —
all three tools are independent: you can export whatever the last successful `cbom` +
`generate_reports` calls produced, at any later time, without regenerating anything.

The consuming application only ever sees `rfq_id` in and a result dict out — no database
paths, SQL, or internal function names cross that boundary.

---

## Step 6 — Excel Export

### Workbook generation

`exporter.export_excel(rfq_id)` builds one `openpyxl.Workbook`, in a fixed order: a raw
**"CBOM"** tab (this module's own addition — a literal-value dump of the full `cbom`
table across all volumes, since no single-volume cross-sheet formula would make sense for
a combined view), then the 16 report tabs in production's own tab order, then one
**"7.0 CBOM VL-{n}"** and one **"Ex Inv VL-{n}"** tab per detected volume.

### Sheet ordering

Fixed and deterministic — the same order every time, matching the reference production
workbook's own tab layout (verified directly against a real reference file during
development), so the exported workbook is immediately familiar to anyone used to the
original engineering tool.

### Formatting

Every sheet uses the same verified palette: navy (`#2F5496`) bold-white headers, light
blue (`#F2F6FC`) data rows, thin black borders, frozen header rows, auto-sized columns.
Money columns are formatted to exactly 4 decimal places; percentage columns (e.g. Scrap
Factor) use Excel's native percentage format rather than a raw decimal fraction.

### Formula generation / why formulas are exported instead of static values

Wherever the **reference production workbook** itself uses a live Excel formula for a
column, this module reproduces that exact formula — transcribed byte-for-byte from a real
reference workbook, not re-derived from guesswork — with **relative, row-dynamic cell
references** (e.g. `=IF($AF{r}, $I{r} * INDEX($F${start}:$F${end}, MATCH($A{r},
$C${start}:$C${end}, 0)), "")`, where `{r}` is substituted per row and `{start}`/`{end}`
are the sheet's own dynamically-computed Assembly Summary range). This means:

- **BOM MATRIX, A CLASS PARTS, PCB/Mech NRE, Sum & Count(/Detailed)** — Description,
  Commodity, Mfg Name, MPN, and cost columns are live `INDEX/MATCH` lookups into the CBOM
  VL sheet, not static values.
- **7.0 CBOM VL** — Ext Price, Ext Part Vol Price, NRE Charge (Conv.), Is Assembly, Parent
  Line No., Is Costed, MOQ/Pkg Qty Present, PKg Qty <= MOQ, Assembly+Parent Line,
  Part Num+Line, **Is Price Same, Is MPN Same, Recurring Count, Ext Vol Qty, and Batch
  Qty** are all live formulas.
- **Ex Inv VL** — ~95% of its columns are live cross-sheet formulas referencing the
  matching CBOM VL sheet.

**Why formulas, not static values**: the whole point of exporting an editable Excel
workbook (rather than a flat data dump) is that a user can change an input cell — a
quoted price, a quantity — and watch every dependent column recalculate automatically,
exactly like the original engineering workbook. A static value would silently go stale
the moment anyone touched an upstream cell.

**A few columns are deliberately exceptions** — Part Qty and FG Part Qty are written as
literal values, not formulas, because the correct business logic (sum of Scrub BOM
quantity across every occurrence of that part within an FG) cannot be expressed as a
same-sheet Excel formula on this sheet's own row layout (verified directly: the sheet
already shows one row per part per FG, so a same-sheet `SUMIFS` would only ever see one
matching row, not the true multi-row Scrub BOM sum). These are computed once in Python
from Scrub BOM directly and written as correct values instead.

---

## Step 7 — Validation

Every validation below is available via `validator.validate_rfq(con, rfq_id)` — one
function, returning every check's pass/fail status and detail, not just failures. It is
not run automatically by `cbom`/`generate_reports`/`export_reports` (keeping those fast
and side-effect-free); call it explicitly as a health check.

- **Row-count validation**: confirms `cbom` and each of the 16 report tables have the
  expected number of rows for the given `rfq_id` (zero rows in `cbom` for a real RFQ is
  always a failure; zero rows in an individual report can be legitimate — e.g. no PCB
  parts in this BOM — so that's reported informationally, not as an automatic failure).
- **Duplicate checks**: for every table with a declared business-key uniqueness
  requirement (e.g. `aclass_parts_report` on `cpn`, `cbom` on `(bom_item_id, volume_no)`),
  confirms the row count equals the distinct-key count — no accidental fan-out from a
  join.
- **Orphan checks**: confirms every `cbom` row's `bom_item_id` still exists in
  `scrub_bom_items` — catches a stale `cbom` row that would survive a Scrub BOM change.
- **Mandatory field validation**: confirms the one column each report table can never
  have NULL in (typically `cpn`/`part_number`/`fg`) is actually never NULL.
- **RFQ validation**: confirms every row in every table has a non-NULL `rfq_id` matching
  the one requested — no cross-RFQ contamination, no orphaned-scope rows.
- **Row-count validation** (cross-check): re-running `generate_reports` for the same
  `rfq_id` twice produces identical counts both times (idempotency, not accidental
  duplication) — a check performed as part of this module's own development, not
  automated inside `validator.py` itself, but straightforward to script the same way
  against any two consecutive `generate_reports` calls.
- **Backend vs. Excel validation**: for every field where CBOM computes a *backend* value
  (e.g. `is_price_same`, `recurring_count`) that also has a live Excel formula reproducing
  the same logic on the exported sheet, the two are verified to agree — independently
  recomputing the expected value from raw data and comparing against both the stored
  backend value and a manual simulation of the actual written Excel formula (done during
  development for every field this applies to; not an automated runtime check inside this
  module, since it requires an Excel formula-evaluation engine this environment doesn't
  have — see README "Troubleshooting").
