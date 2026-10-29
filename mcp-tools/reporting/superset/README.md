# mcp-tools/reporting/superset/

**Populated** — `reporting_module` copied here from `centum intake\reporting_module\`
(fresh copy; the original is untouched, and the live `reporting_mcp_server`
service still runs from its original location).

## What was excluded from the copy

- `__pycache__/` — regenerable bytecode cache
- `exports/` (160MB, 115 files) — generated Excel report output, regenerable
- `logs/` (560KB) — generated runtime logs, regenerable
- `cbom.duckdb` (9.4MB), `input_db.duckdb` (4.2MB), `reports.duckdb` (15.7MB) —
  **confirmed stale**: these local files (last modified Jul 22) are a
  different, much smaller, older dataset than the real ones the live system
  actually uses at `centum intake\database\*.duckdb` (65-74MB, modified
  today). Verified via file hash comparison. Copying them would have silently
  served old/wrong data from this location. See `config.py`'s own migration
  note for the full path-resolution story.

## Known issue: DB path resolution needs an override

`config.py` defaults to looking for the 3 DuckDB files at `../database`
(one level up) — correct when this module lived at
`centum intake\reporting_module\`, but this copy is 3 levels deep
(`mcp-tools/reporting/superset/`), so the default no longer reaches this
repo's own (still-empty) top-level `database/` folder.

**Verified fix**: setting the `REPORTING_DATABASE_DIR` environment variable to
`centum intake\database\` makes everything work correctly from this new
location — confirmed with a real query (`SELECT COUNT(*) FROM cbom_db.cbom`
→ 156,067 rows) run directly against the live data through this copy's own
`database.py`.

Once `database/` itself is migrated into this repo's own top-level
`database/` folder, update `config.py`'s default path depth
(`../../../database`, not `../database`) and remove the env var workaround.

## fastmcp-router/ dependents fixed

`hitl_router.py`, `duck_db_api.py`, and `bom_qa_lookup_server.py` (in
`fastmcp-router/`) previously failed to import because reporting_module
didn't exist yet. Their `sys.path` insert logic has been updated to point
here, and all 3 now import successfully (verified) — though they still need
`REPORTING_DATABASE_DIR` set (or `database/` migrated) to actually serve
requests, for the same reason as above.
