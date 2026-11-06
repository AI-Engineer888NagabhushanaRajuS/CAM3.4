# fastmcp-router/

**Populated** — 9 files copied from `centum intake\` (fresh copy; the original
live services are untouched and still run from their original location).

## Status per file (verified via `python -m py_compile` + `python -c "import ..."`)

| File | Status |
|---|---|
| `fastapi_router.py` | **Works** — imports cleanly, no external coupling beyond `tool_calling.py`/`db.py` (both here) |
| `db.py` | **Works** — self-contained (only external libs: psycopg2) |
| `upload_server.py` | **Works** — only depends on `db.py` (here) |
| `tool_calling.py` | **Works** — only depends on `config.py` (here) |
| `config.py` | **Works** — self-contained (centum intake's own config, defines `MCP_JUNGLE_URL`) |
| `manage_backend.py` | **Do not run this copy** — hardcodes absolute paths to the live `centum intake`/`Downloads\accomplish-ui` locations; running it would manage the real production services, not anything here. Reference-only until every service it orchestrates is actually migrated into this repo and its paths are rewritten. |
| `hitl_router.py` | **Imports OK, needs a DB path override to serve requests** — `reporting_module` has since been migrated to `mcp-tools/reporting/superset/`; the sys.path insert now points there and `import database`/`import final_selection` succeed (verified). Endpoints that touch the DB will still fail until `REPORTING_DATABASE_DIR` is set or `database/` is migrated (see below). |
| `duck_db_api.py` | **Imports OK, needs a DB path override to serve requests** — same fix/status as `hitl_router.py`, verified including the `config`/`helpers` imports. |
| `bom_qa_lookup_server.py` | **Imports OK (name collision fixed), needs a DB path override to serve requests** — `import config as reporting_config` now correctly resolves to `mcp-tools/reporting/superset/config.py` (confirmed: `reporting_config.REPORTS_DB_PATH` exists), not this folder's own `config.py`. End-to-end tested with `REPORTING_DATABASE_DIR` set: a real query against the live data succeeded (156,067 rows). |

## The config.py name collision — resolved for these 3 files

This folder's `config.py` and `reporting_module`'s `config.py` (now at
`mcp-tools/reporting/superset/config.py`) are two different files that
happen to share a module name. The 3 files above insert
`mcp-tools/reporting/superset/` onto `sys.path` **after** this folder, which
Python resolves as higher-priority (`sys.path.insert(0, ...)`, last-in-wins)
— so `import config` correctly picks up reporting_module's version.
Verified directly (`reporting_config.__file__` points at the superset
folder's copy). Don't add a bare `config.py` anywhere else that would sit
ahead of it on `sys.path`.

## What's still needed for the 3 files to fully work

`reporting_module` is migrated (see `mcp-tools/reporting/superset/README.md`)
and imports succeed, but its own DB path resolution (`../database`, meant
for its old location) doesn't reach this repo's `database/` from the new
nesting depth. Set `REPORTING_DATABASE_DIR` to
`centum intake\database\` (verified working), or wait until `database/`
itself is migrated into this repo and update the default path depth in
`mcp-tools/reporting/superset/config.py`.
