"""[BuLLMQuote-SRIM MIGRATION NOTE -- updated, containerization Phase 0]
`database/` has now been migrated into this repo's own top-level `database/`
folder (containerization Phase 0, 2026-10-28) -- `PROJECT_DATABASE_DIR`'s
default below has been corrected from `../database` (wrong for this file's
actual depth, 3 levels below repo root) to `../../../database`, pointing at
the real top-level folder instead of resolving to the nonexistent
`mcp-tools/reporting/database/`.

That local copy is a point-in-time snapshot of CAM's live
`centum intake/database/*.duckdb` files, taken via DuckDB's own read-only
ATTACH + `COPY FROM DATABASE` (never a raw file copy, and never opening CAM's
originals read-write) -- CAM's originals are untouched and keep being written
by CAM's own live pipeline. A scheduled read-only sync job re-runs this same
copy on an interval so this local copy doesn't go stale; see that job's own
script for the current schedule. This repo's own data is therefore always a
recent-but-not-necessarily-live-instant snapshot, not a real-time mirror.

The `REPORTING_DATABASE_DIR` (or per-file `REPORTING_INPUT_DB`/
`REPORTING_CBOM_DB`/`REPORTING_REPORTS_DB`) environment variable override
still works exactly as documented below, and still takes precedence over this
default -- the live bare-metal `reporting_mcp_server` process continues to be
launched with `REPORTING_DATABASE_DIR` explicitly pointed at CAM's original
`centum intake\\database\\` (see fastmcp-router/manage_backend.py), so this
default-path fix has no effect on that already-running process. It only
matters for anything that does NOT set that override -- new container builds,
or an ad-hoc local run against this repo's own synced copy.
[END MIGRATION NOTE]

Single configuration point for this module -- the ONE file to touch when copying
`reporting_module/` into a different project.

The 3 DuckDB files default to the project's shared `database/` folder (one level up from
this file) -- input_db.duckdb and cbom.duckdb are the same files quote_win_to_database.py/
scrub_bom_to_database.py/costing_sheet_to_database.py/erp_to_database.py's own DB_PATH
would need repointing to if this module is ever wired into the live intake pipeline;
reports.duckdb is this module's own generated artifact and is created fresh on first
connect() if it doesn't exist yet. To point at databases that live elsewhere, override
with environment variables -- no code changes needed:

    REPORTING_INPUT_DB     -- path to input_db.duckdb (scrub_bom_items, quote_win, batch, volume, costing_sheet, erp)
    REPORTING_CBOM_DB      -- path to cbom.duckdb (generated)
    REPORTING_REPORTS_DB   -- path to reports.duckdb (generated)
    REPORTING_EXPORTS_DIR  -- directory Excel workbooks are written to
    REPORTING_LOGS_DIR     -- directory the log file is written to

input_db.duckdb is always opened READ-ONLY by this module (see database.py) -- it is
never created or modified by generate_reports()/export_reports(). It must already exist,
with `rfq_id` (and, for CBOM VL's Recurring Count, `display_order`) columns present on its
4 tables -- see migrations.py and the README's "Database Setup" section if starting from a
freshly-loaded database that doesn't have those columns yet.
"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DATABASE_DIR = os.environ.get(
    "REPORTING_DATABASE_DIR",
    os.path.abspath(os.path.join(BASE_DIR, "..", "..", "..", "database")),
)

INPUT_DB_PATH = os.environ.get("REPORTING_INPUT_DB", os.path.join(PROJECT_DATABASE_DIR, "input_db.duckdb"))
CBOM_DB_PATH = os.environ.get("REPORTING_CBOM_DB", os.path.join(PROJECT_DATABASE_DIR, "cbom.duckdb"))
REPORTS_DB_PATH = os.environ.get("REPORTING_REPORTS_DB", os.path.join(PROJECT_DATABASE_DIR, "reports.duckdb"))
EXPORTS_DIR = os.environ.get("REPORTING_EXPORTS_DIR", os.path.join(BASE_DIR, "exports"))
LOGS_DIR = os.environ.get("REPORTING_LOGS_DIR", os.path.join(BASE_DIR, "logs"))

os.makedirs(EXPORTS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)
