# Intake Tool Reference (`SRIM/Tools/I n D/intake/`)

> Full file-by-file reference for the standalone `intake` FastMCP server and
> its supporting scripts/test fixtures. This folder is **separate from**
> `centum intake/scrub_mcp_server.py` — see
> [Relationship to `scrub_mcp_server.py`](#relationship-to-scrub_mcp_serverpy-and-the-centum-intake-pipeline)
> below for how the two BOM pipelines differ.

**Folder path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\intake\`
**Server status:** DORMANT. `mcp_server.py` is fully implemented (intended
port **8002**) but is **not** in `centum intake\manage_backend.py`'s
`SERVICES` list, **not** in `centum intake\.backend_services_state.json`
(the live PID/port registry, which lists `upload_server`, `fastapi_router`,
`hitl_router`, `scrub_mcp_server`, `reporting_mcp_server`,
`bom_qa_lookup_server`, `python_bridge`, `web_frontend`, `superset`, and
`daemon` — 10 services, none of which is this folder's server), and **not**
referenced in `centum intake\fastapi_router.py`'s active tool allowlist
(which only wires up the four `centum_intake__standardize_*` tools from
`scrub_mcp_server.py`). It can still be started standalone with
`python mcp_server.py`.

---

## Table of Contents

1. [mcp_server.py](#mcp_serverpy)
2. [bom_processing.py](#bom_processingpy)
3. [bom_to_database.py](#bom_to_databasepy)
4. [tool_calling.py](#tool_callingpy)
5. [config.py](#configpy)
6. [requirements.txt](#requirementstxt)
7. [detect_alternates.py](#detect_alternatespy)
8. [apply_alternatives.py](#apply_alternativespy)
9. [matrix_bom_volume_enrichment.py](#matrix_bom_volume_enrichmentpy)
10. [test_consolidation.py](#test_consolidationpy)
11. [test_filter_alternates.py](#test_filter_alternatespy)
12. [.claude/settings.local.json](#claudesettingslocaljson)
13. [BOM-Centum (1).xlsx](#bom-centum-1xlsx)
14. [Centum_BOM.xlsx](#centum_bomxlsx)
15. [Centum_consolidated_output.xlsx](#centum_consolidated_outputxlsx)
16. [Centum_consolidated_without_alternates.xlsx](#centum_consolidated_without_alternatesxlsx)
17. [Centum_Vol.xlsx](#centum_volxlsx)
18. [consolidated.xlsx](#consolidatedxlsx)
19. [consolidated_BOM.xlsx](#consolidated_bomxlsx)
20. [consolidated_bom_export_TEST_FIX_MPN_001.csv](#consolidated_bom_export_test_fix_mpn_001csv)
21. [consolidated_bom_export_TEST_SCRIPT_RUN_001.csv](#consolidated_bom_export_test_script_run_001csv)
22. [Consolidated-Centum BoM (1).xlsx](#consolidated-centum-bom-1xlsx)
23. [Consolidated-Centum BoM (1)_with_required_qty.xlsx](#consolidated-centum-bom-1_with_required_qtyxlsx)
24. [Multiple_BOM (4).xlsx](#multiple_bom-4xlsx)
25. [UBR Vol-1 Qty.xlsx](#ubr-vol-1-qtyxlsx)
26. [Relationship to scrub_mcp_server.py and the centum intake pipeline](#relationship-to-scrub_mcp_serverpy-and-the-centum-intake-pipeline)
27. [Excluded items](#excluded-items)

---

## mcp_server.py

**File path:** `SRIM/Tools/I n D/intake/mcp_server.py`

### Purpose

The entry point for the standalone **"Intake"** FastMCP server. It exposes
two active BOM-intake tools over HTTP (intended host/port
`192.168.1.27:8002`) plus three commented-out/inactive tools kept in the
file as historical scaffolding.

### Responsibilities

- Instantiate a `FastMCP("Intake")` server.
- Provide `scan_local_file` (Stage 1: antivirus scanning) and `import_bom`
  (schema mapping → standardization → volume expansion → MM conversion →
  consolidation → DuckDB save).
- Talk to a **Postgres metadata MCP server** (tool name
  `Production_FileMetedata_DB-execute_sql`, registered in Bifrost as of
  the 2026-09-28 migration — see [bifrost.md](./bifrost.md); no session
  handshake needed, unlike the MCP Jungle client this replaced) through
  `tool_calling.py` to read RFQ file-telemetry rows and write back
  scan/tracking status — the intake server does not connect to Postgres
  directly; it goes through another MCP tool.
- Validate all externally supplied IDs (`rfq_id`) before any SQL
  interpolation via `_validate_id`.

### Dependencies

- **Local:** `bom_to_database.process_bom_to_database`,
  `bom_processing.process_bom`, `tool_calling.call_tool`,
  `tool_calling.create_session`. Commented-out imports reference
  `detect_alternates.detect_alternates`,
  `apply_alternatives.apply_alternatives`, and
  `distributor_pricing.enrichment.enrich_distributors` /
  `DigikeyClient` — none of these are active imports today.
- **Third-party (requirements.txt):** `fastmcp` (server framework),
  `python-magic` / `python-magic-bin` (imported as `magic`, for MIME-type
  detection).
- **Standard library:** `ast`, `json`, `os`, `re`, `subprocess`, `sys`,
  `traceback`.

### Public interfaces

| Symbol | Type | Description |
|---|---|---|
| `mcp` | `FastMCP` instance | The server object, named `"Intake"`. |
| `TARGET_METADATA_TOOL` | constant | `"postgres_metadata__execute_sql"` — the downstream MCP tool name used for every DB read/write. |
| `_validate_id(value: str) -> str` | function | Rejects any ID containing characters outside `[A-Za-z0-9_-]`; raises `ValueError` otherwise. Used to sanitize `rfq_id` before it is interpolated into raw SQL strings. |
| `scan_local_file(rfq_id) -> str` | **`@mcp.tool()`** | See detailed breakdown below. |
| `import_bom(rfq_id) -> str` | **`@mcp.tool()`** | See detailed breakdown below. |
| `enrich_bom(rfq_id)` | commented out | Dead code — see [Inactive tools](#inactive-commented-out-tools). |
| `detect_alternates(rfq_id) -> str` | commented out | Dead code — see [Inactive tools](#inactive-commented-out-tools). |
| `apply_alternatives(rfq_id) -> str` | commented out | Dead code — see [Inactive tools](#inactive-commented-out-tools). |

### `scan_local_file(rfq_id) -> str` — full detail

**Docstring / Stage Target:** `"Scans an array of local paths for malware
using ClamAV and returns structural metrics."` — **Stage Target: 1
(ANTIVIRUS_SCANNING)**.

**Parameters:** `rfq_id` (untyped in signature; coerced to `str` and
stripped internally). Must match `^[A-Za-z0-9_\-]+$` or a `ValueError` is
raised via `_validate_id`.

**Step-by-step execution:**

1. **STEP A — fetch pending file paths from DB.** Calls `call_tool()`
   (Bifrost, no session needed) to run (through
   `Production_FileMetedata_DB-execute_sql`):
   ```sql
   SELECT file_id::text AS file_id, file_path
   FROM rfq_file_telemetry
   WHERE rfq_id = '<rfq_id_str>' AND scan_status = 'PENDING';
   ```
   The JSON-RPC response is unwrapped (`result.content[0].text`), then
   parsed — first via `json.loads` after swapping single quotes for double
   quotes, falling back to `ast.literal_eval` if that fails (defensive
   handling of a stringified Python-repr payload). Rows are normalized into
   a `pending_files` list of `{file_id, file_path}` dicts. Any exception in
   this block is swallowed and logged; an empty `pending_files` list is the
   fallback.
   If no pending files are found, the function returns immediately:
   ```json
   {"rfq_id": "...", "rfq_process_stage": 1, "hitl_required": false,
    "message": "No files found with PENDING status.", "file_records": []}
   ```
2. **STEP B — scan loop.** For every pending file record:
   - Normalizes the path (`expanduser` → strip quotes → `abspath` →
     `normpath`).
   - If the path doesn't exist on disk: marks `scan_status = "FAILED"`,
     `file_type = "unknown"`, sets `global_hitl_tripped = True`, continues.
   - Otherwise runs
     `C:\Program Files\ClamAV\clamscan.exe --no-summary <path>` via
     `subprocess.run` (no window on Windows), and separately probes MIME
     type with `magic.from_file(path, mime=True)` (falls back to
     `"unknown/excel-or-binary"` on error).
     - Return code `0` → `scan_status = "CLEAN"`.
     - Return code `1` → `scan_status = "INFECTED"`, HITL tripped, threat
       details captured from stdout.
     - Any other return code → `scan_status = "FAILED"`, HITL tripped,
       stderr captured.
     - Any Python exception around the subprocess call → `scan_status =
       "FAILED"`, HITL tripped, exception string captured.
3. **STEP C — DB upsert.** Writes an upsert into `rfq_process_tracking`:
   ```sql
   INSERT INTO rfq_process_tracking (rfq_id, rfq_process_stage, hitl_required, triggered_by)
   VALUES ('<rfq_id>', 1, <true|false>, 'SYSTEM_API')
   ON CONFLICT (rfq_id) DO UPDATE SET rfq_process_stage=..., hitl_required=..., triggered_by=..., updated_at=CURRENT_TIMESTAMP;
   ```
   Then, for every processed file, runs an `UPDATE rfq_file_telemetry SET
   file_type=..., scan_status=..., execution_logs=...::jsonb,
   processed_at=CURRENT_TIMESTAMP WHERE file_id = '<file_id>';` (logs are
   JSON-encoded and single-quote-escaped for SQL safety). Any DB error here
   is caught and logged but does not fail the tool call.

**Returns (JSON string):**
```json
{
  "rfq_id": "<rfq_id_str>",
  "rfq_process_stage": 1,
  "hitl_required": true | false,
  "file_records": [ {"file_id", "file_path", "file_type", "scan_status", "logs"}, ... ]
}
```
`hitl_required` is `true` if any file was missing, infected, or failed to
scan.

**Security/robustness note:** all SQL strings in this function are built
via raw f-string interpolation (not parameterized queries) even though
`rfq_id` is pre-validated by `_validate_id` — `file_id`, `file_type`,
`scan_status`, and the JSON-escaped `logs` blob are interpolated without
the same regex guard, relying only on ad hoc `.replace("'", "''")`
escaping for the logs field specifically.

### `import_bom(rfq_id) -> str` — full detail

**Docstring:** `"Import BOM — Performs: Schema Mapping, Standardization,
Volume Expansion, MM Conversion, Consolidation, Save To DuckDB."` (no
explicit numbered "Stage Target" comment in this tool's docstring, unlike
`scan_local_file`; based on sequencing this is intake's next stage after
antivirus scanning.)

**Parameters:** `rfq_id` — same validation as above.

**Step-by-step execution:**

1. Opens an MCP session and queries `rfq_file_telemetry` twice through
   `postgres_metadata__execute_sql`:
   - `... WHERE rfq_id = '<id>' AND file_role = 'BOM';` → `bom_file`
   - `... WHERE rfq_id = '<id>' AND file_role = 'VOLUME';` → `volume_file`
   Both responses are parsed with `ast.literal_eval` directly (no JSON
   fallback, unlike `scan_local_file`) and the first row's `file_path` is
   taken unconditionally (`[0]["file_path"]` — will raise `IndexError` if
   no row exists, which is caught by the surrounding `try/except` and
   returned as a failure JSON with a traceback).
2. Calls `bom_processing.process_bom(bom_file=..., volume_file=...)`,
   which performs schema mapping, standardization, volume-file lookup,
   volume expansion (adds `required_qty`), and MPN-based consolidation
   (including UOM/mm normalization) — returns
   `(consolidated_df, duplicate_cpn_conflicts)`.
3. Calls `bom_to_database.process_bom_to_database(rfq_id, bom_file,
   consolidated_df)` to persist the consolidated rows into DuckDB's
   `processed_bom_items` table.
4. Returns success JSON, or a failure JSON with `traceback.format_exc()` on
   any exception from either step.

**Returns (JSON string), success case:**
```json
{"status": "success", "hitl": 0,
 "rows_after_consolidation": <int>,
 "duplicate_cpn_conflicts": [ {"cpn", "mpns", "occurrences"}, ... ]}
```
**Returns, failure case:**
```json
{"status": "failed", "error": "<message>", "traceback": "<full traceback>"}
```

### Inactive (commented-out) tools

Three tools are present as commented-out code and are **not** registered
with `@mcp.tool()`:

- **`enrich_bom(rfq_id)`** — would have called an `enrich_distributors`
  function (DigiKey/Element14/Mouser pricing) imported from
  `distributor_pricing.enrichment`.
- **`detect_alternates(rfq_id) -> str`** — would have called this folder's
  own `detect_alternates.py:detect_alternates()`.
- **`apply_alternatives(rfq_id) -> str`** — would have called this folder's
  own `apply_alternatives.py:apply_alternatives()`.

**Inference:** per the task brief, this functionality has since been
reimplemented as live tools inside the separate `distributor_pricing`
package (`distributor_pricing/mcp_server.py` defines active `enrich_bom`,
`export_enriched_bom`, `detect_alternates`, and `apply_alternatives`
tools, confirmed by inspecting that file's `@mcp.tool()` decorators). The
`intake/detect_alternates.py` and `intake/apply_alternatives.py` module
files described below still exist in this folder and are logically
identical in places to their `distributor_pricing` namesakes, but they are
orphaned — imported by nothing currently active in `intake/mcp_server.py`.

### Internal execution flow (whole-server view)

```
intake/mcp_server.py
  ├── scan_local_file(rfq_id)      [ACTIVE @mcp.tool()]
  │     DB(rfq_file_telemetry PENDING) → ClamAV loop → DB(rfq_process_tracking, rfq_file_telemetry)
  │
  └── import_bom(rfq_id)           [ACTIVE @mcp.tool()]
        DB(rfq_file_telemetry BOM/VOLUME paths)
          → bom_processing.process_bom()
                ├── semantic_mapping() / volume_semantic_mapping()  (ollama LLM calls)
                ├── standardize_bom()
                ├── build_volume_map()
                ├── expand_bom_with_volume()
                ├── consolidate_bom()   (incl. UOM normalization/mm conversion)
                └── detect_duplicate_cpn_conflicts()
          → bom_to_database.process_bom_to_database()  (DuckDB insert)
```

### Configuration usage

- No `.env` file exists in this folder. The one configurable value used
  directly by `mcp_server.py` is the hardcoded ClamAV executable path
  (`C:\Program Files\ClamAV\clamscan.exe`) and the hardcoded
  `mcp.run(transport="http", host="192.168.1.27", port=8002)` bind
  address in `if __name__ == "__main__":`.
- Indirectly depends on `config.py` (via `bom_to_database.py`, for
  `DB_PATH`) and `config.py`'s `MCP_JUNGLE_URL` (via `tool_calling.py`).

### Related files

`bom_processing.py`, `bom_to_database.py`, `tool_calling.py`, `config.py`,
`detect_alternates.py`, `apply_alternatives.py` (orphaned references),
`distributor_pricing/mcp_server.py` and `distributor_pricing/enrichment.py`
(live replacements), `centum intake/manage_backend.py` and
`centum intake/fastapi_router.py` (confirm this server is unregistered).

---

## bom_processing.py

**File path:** `SRIM/Tools/I n D/intake/bom_processing.py`

### Purpose

The core BOM transformation library used by `import_bom`: turns a raw
customer BOM Excel file plus a Volume file into a consolidated,
MPN-deduplicated DataFrame ready for database insertion. Also runnable
standalone as a CLI tool.

### Responsibilities

- Define the canonical output schema (`PREDEFINED_TEMPLATE_HEADERS`, 20
  fields including `fg`, `cpn`, `mpn`, `bom_qty`, `volume`, `required_qty`,
  `uom`, etc.) and which fields have a forced/deterministic source column
  (`FORCED_FIELDS`).
- Use an LLM (via `ollama`) to semantically map arbitrary incoming BOM/
  Volume column headers onto the canonical schema.
- Enforce the business rule that **CPN = UBR Number** deterministically
  (never left to the LLM) when a literal `"UBR NUMBER"` column exists;
  otherwise keeps the LLM's own guess for `cpn` (customer-agnostic
  fallback, e.g. Centum's own `"CPN"` column).
- Normalize units of measure: count-based variants (`EA`, `PCS`, `NOS`,
  etc.) → `"Nos"`; length variants (`meter`, `feet`) → canonical spelling,
  and — critically for consolidation — actual **quantity conversion to
  millimeters** (`normalize_length`).
- Detect Finished-Good (FG) boundaries in a flat BOM sheet purely from
  Volume-file MPN matches (no BOM-Level hierarchy or recursion), expand
  each child row's `required_qty = bom_qty × FG's volume`.
- Consolidate all expanded rows by **MPN alone** (summing quantities,
  combining CPN/FG as reference strings), raising on cross-row UOM
  conflicts for the same MPN.
- Detect (but not resolve) "duplicate CPN, different MPN" conflicts
  (alternate-manufacturer candidates) for reporting.

### Dependencies

- **Third-party:** `ollama` (LLM schema mapping, model
  `qwen2.5-coder:7b`), `pandas`, `openpyxl` (indirectly, via
  `pd.read_excel`/`to_excel`).
- **Standard library:** `json`, `pathlib.Path`.
- No local imports — this module is self-contained.

### Public interfaces

| Function | Description |
|---|---|
| `normalize_length(qty, uom)` | Converts `meter(s)/m` → `qty*1000, "mm"`; `feet/foot/ft` → `qty*304.8, "mm"`; otherwise passes through unchanged. |
| `normalize_uom(uom)` | Canonicalizes UOM spelling only (no quantity math): count variants → `"Nos"`; length variants → `"Meter"`/`"Feet"`/`"mm"`; else stripped original string. |
| `semantic_mapping(headers)` | Calls the Ollama LLM once to map a BOM's incoming headers onto `PREDEFINED_TEMPLATE_HEADERS`; returns a dict with every canonical key present (nulls where unmatched). |
| `volume_semantic_mapping(headers)` | Same idea for the Volume file, targeting `PREDEFINED_VOLUME_HEADERS = ["fg_mpn", "volume"]`; explicit prompt rules force `fg_mpn` to be a **manufacturer** part-number column, never a customer/internal one. |
| `standardize_bom(df, mapping)` | Renames source columns to canonical names per `mapping`, processing `FORCED_FIELDS` first so they always win column-name collisions; fills any missing canonical column with `None`; returns a DataFrame with exactly `PREDEFINED_TEMPLATE_HEADERS` columns in order. |
| `export_mapping(mapping, output_path)` | Writes a `{canonical_field, incoming_header}` mapping table to an Excel file (debug/audit helper). |
| `build_volume_map(volume_df, mapping)` | Resolves `fg_mpn`/`volume` columns from the LLM mapping, raises `ValueError` with diagnostic detail if either can't be resolved; returns `{normalized_mpn_upper: numeric_volume}`. |
| `expand_bom_with_volume(standardized_df, volume_map)` | Single top-to-bottom pass over BOM rows: a row whose `mpn` matches a `volume_map` key starts a new FG section; every subsequent row is a child of the most recent FG until the next FG marker. Computes `required_qty = bom_qty * volume` per child row. Skips rows before any FG, blank-MPN rows, and non-positive/invalid-qty rows (each with a printed warning). Returns the expanded DataFrame. |
| `consolidate_bom(df)` | Groups expanded rows by `mpn` alone (uppercased/stripped); sums `bom_qty`/`required_qty`, takes first `volume` (not additive), combines `fg`/`cpn` into sorted deduped comma-joined strings, keeps first `description`/`mfr`/`commodity`/`uom`, and counts `occurrences`. Normalizes UOM and applies `normalize_length` before grouping, rescaling `required_qty` by the same ratio applied to `bom_qty`. Raises `ValueError` if any MPN group has more than one distinct UOM. |
| `detect_duplicate_cpn_conflicts(consolidated_df)` | Finds CPNs that map to more than one MPN post-consolidation; returns a list of `{cpn, mpns, occurrences}` dicts. |
| `print_duplicate_cpn_report(conflicts)` | Pretty-prints the above to stdout. |
| `process_bom(bom_file, volume_file)` | Top-level orchestrator called by `mcp_server.py:import_bom`. Loads the BOM, runs `semantic_mapping`, force-overrides `cpn`/`bom_id`/`bom_level`/`mpn`/`bom_qty`/`uom` from literal header names when present, validates `cpn`/`mpn`/`bom_qty` are resolved (raises `ValueError` listing missing fields otherwise), standardizes, loads+maps the Volume file, builds the volume map, expands, consolidates, detects duplicate CPNs, prints a summary, and returns `(consolidated_df, duplicate_cpn_conflicts)`. |
| `__main__` CLI block | `python bom_processing.py <bom.xlsx> <volume.xlsx> [output.xlsx]` — runs the same pipeline standalone with per-step console stats (root assemblies, leaf components, cyclic/UOM-conflict error counts, missing volume mappings) and writes an Excel (falling back to CSV) output file. Exits non-zero on validation failure. |

### Internal execution flow

```
process_bom(bom_file, volume_file)
 ├─ pd.read_excel(bom_file) → strip column names
 ├─ semantic_mapping(headers)                      [LLM call #1]
 ├─ force overrides: UBR NUMBER→cpn, BOM_ID, BOM LEVEL, MPN, BOM QTY, UOM
 ├─ validate cpn/mpn/bom_qty resolved (raise if not)
 ├─ standardize_bom(bom_df, mapping)
 ├─ pd.read_excel(volume_file) → volume_semantic_mapping(headers)  [LLM call #2]
 ├─ build_volume_map(volume_df, volume_mapping)
 ├─ expand_bom_with_volume(standardized_df, volume_map)
 ├─ consolidate_bom(expanded_df)
 ├─ detect_duplicate_cpn_conflicts(consolidated_df)
 └─ return (consolidated_df, duplicate_cpn_conflicts)
```

### Configuration usage

None directly — no `.env`/config import. The LLM model name
(`qwen2.5-coder:7b`) is hardcoded in both `semantic_mapping` and
`volume_semantic_mapping`, implying a local Ollama daemon must be running
and have that model pulled.

### Related files

Called by `mcp_server.py` (`import_bom`) and by `test_consolidation.py`
(which imports its functions individually to build a step-by-step
validation harness). Conceptually parallel to, but explicitly independent
from, `matrix_bom_volume_enrichment.py` (different input shape) and to
`centum intake/scrub_bom_processing.py` (different pipeline — see
[Relationship](#relationship-to-scrub_mcp_serverpy-and-the-centum-intake-pipeline)).

---

## bom_to_database.py

**File path:** `SRIM/Tools/I n D/intake/bom_to_database.py`

### Purpose

Persists the DataFrame produced by `bom_processing.process_bom()` into the
shared DuckDB database's `processed_bom_items` table.

### Responsibilities

- Guard against double-import: refuses to insert if `rfq_id` already has
  rows in `processed_bom_items`.
- Backfill columns the consolidated DataFrame doesn't carry
  (`file_name`, `parent_fg`, `ce_remarks`, `item_num`, `part_type`,
  `ltb_date`, `common_aml`, `change_remarks`, `exported_at`) so the insert
  always matches the table's full column list.
- Perform the DuckDB insert via a registered temp view (`conn.register`)
  and a `SELECT ... FROM temp_df` insert, rather than row-by-row inserts.

### Dependencies

- **Third-party:** `duckdb`, `pandas` (implicit, via the DataFrame type).
- **Standard library:** `pathlib.Path`.
- **Local:** `config.DB_PATH`.

### Public interfaces

| Function | Description |
|---|---|
| `process_bom_to_database(rfq_id, bom_file, consolidated_df)` | Copies `consolidated_df`, adds `file_name` (basename of `bom_file`) and `parent_fg=None`, backfills the optional metadata columns listed above with `None` if absent, checks for existing rows for `rfq_id` (returns a `{"status": "failed", ...}` dict without writing if any exist), then inserts into `processed_bom_items` via a registered DuckDB view. Returns `{"status": "success", "rows_inserted": <int>}` on success. |

### Internal execution flow

```
process_bom_to_database(rfq_id, bom_file, consolidated_df)
 ├─ df = consolidated_df.copy(); add file_name, parent_fg
 ├─ backfill missing optional columns with None
 ├─ duckdb.connect(DB_PATH)
 │    ├─ SELECT COUNT(*) FROM processed_bom_items WHERE rfq_id = ?
 │    │    → if > 0: return failure dict (no insert)
 │    ├─ conn.register("temp_df", df)
 │    ├─ INSERT INTO processed_bom_items (...) SELECT ... FROM temp_df
 │    └─ conn.unregister("temp_df")
 └─ return {"status": "success", "rows_inserted": len(df)}
```

### Configuration usage

Reads `DB_PATH` from `config.py`, which in turn resolves it from
`shared/db_config.py` — `C:\SRIM-DB-SETUP\Databases\bom_storage.duckdb`.
This is the **same physical DuckDB file** used by the `distributor_pricing`
server (per `shared/db_config.py`'s own comment), so both are separate
processes pointed at shared state.

### Related files

`config.py` (`DB_PATH`), `bom_processing.py` (produces the DataFrame this
consumes), `mcp_server.py` (`import_bom` calls this), `test_consolidation.py`
(also calls this directly to validate the DB-write step).

---

## tool_calling.py

**File path:** `SRIM/Tools/I n D/intake/tool_calling.py`

### Purpose

A minimal MCP JSON-RPC client used by `mcp_server.py` to call *other* MCP
servers/tools (specifically the Postgres metadata tool) through an "MCP
Jungle" gateway, rather than talking to Postgres directly.

### Responsibilities

- Perform the full MCP handshake: `initialize` request → capture
  `Mcp-Session-Id` response header → send `notifications/initialized`.
- Provide a generic `call_tool` helper for any downstream tool by name.
- Provide a `list_tools` helper scoped to a specific `server_id`
  (`"postgres-mcp"`).
- Maintain a monotonically increasing JSON-RPC request ID counter
  (`itertools.count`), documented as safe for concurrent callers.

### Dependencies

- **Third-party:** `requests` (from `requirements.txt`).
- **Standard library:** `itertools`, `json`.
- **Local:** `config.MCP_JUNGLE_URL`.

### Public interfaces

| Function | Description |
|---|---|
| `create_session()` | Opens a `requests.Session`, sets `Content-Type`/`MCP-Protocol-Version: 2025-11-25` headers, POSTs an `initialize` JSON-RPC payload to `MCP_JUNGLE_URL`, captures the returned `Mcp-Session-Id` header onto the session, then POSTs the mandatory `notifications/initialized` notification. Returns the configured `requests.Session`. |
| `list_tools(session)` | POSTs a `tools/list` JSON-RPC request scoped to `server_id: "postgres-mcp"`; returns the parsed JSON response. |
| `call_tool(session, tool_name, arguments)` | POSTs a `tools/call` JSON-RPC request with the given tool name and arguments dict; returns the parsed JSON response (the raw JSON-RPC envelope, which callers like `mcp_server.py` then unwrap via `result.content[0].text`). |
| `__main__` block | Creates a session, calls `list_tools`, and pretty-prints the result — a manual smoke test for the gateway connection. |

### Internal execution flow

```
create_session()
 ├─ POST {method: "initialize", params: {protocolVersion, capabilities, clientInfo}} → MCP_JUNGLE_URL
 ├─ capture Mcp-Session-Id header
 └─ POST {method: "notifications/initialized"} → MCP_JUNGLE_URL

call_tool(session, tool_name, arguments)
 └─ POST {method: "tools/call", params: {name, arguments}} → MCP_JUNGLE_URL → return response.json()
```

### Configuration usage

Reads `MCP_JUNGLE_URL` from `config.py` (`http://localhost:8080/mcp`).

### Related files

`config.py` (`MCP_JUNGLE_URL`), `mcp_server.py` (both tools use
`create_session`/`call_tool` to reach `postgres_metadata__execute_sql`).
Identical in spirit (and near-identical in code) to
`centum intake/tool_calling.py`, which serves the same role for
`scrub_mcp_server.py`.

---

## config.py

**File path:** `SRIM/Tools/I n D/intake/config.py`

### Purpose

Small local configuration module providing the Bifrost gateway URL
(`BIFROST_URL`) and endpoint-slug lookup table (as of the 2026-09-28
migration off MCP Jungle — see [bifrost.md](./bifrost.md)), and
re-exporting the shared DuckDB path.

### Responsibilities

- Insert the parent directory (`SRIM/Tools/I n D/`) onto `sys.path` so
  `shared.db_config` can be imported regardless of the caller's working
  directory.
- Import and re-expose `DB_PATH` from `shared/db_config.py`.
- Define `MCP_JUNGLE_URL = "http://localhost:8080/mcp"` — labeled in a
  comment as the "MCP gateway (intake-only)" URL.

### Dependencies

- **Standard library:** `sys`, `pathlib.Path`.
- **Local:** `shared.db_config.DB_PATH`.

### Public interfaces

| Symbol | Description |
|---|---|
| `DB_PATH` | Re-exported from `shared/db_config.py` — `C:\SRIM-DB-SETUP\Databases\bom_storage.duckdb`. |
| `MCP_JUNGLE_URL` | `"http://localhost:8080/mcp"` — the gateway endpoint used by `tool_calling.py`. |

### Configuration usage

This **is** the configuration file for the whole folder — there is no
`.env` file in `intake/`. All DB and gateway configuration is hardcoded
here (and one level up, in `shared/db_config.py`).

### Related files

`shared/db_config.py` (`SRIM/Tools/I n D/shared/db_config.py` — defines
`DB_PATH = Path(r"C:\SRIM-DB-SETUP\Databases\bom_storage.duckdb")`, with an
explicit comment that this constant is shared identically by both
`intake/` and `distributor_pricing/`, "both FastMCP servers are separate
processes pointed at the same physical DuckDB file"). Consumed by
`tool_calling.py` (`MCP_JUNGLE_URL`), `bom_to_database.py`,
`detect_alternates.py`, `apply_alternatives.py`, `test_consolidation.py`
(all via `DB_PATH`).

---

## requirements.txt

**File path:** `SRIM/Tools/I n D/intake/requirements.txt`

### Purpose

Pinned (by name only, no versions) dependency list for this folder's
Python environment.

### Contents

```
fastmcp
pandas
duckdb
requests
ollama
python-magic-bin; platform_system == "Windows"
python-magic; platform_system != "Windows"
openpyxl
```

### Notes

- No version pins — this is a name-only requirements file.
- The `python-magic-bin` / `python-magic` split via environment markers
  ensures Windows installs get the bundled-binary variant (`magic`
  requires the native `libmagic` library, which `python-magic-bin` vendors
  for Windows) while other platforms install the pure wrapper expecting a
  system-installed `libmagic`.
- `openpyxl` is required transitively by `pandas.read_excel`/`to_excel`
  for `.xlsx` files even though no file imports it directly by name.
- Every package here maps to an actual `import` somewhere in the folder:
  `fastmcp` → `mcp_server.py`; `pandas` → `bom_processing.py`,
  `bom_to_database.py`, `matrix_bom_volume_enrichment.py`,
  `test_consolidation.py`, `test_filter_alternates.py`; `duckdb` →
  `bom_to_database.py`, `detect_alternates.py`, `apply_alternatives.py`,
  `test_consolidation.py`; `requests` → `tool_calling.py`; `ollama` →
  `bom_processing.py`; `python-magic`/`python-magic-bin` (as `magic`) →
  `mcp_server.py`.

### Related files

Installed for the whole folder; consumed indirectly by every `.py` file.

---

## detect_alternates.py

**File path:** `SRIM/Tools/I n D/intake/detect_alternates.py`

### Purpose

Detects "alternate manufacturer part" situations — the same CPN appearing
with more than one distinct MPN in an **already-enriched**
`processed_bom_items` table — and stages them into an `update_alternatives`
table for human review. **Not currently wired into `mcp_server.py`** (its
`@mcp.tool()` call site is commented out there).

### Responsibilities

- Idempotently create `update_alternatives` if it doesn't exist
  (`_ensure_alternatives_table`).
- Refuse to re-run for an `rfq_id` that already has alternates staged
  (returns a failure dict rather than duplicating rows).
- Group `processed_bom_items` rows by `cpn`, find CPNs with more than one
  distinct `mpn`, and insert one `update_alternatives` row per such
  (cpn, mpn) pair, all with `preferred_flag = FALSE` awaiting user
  decision.
- Wrap the insert loop in an explicit `BEGIN/COMMIT/ROLLBACK` transaction.

### Dependencies

- **Third-party:** `duckdb`.
- **Local:** `config.DB_PATH`.

### Public interfaces

| Function | Description |
|---|---|
| `_ensure_alternatives_table(conn)` | `CREATE TABLE IF NOT EXISTS update_alternatives (id UUID, rfq_id, bom_item_id UUID, cpn, mpn, mfr, preferred_flag BOOLEAN DEFAULT FALSE, created_at, updated_at)`. |
| `detect_alternates(rfq_id)` | Ensures the table exists; if `update_alternatives` already has rows for this `rfq_id`, returns `{"status": "failed", "error": ..., "existing_rows": N}`. Otherwise selects `bom_item_id, cpn, mpn, mfr` from `processed_bom_items` for the RFQ where `cpn` is non-null/non-empty, groups by `cpn` to find CPNs with >1 distinct `mpn`, and inserts one row per alternate into `update_alternatives` inside a transaction. Returns `{"status": "success", "cpns_flagged": N, "alternates_found": N}` (or `alternates_found: 0` early-outs if there's no data / no duplicates). |

### Internal execution flow

```
detect_alternates(rfq_id)
 ├─ _ensure_alternatives_table(conn)
 ├─ if COUNT(update_alternatives WHERE rfq_id) > 0 → return failure
 ├─ df = SELECT bom_item_id, cpn, mpn, mfr FROM processed_bom_items WHERE rfq_id AND cpn NOT NULL/empty
 ├─ if df empty → return success, 0/0
 ├─ mpn_counts = df.groupby("cpn")["mpn"].nunique(); duplicate_cpns = those > 1
 ├─ if none → return success, 0/0
 ├─ BEGIN TRANSACTION
 │    for cpn in duplicate_cpns: for row in group: INSERT INTO update_alternatives (...)
 ├─ COMMIT (or ROLLBACK + re-raise on exception)
 └─ return {"status": "success", "cpns_flagged", "alternates_found"}
```

### Configuration usage

`DB_PATH` from `config.py`.

### Related files

Near-duplicate of `distributor_pricing/detect_alternates.py`, which *is*
the version actually invoked (as `@mcp.tool() def detect_alternates` in
`distributor_pricing/mcp_server.py`) — see the
[Inactive tools](#inactive-commented-out-tools) note under `mcp_server.py`
above. Referenced by a commented-out import in `intake/mcp_server.py`
(`# from detect_alternates import detect_alternates as _detect_alternates`).

---

## apply_alternatives.py

**File path:** `SRIM/Tools/I n D/intake/apply_alternatives.py`

### Purpose

Applies a user's alternate-part decisions (recorded in
`update_alternatives` by `detect_alternates.py`) back onto
`processed_bom_items`: for each CPN, keeps only the row(s) with the
user-preferred MPN and deletes the rest. **Not currently wired into
`mcp_server.py`** (commented out there, same as `detect_alternates.py`).

### Responsibilities

- Read all `(cpn, mpn, preferred_flag)` decisions for an `rfq_id` from
  `update_alternatives`.
- Validate that **every** CPN has exactly one `preferred_flag = TRUE` row
  before making any change — if any CPN has zero or multiple preferred
  rows, abort the whole call with a list of the invalid CPNs (no partial
  application).
- Delete all non-preferred MPN rows per CPN from `processed_bom_items`
  inside a single transaction.

### Dependencies

- **Third-party:** `duckdb`.
- **Local:** `config.DB_PATH`.

### Public interfaces

| Function | Description |
|---|---|
| `apply_alternatives(rfq_id)` | Loads decisions for the RFQ; if none, returns a "no selections found" success message. Validates exactly one preferred MPN per CPN (returns `{"status": "failed", "error": ..., "invalid_cpns": [...]}` otherwise). Deletes every `processed_bom_items` row for each CPN whose `mpn != preferred_mpn`, inside `BEGIN/COMMIT` (rolls back on exception). Returns `{"status": "success", "cpns_processed", "mpns_removed", "remaining_mpn_by_cpn"}`. |

### Internal execution flow

```
apply_alternatives(rfq_id)
 ├─ decisions_df = SELECT cpn, mpn, preferred_flag FROM update_alternatives WHERE rfq_id
 ├─ if empty → return success/no-op
 ├─ for each distinct cpn: validate exactly 1 preferred_flag=TRUE row
 │      → if not, collect into `invalid`
 ├─ if invalid → return failure (no DB writes)
 ├─ BEGIN TRANSACTION
 │    for cpn, preferred_mpn: DELETE FROM processed_bom_items WHERE rfq_id AND cpn AND mpn != preferred_mpn
 ├─ COMMIT (or ROLLBACK + re-raise)
 └─ return {"status": "success", "cpns_processed", "mpns_removed", "remaining_mpn_by_cpn"}
```

### Configuration usage

`DB_PATH` from `config.py`.

### Related files

Near-duplicate of `distributor_pricing/apply_alternatives.py`, which is
the version actually registered as `@mcp.tool()` in
`distributor_pricing/mcp_server.py`. Referenced by a commented-out import
in `intake/mcp_server.py`.

---

## matrix_bom_volume_enrichment.py

**File path:** `SRIM/Tools/I n D/intake/matrix_bom_volume_enrichment.py`

### Purpose

A **schema-flexible, standalone** enrichment tool for a completely
different BOM shape than `bom_processing.py` handles: a "matrix" BOM where
each Finished-Good assembly is its own **column** (not a row-level
`fg`/`Assembly` field), matched against a volume file that may define
multiple volume scenarios (V1, V2, ...). The module's own docstring is
explicit that it is intentionally independent from and does not import or
modify anything in `bom_processing.py`, `server.py` (likely a stale
reference — no `server.py` exists in this folder; probably means
`mcp_server.py`), or the database/enrichment modules.

### Responsibilities

- Auto-detect the real header row in a raw Excel sheet (rather than
  assuming row 0) by scoring rows against a set of anchor tokens
  (`CPN`, `ASSEMBLY`, `MPN`, `UOM`, etc.) and non-blank/next-row heuristics.
- Auto-detect an ID/FG column via alias list + regex fallback (never
  guesses — raises if nothing matches).
- Auto-detect one or more `VOLUME`/`VOL`/`V-<n>` style columns in a
  candidate volume file, and auto-select which sheet in a multi-sheet
  volume workbook actually qualifies as "the" volume sheet using both
  name-matching and **data-shape** checks (ID uniqueness ratio ≥ 90%,
  volume-column numeric fill ratio ≥ 90%) — explicitly designed to reject
  a sheet whose columns are merely *named* like volume columns but are
  mostly blank or non-uniquely keyed (a "decoy" sheet).
- Build a `{normalized_id: {volume_col: value}}` map from the chosen
  volume sheet, coercing non-numeric cells to 0.0 with collected warnings,
  and warning (not failing) on duplicate IDs (last-row-wins).
- Match BOM matrix column headers against the volume map's FG keys, and
  append one `Required_Qty_V1`, `Required_Qty_V2`, ... column per detected
  volume scenario, computed as `Σ(FG column cell × that FG's volume value)`
  per row. Refuses to overwrite an existing column with the same
  generated name.
- Write the enriched matrix to a new `.xlsx` (default name
  `<input>_with_required_qty.xlsx`) and print a full validation report.

### Dependencies

- **Third-party:** `pandas`.
- **Standard library:** `re`, `sys`, `collections.Counter`, `pathlib.Path`.
- No local imports.

### Public interfaces

| Function | Description |
|---|---|
| `_normalize_header(col) -> str` | Collapses whitespace, uppercases. |
| `_normalize_id_value(value) -> str` | Same normalization for ID cell values. |
| `_dedupe_columns(columns)` | Appends `.1`, `.2`, ... suffixes to repeated column names. |
| `detect_header_row(raw_df, max_scan_rows=10) -> int` | Scores the first N rows for header-likeness (blank ratio, next-row non-blank, anchor-token hits); returns the best 0-indexed row or raises `ValueError`. |
| `load_bom_matrix(bom_file, sheet_name=None)` | Reads a sheet with `header=None`, detects the header row, dedupes column names, drops fully-blank data rows; returns `(bom_df, header_row_index_0based, chosen_sheet_name)`. |
| `find_id_column(columns, aliases=ID_COLUMN_ALIASES, pattern=ID_COLUMN_PATTERN)` | Exact-alias match wins over regex-pattern match; leftmost column wins ties; raises `ValueError` if nothing matches. |
| `find_volume_columns(columns)` | Returns all columns matching `VOLUME_COLUMN_PATTERN` (e.g. `VOLUME`, `VOL-1`, `V2`), left-to-right. |
| `score_sheet_as_volume_sheet(df) -> dict` | Computes `id_col`, `volume_cols`, `id_unique_ratio`, `volume_fill_ratio`, and a boolean `qualifies` (both ratios ≥ 0.9); returns a rejection `reason` if not. |
| `select_volume_sheet(volume_file, sheet_name=None)` | Scores every sheet (or just `sheet_name` if given); raises if zero or more than one sheet qualifies (ambiguity is a hard error, not a guess); returns `(chosen_sheet_name, chosen_df, chosen_score, rejections)`. |
| `build_multi_volume_map(volume_df, id_col, volume_cols)` | Returns `({normalized_id: {orig_vol_col: float}}, warnings)`; non-numeric cells → 0.0 + warning; duplicate IDs → warning, last-row-wins. |
| `match_fg_columns(bom_columns, volume_map)` | Matches BOM matrix column headers (normalized) against volume map keys; returns matched columns, FGs unmatched in the BOM, and duplicate BOM FG columns after normalization. |
| `compute_required_qty_columns(bom_df, matched_columns, volume_map, volume_cols_ordered)` | Appends `Required_Qty_V<n>` columns (NaN cells treated as 0); raises if a same-named column already exists. |
| `enrich_bom_with_volume(bom_file, volume_file, bom_sheet_name=None, volume_sheet_name=None, output_file=None)` | Top-level orchestrator: loads the BOM matrix, finds its (optional/informational) ID column, selects+scores the volume sheet, builds the volume map, matches FG columns, computes the new columns, writes the output `.xlsx`, and returns a detailed report dict (sheet names, header row index, matched/unmatched FG counts, all warning categories, output path). |
| `print_report(report)` | Pretty-prints the report dict returned by `enrich_bom_with_volume`. |
| `__main__` CLI | `python matrix_bom_volume_enrichment.py <consolidated_bom.xlsx> <volume.xlsx> [output.xlsx]`. |

### Internal execution flow

```
enrich_bom_with_volume(bom_file, volume_file, ...)
 ├─ load_bom_matrix(bom_file) → (bom_df, header_row_idx, sheet)
 ├─ find_id_column(bom_df.columns)           [best-effort, informational only]
 ├─ select_volume_sheet(volume_file)
 │    └─ score_sheet_as_volume_sheet() per candidate sheet → pick the unique qualifier
 ├─ build_multi_volume_map(volume_df, id_col, volume_cols)
 ├─ match_fg_columns(bom_df.columns, volume_map)
 ├─ compute_required_qty_columns(bom_df, matched_columns, volume_map, volume_cols_ordered)
 ├─ result_df.to_excel(output_file)
 └─ return report dict
```

### Configuration usage

None — fully self-contained, no DB, no config import, no LLM call.

### Related files

Explicitly declared independent from `bom_processing.py` and the
database/enrichment modules. Related in *purpose* (volume-driven required-
quantity calculation) but incompatible in *input shape* — this module is
for matrix-style BOMs (one column per FG), while `bom_processing.py`
handles flat/row-style BOMs. Its default output naming convention
(`_with_required_qty.xlsx`) matches the file
`Consolidated-Centum BoM (1)_with_required_qty.xlsx` present in this same
folder, strongly suggesting that file is this script's own sample output.

---

## test_consolidation.py

**File path:** `SRIM/Tools/I n D/intake/test_consolidation.py`

### Purpose

A reusable, CLI-driven **end-to-end validation harness** for the intake
consolidation pipeline. Its own docstring states it "runs the SAME,
unmodified functions" that `mcp_server.py`'s `import_bom` tool uses
(`bom_processing.py` + `bom_to_database.py`), and does not alter any
consolidation/volume/DuckDB logic — it only calls existing functions and
reports on what they produce, stage by stage.

### Responsibilities

- Re-run the schema-mapping/standardization/volume-expansion/consolidation
  steps with the exact same functions `process_bom()` calls internally
  (imported directly, not via `process_bom()`), so each intermediate
  DataFrame can be inspected and printed.
- Validate `required_qty == bom_qty × volume` both on a 5-row sample and
  across the full dataset.
- Validate DuckDB round-tripping: pre-existing rows for a given `rfq_id`
  are deleted for a clean re-insert, `process_bom_to_database` is called,
  then the DB is re-queried to check row counts, unique MPN counts,
  duplicate `(cpn, mpn)` pairs (must be zero, since `consolidate_bom`
  groups on MPN), and duplicate raw MPN count (informational — a repeat
  here is valid alternate-part data, not a bug).
- Export the freshly-queried DuckDB rows to Excel/CSV (chosen by output
  extension) as the final validation artifact.
- Auto-generate a timestamped `TEST_<timestamp>` RFQ ID when `--rfq-id` is
  omitted, so repeated runs never collide with real data.

### Dependencies

- **Third-party:** `duckdb`, `pandas`.
- **Standard library:** `argparse`, `json`, `os`, `sys`, `datetime`,
  `pathlib.Path`.
- **Local:** `config.DB_PATH`; from `bom_processing`:
  `semantic_mapping`, `volume_semantic_mapping`, `standardize_bom`,
  `build_volume_map`, `expand_bom_with_volume`, `consolidate_bom`,
  `detect_duplicate_cpn_conflicts`; from `bom_to_database`:
  `process_bom_to_database`.

### Public interfaces

| Function | Description |
|---|---|
| `section(title)` | Prints a titled separator block to stdout. |
| `run(bom_file, volume_file, rfq_id, output_csv)` | The full 6-step harness (input validation → volume processing validation → consolidation validation → DuckDB validation → export validation → final verification report); returns a summary report dict and prints extensively at each stage. |
| `main()` | `argparse`-based CLI entry point: positional `bom_file`, `volume_file`; optional `--rfq-id`, `--output`. Calls `run(...)`. |

### Internal execution flow

```
run(bom_file, volume_file, rfq_id, output_csv)
 STEP 1: read BOM+Volume raw, print detected columns/row counts,
         reproduce mapping+standardize+expand exactly as process_bom() does
 STEP 2: print volume map size, root-assembly/leaf counts, per-row and
         full-dataset required_qty == bom_qty*volume checks
 STEP 3: consolidate_bom(), detect_duplicate_cpn_conflicts(), show a
         concrete before/after example of a merged (cpn, mpn) pair,
         print UOM values before/after normalization
 STEP 4: connect to DuckDB, delete any pre-existing rows for rfq_id,
         call process_bom_to_database(), re-query counts/uniques/dup checks
 STEP 5: query DuckDB fresh (ORDER BY mpn) and export to the given
         .xlsx/.csv path
 STEP 6: build and print a final JSON summary report + a 10-row sample
         table of the exported data
```

### Configuration usage

`DB_PATH` from `config.py` (same DuckDB file as the live pipeline —
running this script against a real `rfq_id` would collide with real data,
hence the auto-timestamped test ID default).

### Related files

Directly parallels `mcp_server.py`'s `import_bom` tool logic without going
through the MCP/Postgres-gateway layer (it takes file paths as CLI args
instead of resolving them from `rfq_file_telemetry`). Its default output
naming (`consolidated_bom_export_<rfq_id>.csv`) matches
`consolidated_bom_export_TEST_FIX_MPN_001.csv` and
`consolidated_bom_export_TEST_SCRIPT_RUN_001.csv` found in this folder —
those are almost certainly saved outputs from prior runs of this script.

---

## test_filter_alternates.py

**File path:** `SRIM/Tools/I n D/intake/test_filter_alternates.py`

### Purpose

Explicitly labeled in its own docstring as a **"TEMPORARY TEST-ONLY
script."** Simulates a possible future alternate-approval step by taking
an already-consolidated BOM export and keeping only the first row per
duplicate CPN (no real preference logic — just first-occurrence
de-duplication). Does not touch the real intake pipeline, DuckDB, or
`distributor_pricing` in any way; it only reads one Excel file and writes
another.

### Responsibilities

- Read a consolidated BOM export (`Centum_consolidated_output.xlsx` by
  default).
- Group by `cpn`, identify groups with more than one row (candidate
  "alternates").
- Drop all but the first row per `cpn` (`drop_duplicates(subset="cpn",
  keep="first")`).
- Write the filtered result and print a validation report comparing the
  result against a hardcoded `EXPECTED_FINAL_COUNT = 36`, with an explicit
  note in the code that a mismatch here reflects the actual input data
  shape, not a script bug (since "one row per unique CPN" is
  mathematically always `df['cpn'].nunique()`).

### Dependencies

- **Third-party:** `pandas`.
- **Standard library:** `sys`, `pathlib.Path`.
- No local imports.

### Public interfaces

| Function | Description |
|---|---|
| `filter_alternates(input_path, output_path)` | Reads `input_path`, computes duplicate-CPN group stats, drops duplicate CPNs keeping the first occurrence, writes `output_path`, prints a full report, and returns a stats dict (`original_count`, `duplicate_cpn_groups`, `removed_count`, `final_count`, `matches_expected`). |
| `__main__` CLI | `python test_filter_alternates.py [input.xlsx] [output.xlsx]`, defaulting to `Centum_consolidated_output.xlsx` → `Centum_consolidated_without_alternates.xlsx`. |

### Internal execution flow

```
filter_alternates(input_path, output_path)
 ├─ df = pd.read_excel(input_path)
 ├─ dup_groups = df.groupby("cpn").size() > 1
 ├─ filtered_df = df.drop_duplicates(subset="cpn", keep="first")
 ├─ filtered_df.to_excel(output_path)
 └─ print report, compare final_count to EXPECTED_FINAL_COUNT=36
```

### Configuration usage

None.

### Related files

Its default input/output filenames are exactly
`Centum_consolidated_output.xlsx` and
`Centum_consolidated_without_alternates.xlsx`, both present in this
folder — confirming those two Excel files are this script's own sample
input/output pair, not independent data files.

---

## .claude/settings.local.json

**File path:** `SRIM/Tools/I n D/intake/.claude/settings.local.json`

### Purpose

Local Claude Code permission override for this folder, scoped only to
this project directory (not the global `~/.claude` config).

### Contents

```json
{
  "permissions": {
    "allow": ["Bash(python *)"]
  }
}
```

Grants blanket allow-listing for any `python ...` Bash invocation when
Claude Code is operating inside this folder — presumably to reduce
permission prompts while iterating on the CLI scripts (`bom_processing.py`,
`test_consolidation.py`, etc.) during development.

### Related files

Analogous to `centum intake/.claude/settings.local.json` and
`distributor_pricing/.claude/settings.local.json`, each folder having its
own scoped Claude Code permissions file.

---

## Data / sample-fixture files

The remaining files in this folder are Excel workbooks and CSV exports —
sample/test data consumed or produced by the scripts above, not source
code. They are documented here for completeness since the task calls for
every file in the folder to be covered. Column lists and row counts below
were obtained by opening each file directly with pandas/openpyxl.
Purpose/origin statements are best-effort inference from filename, sheet
structure, and cross-references to the scripts that default to these
exact filenames — marked **Inference** where not otherwise confirmed.

### BOM-Centum (1).xlsx

**File path:** `SRIM/Tools/I n D/intake/BOM-Centum (1).xlsx` (16.4 KB)

- Sheet `Requirement`: columns `CPN, Description, MPN, Vl1, Vl2` — 8 rows.
- Sheet `BOM`: columns `CPN, Description, MPN, Commodity, Quantity, UOM,
  Drawing Reference, Reference Designators, VL 1, Vl2` — 122 rows.

**Inference:** a raw customer BOM export for the "Centum" customer,
paired with its own volume/requirement tab in the same workbook (a
two-tab per-project source file: parts list + planning volumes). This is
example/sample input data for `bom_processing.py`, not a file the code
reads by a hardcoded path.

### Centum_BOM.xlsx

**File path:** `SRIM/Tools/I n D/intake/Centum_BOM.xlsx` (13.8 KB)

- Sheet `BOM`: columns `CPN, Description, MPN, Commodity, Quantity, UOM,
  Drawing Reference, Reference Designators, VL 1, Vl2` — 122 rows.

**Inference:** the same 122-row BOM as `BOM-Centum (1).xlsx`'s `BOM` tab,
extracted into its own standalone workbook — likely used as a plain
single-sheet BOM input when testing `bom_processing.py`'s `<bom.xlsx>` CLI
argument, since that pipeline expects one BOM file and one separate
Volume file rather than a combined two-tab workbook.

### Centum_consolidated_output.xlsx

**File path:** `SRIM/Tools/I n D/intake/Centum_consolidated_output.xlsx` (12.5 KB)

- Sheet `Sheet1`: columns `bom_item_id, rfq_id, file_name, parent_fg, fg,
  cpn, description, mfr, mpn, commodity, bom_qty, volume, required_qty,
  uom, ce_remarks, item_num, part_type, ltb_date, common_aml,
  change_remarks, exported_at, imported_at` (22 columns, matching the
  `processed_bom_items` DB schema shape) — 57 rows.

**Inference:** this is the pipeline's own consolidated-and-persisted BOM,
almost certainly exported from DuckDB's `processed_bom_items` table after
a real or test run of `import_bom`/`process_bom_to_database`. It is also
the **default input file** for `test_filter_alternates.py`
(`DEFAULT_INPUT = "Centum_consolidated_output.xlsx"`), confirming it is a
saved sample of consolidated output rather than a raw source document.

### Centum_consolidated_without_alternates.xlsx

**File path:** `SRIM/Tools/I n D/intake/Centum_consolidated_without_alternates.xlsx` (10.6 KB)

- Sheet `Sheet1`: same 22 columns as `Centum_consolidated_output.xlsx` —
  40 rows (17 fewer than the 57-row source).

This is the **default output file** for `test_filter_alternates.py`
(`DEFAULT_OUTPUT = "Centum_consolidated_without_alternates.xlsx"`),
i.e. it is `Centum_consolidated_output.xlsx` run through
`filter_alternates()` (first-occurrence-per-CPN de-duplication). Its
row count (40) does not match that script's own
`EXPECTED_FINAL_COUNT = 36` constant, which the script's code
acknowledges may not be achievable on this exact input and treats as a
data-shape fact rather than a bug — consistent with what's observed here.

### Centum_Vol.xlsx

**File path:** `SRIM/Tools/I n D/intake/Centum_Vol.xlsx` (13.9 KB)

- Sheet `Requirement`: columns `CPN, Description, MPN, Vl1, Vl2` — 8 rows.

**Inference:** the `Requirement` (volume) tab from `BOM-Centum (1).xlsx`,
extracted into its own standalone workbook — the counterpart "Volume
file" to `Centum_BOM.xlsx`'s "BOM file", together forming a plausible
`<bom.xlsx> <volume.xlsx>` pair for `bom_processing.py`'s CLI or
`test_consolidation.py`.

### consolidated.xlsx

**File path:** `SRIM/Tools/I n D/intake/consolidated.xlsx` (265.9 KB —
largest file in the folder)

Multi-sheet real-world source workbook with non-trivial header layouts:

- Sheet `Consolidated material list`: 156 unnamed columns; the real
  header is not in row 0 — rows 3-5 contain a merged/date header block
  including "Tentative ETD", "WO completion Date", "WO Issued Date" — 119
  rows.
- Sheet `Pivot table`: an Excel PivotTable output — `Row Labels`, `Item
  Description`, `Manufacturer`, `MPN`, `Innotech UoM`, plus one column
  per UBR-numbered work order (`P1_UBRxxxxx...`), plus `Grand Total` —
  108 rows.
- Sheet `L2-BoM`: real header at row 3 (0-indexed): `UBR Number, BoM
  Level, Assy #, Harness priority, Priority_Assy#, Item Description, MPN,
  Manufacturer, BOM Qty, UOM, Innotech BoM Qty, Innotech UoM` — 481 rows.
- Sheet `Harness BOM-Working`: real header at row 1: `UBR Number, BoM
  Level, Assy #, Harness priority, Priority_Assy#, Part Number, MPN,
  Manufacturer, BOM Qty, UOM, Innotech BoM Qty, Innotech UoM` — 542 rows.
- Sheet `Harness BOM-Original`: real header at row 1: `UBR Number, Assy
  #, Part Number, MPN, Manufacturer, BOM Qty, UOM, BOM Level` — 542 rows.

**Inference:** a genuine customer/engineering multi-level wire-harness BOM
workbook (UBR-numbered sub-assemblies, multiple BOM-Level hierarchy
columns, an embedded pivot analysis) — a real raw source document, not
pipeline-generated output. Its headers are offset by several rows due to
merged title cells in at least 3 of 5 sheets, which is exactly the class
of problem `matrix_bom_volume_enrichment.py`'s `detect_header_row()` was
built to solve generically; `bom_processing.py`'s simpler
`pd.read_excel()` (row-0 header assumption) would misread this file
as-is.

### consolidated_BOM.xlsx

**File path:** `SRIM/Tools/I n D/intake/consolidated_BOM.xlsx` (11.1 KB)

- Sheet `Sheet1`: columns `mpn, bom_qty, volume, required_qty, fg, cpn,
  description, mfr, commodity, uom` (10 columns, lowercase — matches
  `consolidate_bom()`'s groupby/aggregate output columns exactly, before
  `bom_to_database.py` adds `file_name`/`parent_fg`/etc.) — 103 rows.

This is also `bom_processing.py`'s **own default CLI output filename**
(`_output_file = ... "consolidated_BOM.xlsx"` when no third argument is
given), so this file is almost certainly a saved sample output of running
`python bom_processing.py <bom> <volume>` directly — i.e. `consolidate_bom()`'s
result written straight to Excel, without the DB round-trip that adds the
extra `processed_bom_items` columns seen in `Centum_consolidated_output.xlsx`.

### consolidated_bom_export_TEST_FIX_MPN_001.csv

**File path:** `SRIM/Tools/I n D/intake/consolidated_bom_export_TEST_FIX_MPN_001.csv` (21.6 KB)

- Columns: same 22 as `Centum_consolidated_output.xlsx`
  (`bom_item_id` ... `imported_at`) — 104 rows.

This filename exactly matches `test_consolidation.py`'s default output
naming pattern, `consolidated_bom_export_<rfq_id>.csv`, with `rfq_id =
TEST_FIX_MPN_001` — i.e. this is a saved result of running
`test_consolidation.py` with `--rfq-id TEST_FIX_MPN_001`.
**Inference:** the `rfq_id` name ("FIX_MPN") suggests this run was
specifically exercising/validating an MPN-related bug fix in the
consolidation logic.

### consolidated_bom_export_TEST_SCRIPT_RUN_001.csv

**File path:** `SRIM/Tools/I n D/intake/consolidated_bom_export_TEST_SCRIPT_RUN_001.csv` (21.8 KB)

- Columns: same 22 as above — 103 rows (one fewer than the `FIX_MPN_001`
  run).

Same origin as the file above — a saved `test_consolidation.py` export,
this time for `rfq_id = TEST_SCRIPT_RUN_001`, i.e. a more generic
"exercise the script end-to-end" validation run rather than a targeted
bug-fix check. The near-identical row count between these two test
exports (103 vs 104) suggests they were run against the same or very
similar source BOM/Volume files at different points in development.

### Consolidated-Centum BoM (1).xlsx

**File path:** `SRIM/Tools/I n D/intake/Consolidated-Centum BoM (1).xlsx` (15.2 KB)

- Sheet `Consolidated BoM`: real header at row 5 (0-indexed): `Sl No.,
  Category, Sub category, CPN, Description, MFR1, MPN1, MFR2, MPN2, MFR3,
  MPN3, MFR4, MPN4`, followed by 8 columns named by specific build/work-order
  codes (e.g. `AD4ASOH100024000-B01`, ...), then `Grand Total, Required
  Qty, Ordering Qty, UOM` — 41 rows.

**Inference:** a genuine, human-authored consolidated BOM report for the
Centum customer, in "matrix" form — one column per build/work order,
plus up to 4 alternate MFR/MPN slots per part — rather than the
pipeline's native flat/row-per-part output shape. This is exactly the
input shape `matrix_bom_volume_enrichment.py` was written to handle (its
`ID_COLUMN_ALIASES` list explicitly includes `CPN`, and its
`VOLUME_COLUMN_PATTERN` is designed to match per-build-order columns like
these).

### Consolidated-Centum BoM (1)_with_required_qty.xlsx

**File path:** `SRIM/Tools/I n D/intake/Consolidated-Centum BoM (1)_with_required_qty.xlsx` (10.1 KB)

- Sheet `Sheet1`: `Unnamed: 0, Sl No., Category, Sub category, CPN,
  Description, MFR1, MPN1, MFR2, MPN2, MFR3, MPN3, MFR4, MPN4`, the same
  8 build-order columns as the file above, `Grand Total, Required Qty,
  Ordering Qty, UOM`, plus two new appended columns: `Required_Qty_V1,
  Required_Qty_V2` — 36 rows.

This filename exactly matches `matrix_bom_volume_enrichment.py`'s default
output naming (`<input>_with_required_qty.xlsx`), and it carries that
script's exact generated column names (`Required_Qty_V1`,
`Required_Qty_V2`). This is a **confirmed** (not inferred) sample output
of running `matrix_bom_volume_enrichment.py` against
`Consolidated-Centum BoM (1).xlsx` with some paired volume file (not
present under an obviously matching name in this folder — the volume
input for this specific run is not directly identifiable among the other
files, though `UBR Vol-1 Qty.xlsx` or `Centum_Vol.xlsx` are plausible
candidates based on shape). Row count (36) differs from the 41-row source
because `load_bom_matrix()` drops fully-blank rows.

### Multiple_BOM (4).xlsx

**File path:** `SRIM/Tools/I n D/intake/Multiple_BOM (4).xlsx` (39.1 KB)

- Sheet `Harness BOM-Original`: columns `BOM_ID, UBR Number, Assy #, Part
  Number, MPN, Manufacturer, BOM Qty, UOM, BOM Level` — 541 rows, with a
  clean header at row 0 (unlike the same-named sheet inside
  `consolidated.xlsx`, which has its header at row 1).

**Inference:** a raw multi-assembly harness BOM input file — the filename
("Multiple_BOM") suggests it was used to test handling of a BOM
containing multiple Finished-Good assemblies in one sheet (relevant to
`expand_bom_with_volume()`'s FG-detection logic, which must correctly
segment multiple FG sections within a single flat file). Its row count
(541, plus header = 542) matches `consolidated.xlsx`'s
`Harness BOM-Working`/`Harness BOM-Original` sheets almost exactly,
suggesting a shared lineage/source dataset between the two files, though
this one has already been normalized to a clean row-0 header and gained a
`BOM_ID` column not present in `consolidated.xlsx`'s version.

### UBR Vol-1 Qty.xlsx

**File path:** `SRIM/Tools/I n D/intake/UBR Vol-1 Qty.xlsx` (10.4 KB)

- Sheet `Sheet1`: columns `SL #, FG Item Part #, Vol-1` — 63 rows.

**Inference:** a simple Finished-Good-keyed volume/quantity lookup file
for a single volume scenario ("Vol-1") — a plausible "Volume file" input
for `bom_processing.py`'s `process_bom(bom_file, volume_file)` when
tested against a larger harness BOM such as `Multiple_BOM (4).xlsx` or
`consolidated.xlsx`'s harness sheets (63 rows is in a plausible range for
a list of distinct FG assemblies drawn from a several-hundred-row flat
BOM).

---

## Relationship to `scrub_mcp_server.py` and the `centum intake` pipeline

**Inference:** The relationship between `intake/mcp_server.py` (this
folder, port 8002) and `centum intake/scrub_mcp_server.py` (port 8004) is
not documented anywhere in either folder (no README exists in `intake/`),
so the following is inferred from reading both servers' source directly,
plus `centum intake/manage_backend.py` and `centum intake/fastapi_router.py`:

- **They are two different, independently-versioned BOM ingestion
  pipelines, not two versions of the same one.**
  - `intake/mcp_server.py` expects a **raw BOM Excel file + a separate
    Volume Excel file**, resolved from `rfq_file_telemetry` by
    `file_role IN ('BOM', 'VOLUME')` with no `version` concept at all, and
    writes fully volume-expanded, MPN-consolidated rows (with
    `required_qty`, mm-normalized `bom_qty`, etc.) into a
    `processed_bom_items` table, keyed by bare `rfq_id`.
  - `centum intake/scrub_mcp_server.py`'s `standardize_scrub_bom` expects
    a **single multi-sheet "SCRUB BOM" workbook** (sheets "SCRUB BOM",
    "Settings", "Batch"), resolved via `_fetch_file_path(session, rfq_id,
    version, "BOM")` — explicitly `version`-aware — and performs
    **schema mapping + standardization only** ("Does not perform volume
    expansion, consolidation, or duplicate-CPN detection — those are out
    of scope for this tool", per its own docstring), writing into three
    separate tables (`scrub_bom_items`, `volume`, `batch`) under a
    **versioned key** `f"{rfq_id}__v{version}"` (see `db.versioned_key`).
    It also owns three more tools (`standardize_quote_win`,
    `standardize_erp`, `standardize_costing_sheet`) for entirely different
    document types intake's `mcp_server.py` has no equivalent for.
- **Only `scrub_mcp_server.py` is live.** `centum intake/fastapi_router.py`
  hardcodes an allowlist of exactly four tool names —
  `centum_intake__standardize_scrub_bom`,
  `centum_intake__standardize_quote_win`, `centum_intake__standardize_erp`,
  `centum_intake__standardize_costing_sheet` — all from
  `scrub_mcp_server.py`. Neither `scan_local_file`/`import_bom` (this
  folder) nor anything from `distributor_pricing` appears in that
  allowlist, and neither appears in `manage_backend.py`'s `SERVICES` list
  or the live `.backend_services_state.json` PID registry.
- **Best-supported inference:** `intake/mcp_server.py` looks like an
  earlier or parallel design for BOM ingestion — built around a
  Volume-file-driven FG-expansion + MPN-consolidation model with its own
  antivirus-scanning stage — that has since been superseded in the
  live/orchestrated pipeline by `scrub_mcp_server.py`'s versioned,
  multi-document (SCRUB BOM/QuoteWin/ERP/Costing Sheet) standardize-only
  model, with volume/consolidation/alternates logic apparently intended to
  live downstream in other still-active services (e.g.
  `distributor_pricing`'s `enrich_bom`/`detect_alternates`/
  `apply_alternatives`, and possibly `centum intake/duck_db_api.py` or
  `db.py` for consolidation — not verified in this pass). This is an
  inference from code structure and the live-service allowlists, not a
  documented fact — no comment in either file states this history
  explicitly, and no README exists to confirm it.
- One piece of hard evidence supporting "superseded/parallel, not
  identical": the two pipelines write to **different DuckDB tables**
  (`processed_bom_items` for `intake/`, vs. `scrub_bom_items`/`volume`/
  `batch` for `scrub_mcp_server.py`) with different key schemes (bare
  `rfq_id` vs. versioned `rfq_id__vN`), so they cannot simply be two
  clients of the same data model — a consumer would need to know which
  pipeline actually ran for a given RFQ.

## Excluded items

Per the task instructions, the following were excluded from per-file
documentation:

- `__pycache__/` — compiled bytecode cache (`.pyc` files for
  `apply_alternatives`, `bom_processing`, `bom_to_database`, `config`,
  `detect_alternates`, `mcp_server`, `quote_win_processing`,
  `quote_win_to_database`, `scrub_bom_processing`,
  `scrub_bom_to_database`, `scrub_mcp_server`, `test_consolidation`,
  `test_filter_alternates`, `tool_calling` — note this cache curiously
  also contains `.pyc` files for `scrub_mcp_server.py`,
  `quote_win_processing.py`, etc., which are not `.py` files in this
  folder; **Inference:** this is likely a leftover from Python resolving
  `sys.path` entries shared with `centum intake/` during some prior
  interpreter invocation, or a copy/paste of a `__pycache__` directory —
  not evidence that those modules exist as source in `intake/`).
- No `.git/` directory is present in this folder.
- No separate "generated output" directory exists; the Excel/CSV data
  files are catalogued above in the [Data / sample-fixture
  files](#data--sample-fixture-files) section rather than skipped, since
  they are within the ~25-file count the task asked to cover and are not
  purely ephemeral build artifacts.
