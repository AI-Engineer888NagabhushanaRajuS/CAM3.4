# database/

**Populated (partially)** — `Bom_storage.duckdb` copied from
`C:\SRIM-DB-SETUP\Databases\Bom_storage.duckdb` (fresh copy; the original is
untouched). Per explicit instruction, this is the intended database for this
new clone project.

Contents (verified by opening the copy directly): 2 tables —
`processed_bom_items` (704 rows) and `update_alternatives` (116 rows). See
`C:\SRIM-DB-SETUP\Databases\duckdb_schema.py` (not copied here) for the full
schema definition — a BOM-item cache with an alternate-manufacturer-part
decision table (`preferred_flag`), keyed on `rfq_id`/`bom_item_id`.

## Important: this does NOT resolve mcp-tools/reporting/superset's DB path issue

This is a **different schema** from what the migrated `reporting_module` (at
`mcp-tools/reporting/superset/`) expects. That code looks for 3 specifically-named
files — `input_db.duckdb`, `cbom.duckdb`, `reports.duckdb` — with tables like
`scrub_bom_items`, `quote_win`, `cbom`, none of which exist in
`Bom_storage.duckdb`. The `REPORTING_DATABASE_DIR` override documented in
`mcp-tools/reporting/superset/config.py`'s migration note is still unresolved;
populating this folder with `Bom_storage.duckdb` doesn't change that. If
`Bom_storage.duckdb` is meant to replace or feed into the reporting pipeline's
own database, that mapping hasn't been established yet.

## Still not migrated

- `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum intake\database\` — live
  runtime DuckDB files (`cbom.duckdb`, `input_db.duckdb`, `reports.duckdb`) used
  by the currently-running reporting pipeline.
- `C:\SRIM-DB-SETUP\` — Postgres schema/setup scripts
  (`v1__init_postgres_schema.sql`, `init_bom_db.py`, `duckdb_schema.py`), and
  `rfq_456_export.csv`.
