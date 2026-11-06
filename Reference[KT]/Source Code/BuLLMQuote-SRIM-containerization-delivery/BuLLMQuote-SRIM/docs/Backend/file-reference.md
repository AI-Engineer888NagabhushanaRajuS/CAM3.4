# Centum Intake — Backend File Reference

Authoritative, per-file reference for every top-level file in
`C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum intake\`.

This document intentionally does **not** recurse into subfolders
(`reporting_module/`, `database/`, `test_1`..`test_21`, `staged/`, `Test_fixes/`,
`deprecated/`, `service_logs/`, `__pycache__/`, `database_backup_*/`, `cam_logo/`,
`.claude/`) — those are out of scope here and documented elsewhere.

The platform is a BOM/RFQ costing pipeline: a customer uploads a BOM (and,
optionally, QuoteWin/Costing Sheet/ERP files), a Dify workflow ("the DMR") drives
a step-by-step "skill" execution loop against this backend via an MCP gateway
("MCP Jungle"), each skill standardizes one input file into DuckDB, and a
separate `reporting_module` (out of scope, documented elsewhere) generates the
final costed BOM ("CBOM") and its Excel/report exports. `manage_backend.py` is
the single entry point that starts/stops/health-checks all 10 backend services
this system needs (7 of which are files in this folder).

## Table of Contents

1. [`config.py`](#configpy)
2. [`db.py`](#dbpy)
3. [`tool_calling.py`](#tool_callingpy)
4. [`manage_backend.py`](#manage_backendpy)
5. [`.backend_services_state.json`](#backend_services_statejson)
6. [`fastapi_router.py`](#fastapi_routerpy)
7. [`hitl_router.py`](#hitl_routerpy)
8. [`upload_server.py`](#upload_serverpy)
9. [`duck_db_api.py`](#duck_db_apipy)
10. [`bom_qa_lookup_server.py`](#bom_qa_lookup_serverpy)
11. [`scrub_mcp_server.py`](#scrub_mcp_serverpy)
12. [`scrub_bom_processing.py`](#scrub_bom_processingpy)
13. [`scrub_bom_to_database.py`](#scrub_bom_to_databasepy)
14. [`quote_win_processing.py`](#quote_win_processingpy)
15. [`quote_win_to_database.py`](#quote_win_to_databasepy)
16. [`erp_processing.py`](#erp_processingpy)
17. [`erp_to_database.py`](#erp_to_databasepy)
18. [`costing_sheet_processing.py`](#costing_sheet_processingpy)
19. [`costing_sheet_to_database.py`](#costing_sheet_to_databasepy)
20. [`test_hierarchy_multiplier.py`](#test_hierarchy_multiplierpy)
21. [`test_quote_win_processing.py`](#test_quote_win_processingpy)
22. [`test_scrub_bom_processing.py`](#test_scrub_bom_processingpy)
23. [`clear_demo_data.py`](#clear_demo_datapy)
24. [`backup_postgres_demo_data.py`](#backup_postgres_demo_datapy)
25. [`master_test_summary.md`](#master_test_summarymd)

Additional non-code top-level artifacts observed but not documented in detail
(data/state, not source code): `price_mismatch_v2.pkl` (a pickle file, purpose
not derivable from the top-level scan; **Inference:** likely a cached
model/lookup artifact used by one of the processing or reporting modules).

---

## `config.py`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum intake\config.py`

**Purpose:** Single centralized configuration point defining the URL of the
external "MCP Jungle" gateway that `tool_calling.py` (and, independently,
`fastapi_router.py`, which hardcodes its own copy — see below) talk to. Pure
infrastructure/config role, no business logic.

**Responsibilities:**
- Read the `MCP_JUNGLE_URL` environment variable, falling back to a default.
- Expose that value as a module-level constant for import elsewhere.

**Dependencies:**
- Stdlib: `os`.
- No third-party or local module imports. No `sys.path` manipulation.

**Public interfaces:**
- `MCP_JUNGLE_URL` (module-level `str` constant) — the MCP Jungle gateway
  JSON-RPC endpoint. Default: `"http://localhost:8080/mcp"`.

**Internal execution flow:** Trivial — a single expression,
`os.environ.get("MCP_JUNGLE_URL", "http://localhost:8080/mcp")`, evaluated once
at import time.

**Configuration usage:**
- Env var `MCP_JUNGLE_URL` (default `http://localhost:8080/mcp`).

**Related files:** Imported by `tool_calling.py` (`from config import
MCP_JUNGLE_URL`). Note: `fastapi_router.py` does **not** import this constant —
it independently hardcodes its own module-level `MCP_JUNGLE_URL =
"http://localhost:8080/mcp"` string. This is a minor duplication/drift risk: if
`MCP_JUNGLE_URL` is ever overridden via environment variable for
`tool_calling.py`, `fastapi_router.py`'s own `get_routing_sequence` endpoint
(which builds its own session directly against the hardcoded literal) will not
pick up the override.

---

## `db.py`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum intake\db.py`

**Purpose:** Shared Postgres data-access layer for the RFQ execution/workflow
engine. Bridges two logical databases:
- `logic_db` — workflow configuration: `quote_routing_profiles` (ordered list
  of MCP tool names per named profile, e.g. `Standard_BOM_Flow`) and
  `system_skills_registry` (skill metadata keyed by index or MCP tool name).
- `file_metadata_db` — runtime state: `rfq_process_tracking` (per-`(rfq_id,
  version)` execution progress, `rfq_process_stage` = integer "skill index",
  plus a `hitl_required` pause flag) and `rfq_file_telemetry` (per-version
  uploaded-file records, referenced from other files but not queried directly
  in this module).

This is the module that answers "what skill/tool runs next for this RFQ" and
"has this RFQ's human-in-the-loop gate been satisfied" — the backbone of the
whole step-by-step DMR execution loop.

**Responsibilities:**
- Provide context-managed connections to both databases.
- Idempotently migrate `rfq_process_tracking`/`rfq_file_telemetry` schema to
  support multiple versions per `rfq_id` (composite PK, `is_active` flag,
  partial unique index enforcing "one active version per rfq_id").
- Resolve the active version for a given `rfq_id`.
- Build the internal DuckDB-side scoping key for a given `(rfq_id, version)`.
- Read/advance/set the current skill index (`rfq_process_stage`) for the
  active version of an RFQ.
- Track and query a `hitl_required` boolean per active RFQ version.
- Look up routing sequences for a named quote-routing profile.
- Look up skill metadata by index or by MCP tool name.
- Provide higher-level "advance execution" / "get current execution" helpers.

**Dependencies:**
- Stdlib: `os`, `contextlib.contextmanager`; `from __future__ import
  annotations`.
- Third-party: `psycopg2`, `psycopg2.extras.RealDictCursor`.
- No local module imports, no `sys.path` manipulation. This is a leaf module —
  everything else imports it, it imports nothing project-local.

**Public interfaces:**
- `get_logic_connection()` — contextmanager; yields a `psycopg2` connection to
  `logic_db`, closes on exit.
- `get_metadata_connection()` — contextmanager; yields a `psycopg2` connection
  to `file_metadata_db`, closes on exit.
- `ensure_version_schema()` — idempotent migration: adds `version`/`is_active`
  columns to `rfq_process_tracking` and `version` to `rfq_file_telemetry`,
  repoints the FK, adds a partial unique index for "one active version per
  rfq_id."
- `get_active_version(rfq_id: str) -> int` — returns the active version number
  for an rfq_id; raises `Exception` if none exists.
- `versioned_key(rfq_id: str, version: int) -> str` — returns the bare
  `rfq_id` for `version <= 1`, else `f"{rfq_id}__v{version}"`.
- `get_routing_sequence(profile_name: str = "Standard_BOM_Flow") -> list` —
  fetches the live (uncached) `routing_sequence` array for a named profile;
  raises `Exception` if not found.
- `get_current_skill_index(rfq_id: str) -> int` — returns `rfq_process_stage`
  for the active version; raises `Exception` if the rfq_id has no active row.
- `increment_skill_index(rfq_id: str) -> int` — blind `+1` on
  `rfq_process_stage` for the active version; commits; raises `Exception` if no
  row updated.
- `advance_skill_index_to_at_least(rfq_id: str, min_index: int) -> int` — sets
  `rfq_process_stage = GREATEST(current, min_index)`; idempotent and never
  regresses; commits; raises `Exception` if no row updated.
- `set_skill_index(rfq_id: str, skill_index: int)` — direct assignment of
  `rfq_process_stage` for the active version; commits; returns `None`.
- `set_hitl_required(rfq_id: str, value: bool) -> None` — sets the
  `hitl_required` flag for the active version; commits.
- `get_hitl_state(rfq_id: str)` — returns `(rfq_process_stage, hitl_required)`
  tuple for the active version, or `None` if no active row.
- `get_skill_by_index(skill_index: int)` — returns a dict
  (`skillIndex`/`skillCode`/`skillName`/`macroCategory`/`macroCategoryName`)
  from `system_skills_registry`; raises `Exception` if not found.
- `get_skill_by_code(mcp_tool_name: str)` — same shape, keyed by
  `mcp_tool_name`; raises `Exception` if not found.
- `advance_execution(rfq_id: str)` — composes `increment_skill_index` +
  `get_skill_by_index`; returns the new skill's metadata dict.
- `get_current_execution(rfq_id: str)` — composes `get_current_skill_index` +
  `get_skill_by_index` without mutating state.

**Internal execution flow:**

- **`ensure_version_schema()`**: (1) Queries `information_schema.columns` to
  check whether `rfq_process_tracking.version` exists; if absent, runs DDL to
  add `version INTEGER NOT NULL DEFAULT 1`, add `is_active BOOLEAN NOT NULL
  DEFAULT true`, drop the old FK on `rfq_file_telemetry`, drop and recreate the
  PK on `rfq_process_tracking` as composite `(rfq_id, version)`. (2)
  Separately checks `rfq_file_telemetry.version`; if absent, adds `version
  INTEGER NOT NULL DEFAULT 1` and a new composite FK `(rfq_id, version)
  REFERENCES rfq_process_tracking(rfq_id, version) ON DELETE CASCADE`. (3)
  Unconditionally (re-)creates a partial unique index
  `idx_rfq_process_tracking_one_active ON rfq_process_tracking(rfq_id) WHERE
  is_active` and a plain index on `rfq_file_telemetry(rfq_id, version)`. (4)
  Commits once. Both migration blocks are individually gated by existence
  checks, so repeated calls after first success are cheap no-ops (just the
  `information_schema` lookups). All 9 pre-existing `rfq_process_tracking`
  rows and 20 pre-existing `rfq_file_telemetry` rows at the time this was
  written got `version=1, is_active=true` automatically via column defaults —
  no manual backfill needed.
- **`versioned_key`**: pure logic, no DB access. `version <= 1` returns the
  bare `rfq_id` — this is deliberate backward compatibility: every RFQ that
  existed before the versioning feature shipped has its DuckDB rows stored
  under the plain rfq_id with no suffix, and giving version 1 its own suffix
  would silently orphan all of that data. Only version 2+ (which by
  construction can only be created after this feature existed) gets a real
  `__v{n}` suffix.
- **`advance_skill_index_to_at_least`**: uses `GREATEST(rfq_process_stage,
  %s)` specifically so it's safe to call more than once (e.g. a retried
  request) and can never move the stage backward. This exists because
  `hitl_router.py`'s `resolve_final_selection` confirm flow needs to jump the
  stage unambiguously *past* the `resolve_final_selection` skill's own
  position in the routing sequence — a blind `increment_skill_index` (`+1`)
  only reaches that skill's own position again (since
  `resolve_final_selection` always returns `hitl=1` and therefore never
  self-advances), which Dify's own "is this RFQ still HITL-pending" check then
  reads as "still not approved," aborting every resume attempt.
- **`advance_execution`**: two-step compose (increment, then look up by new
  index) — not a single transaction spanning both steps (separate connections
  are opened/closed inside each call).

**Configuration usage:**
- Env var `LOGIC_DB_URL` — required, no fallback. `db.py` raises a `KeyError`
  at import time if unset.
- Env var `FILE_METADATA_DB_URL` — required, no fallback, same behavior.
- **Security note (resolved):** both used to embed a plaintext Postgres
  username/password directly in source as a fallback default. That fallback
  has been removed — both env vars are now hard requirements (see
  `clear_demo_data.py` and `backup_postgres_demo_data.py` below, both of which
  import these constants from `db.py`). Set both in an untracked `.env` file;
  the previously-hardcoded password should still be rotated on the actual
  Postgres instance, since it was visible in source/logs on this machine
  regardless of what's committed to git.
- Does not import/use `config.py`.

**Related files:** This is a leaf/foundation module. Directly imported by:
`fastapi_router.py`, `hitl_router.py`, `duck_db_api.py`, `upload_server.py`,
`scrub_mcp_server.py`, `clear_demo_data.py`, `backup_postgres_demo_data.py`.
Its docstring notes it shares a migration idiom with
`reporting_module/final_selection.py`'s `ensure_conflicts_table()` (same
pattern applied to a different table) — not an import relationship, just a
noted convention.

---

## `tool_calling.py`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum intake\tool_calling.py`

**Purpose:** Thin JSON-RPC 2.0 client that forwards tool-execution requests to
the external "MCP Jungle" gateway (a multi-server MCP proxy sitting in front of
Postgres-MCP and other backing MCP servers), handling the MCP session
handshake, tool listing, and tool invocation.

**Responsibilities:**
- Establish and initialize an MCP protocol session against the gateway
  (`initialize` request + mandatory `notifications/initialized` notification).
- Persist the gateway-assigned session ID (`Mcp-Session-Id` header) on the
  `requests.Session` for all subsequent calls in that session.
- List tools available from a specific downstream MCP server behind the
  gateway.
- Invoke a named tool with arguments via `tools/call`, with a 300-second
  timeout to tolerate slow LLM-backed tools.
- Generate monotonically increasing JSON-RPC request IDs safe for concurrent
  use.
- Provide a CLI/demo entry point that opens a session and prints the tool
  catalog.

**Dependencies:**
- Stdlib: `itertools`, `json`.
- Third-party: `requests`.
- Local: `config` (`from config import MCP_JUNGLE_URL`). No `sys.path`
  manipulation.

**Public interfaces:**
- `_request_id` (module-level `itertools.count(1)`) — yields monotonically
  increasing integers for JSON-RPC `id` fields.
- `create_session()` — no params. Performs the MCP handshake against
  `MCP_JUNGLE_URL`; returns a configured `requests.Session`.
- `list_tools(session)` — sends `tools/list` scoped to `server_id:
  "postgres-mcp"` (hardcoded); returns the parsed JSON response.
- `call_tool(session, tool_name, arguments)` — sends `tools/call` with
  `params.name`/`params.arguments`, `timeout=300`; returns the parsed JSON
  response.
- `if __name__ == "__main__":` block — creates a session, lists tools, prints
  them pretty-printed as JSON.

**Internal execution flow:**

- **`create_session()`**:
  1. Creates a `requests.Session()`.
  2. Sets headers `Content-Type: application/json` and
     `MCP-Protocol-Version: 2025-11-25`.
  3. Builds an `initialize` JSON-RPC payload declaring `protocolVersion`,
     capabilities (`roots.listChanged=True`, empty `sampling`), and
     `clientInfo` (`python-tool-client`, `1.0.0`).
  4. POSTs to `MCP_JUNGLE_URL` (`timeout=30`), calls `raise_for_status()`.
  5. Reads the `Mcp-Session-Id` response header; if present, sets it on the
     session's headers for reuse.
  6. Sends a `notifications/initialized` JSON-RPC notification (no `id`) to
     finalize the handshake — required or the gateway won't attach external
     server tools to the session. Response not checked.
  7. Returns the session.
- **`list_tools(session)`**: POSTs `tools/list` with `params.server_id =
  "postgres-mcp"` — only queries that one downstream server's catalog, not the
  full gateway catalog. `timeout=30`. No `raise_for_status`.
- **`call_tool(session, tool_name, arguments)`**: POSTs `tools/call` with
  `timeout=300`. Comment explains 30s was previously too short and silently
  dropped results for slow LLM-backed tools (e.g. `standardize_quote_win` on a
  large file), matching the generous timeout Dify's own HTTP nodes already
  use for the same calls. No `raise_for_status`.

**Configuration usage:**
- `config.MCP_JUNGLE_URL` — the only configuration surface, used as the POST
  target in all three network-calling functions.

**Related files:** Imports `config.py`. Imported by `fastapi_router.py`
(`create_session`, `call_tool`) and `scrub_mcp_server.py` (`call_tool`,
`create_session`) to actually execute skills/tools through the MCP Jungle
gateway.

---

## `manage_backend.py`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum intake\manage_backend.py`

**Purpose:** Master orchestration script — the single entry point to start,
stop, restart, health-check, and continuously monitor all 10 backend services
(7 of which are files in this folder; 3 live in a sibling
`accomplish-ui`/Superset installation) plus 3 external infrastructure
dependencies this platform needs.

**Responsibilities:**
- Define a static inventory (`SERVICES`) of every long-lived process needed:
  host/port, health-check method, and launch mechanism (Python script vs. raw
  `cmd` argv, with optional per-service env overrides and pre-build steps).
- Define a static inventory (`EXTERNAL_DEPENDENCIES`) of infra this script
  doesn't manage but health-checks anyway (Postgres, Ollama, MCP Jungle
  gateway).
- Persist/load process state (PID, start time, log file path, port) to
  `.backend_services_state.json` so `stop`/`status`/`monitor` work correctly
  across separate script invocations.
- Start services: skip if already tracked and alive; warn (not duplicate-start)
  if the port is already occupied by something untracked; run an optional
  synchronous pre-build command; launch via `subprocess.Popen` with
  per-service cwd/env, logging stdout+stderr to a per-service file under
  `service_logs/`.
- Stop services: terminate the tracked PID and all child processes gracefully
  (`terminate()`, wait up to 8s, then `kill()` any stragglers).
- Health-check each service via its declared `health_kind` (`http_2xx` = must
  get a 2xx; `http_any` = any HTTP response at all, even 404, counts as
  "listening") and each external dependency via `tcp`, `http_2xx`, or
  `http_any`.
- Wait-for-health polling after `start` (30s timeout per service).
- Continuous `monitor` mode: reprints status every `--interval` seconds; with
  `--auto-restart`, restarts a service immediately if its process died, or
  after 3 consecutive failed health checks if the process is alive but
  unresponsive.
- CLI subcommand dispatch: `start` / `stop` / `restart` / `status` /
  `monitor`.

**Dependencies:**
- Stdlib: `argparse`, `json`, `os`, `socket`, `subprocess`, `sys`, `time`,
  `urllib.error`, `urllib.request`, `datetime.datetime`, `datetime.timezone`.
- Third-party: `psutil`.
- No local module imports — this script only references other project files
  as **subprocess targets/paths** (launched as separate OS processes via
  `subprocess.Popen`), never as Python imports, so no `sys.path` trick is
  needed.

**Public interfaces:**
- `_now()` — no params; current UTC time as ISO-8601 string with `Z` suffix.
- `load_state()` — reads/parses `.backend_services_state.json`; returns `{}`
  if missing or corrupt.
- `save_state(state)` — writes `state` dict as indented JSON.
- `_tcp_open(host, port, timeout=1.5)` — `bool`, via `socket.create_connection`.
- `_http_get(url, timeout=2.5)` — returns `(reached: bool, status_code:
  int|None, detail: str)`; distinguishes "got any HTTP response" from
  "connection failed."
- `check_dependency(dep)` — `(healthy: bool, detail: str)` for one
  `EXTERNAL_DEPENDENCIES` entry, dispatched by `dep["kind"]`.
- `check_service_health(svc)` — `(healthy: bool, detail: str)` for one
  `SERVICES` entry, dispatched by `svc["health_kind"]`.
- `is_pid_alive(pid)` — `bool` via `psutil.pid_exists` + non-zombie check.
- `start_service(svc, state)` — launches one service if not already
  running/port-occupied; updates and saves `state`.
- `wait_for_health(svc, timeout=30, interval=1.0)` — polls until healthy or
  timeout; returns final `(ok, detail)`.
- `stop_service(name, state)` — terminates the tracked process (and children)
  for a service by name; updates and saves `state`.
- `print_status(state, verbose=True)` — prints a full health report; returns
  `bool` (`all_healthy`).
- `cmd_start(args)` / `cmd_stop(args)` / `cmd_restart(args)` / `cmd_status(args)`
  / `cmd_monitor(args)` — the five CLI subcommand handlers.
- `main()` — builds the `argparse` CLI, dispatches to the matching `cmd_*`.

**Internal execution flow (key functions):**

- **`start_service(svc, state)`**: (1) skip if `state` already has a live PID
  for this service; (2) warn and refuse to start a duplicate if the port is
  already open with no tracked PID; (3) ensure `service_logs/` exists, open/
  append a log file with a timestamped start marker; (4) if `svc` has
  `pre_build_cmd`, run it synchronously via `subprocess.run(...,
  shell=True, ...)` and abort (without starting the main process) on nonzero
  exit; (5) determine `argv` — `svc.get("cmd")` if present, else `[PYTHON,
  svc["script"]]`; (6) merge `svc.get("env")` on top of a **copy** of the
  current `os.environ` (never a wholesale replacement, so PATH/USERPROFILE
  etc. still reach the child); (7) on Windows, use
  `CREATE_NEW_PROCESS_GROUP`; (8) `subprocess.Popen(...)`; (9) record
  `{pid, started_at, log_file, port}` in `state` and save.
- **`stop_service(name, state)`**: look up tracked entry; if PID not alive,
  report "already stopped" and clean up state; otherwise recursively enumerate
  child processes via `psutil`, `terminate()` each child then the parent, wait
  up to 8s, `kill()` anything still alive; always remove from state and save.
- **`print_status(state, verbose=True)`**: for each `SERVICES` entry,
  cross-references tracked-PID liveness against actual health-check result to
  classify as `HEALTHY` / `PROCESS UP, NOT RESPONDING` / `DOWN`; same pattern
  (minus the middle state) for `EXTERNAL_DEPENDENCIES`; accumulates and
  returns overall `all_healthy`.
- **`cmd_monitor(args)`**: loop — reload state fresh each iteration (so it
  sees state written by a separate `start` invocation), print status; if
  `--auto-restart`: dead process → restart immediately and reset failure
  counter; alive-but-unhealthy → increment per-service consecutive-failure
  counter, force `stop_service` + `start_service` once it hits 3; healthy →
  reset counter to 0. Sleeps `args.interval` seconds; exits cleanly on
  `KeyboardInterrupt`.

**Configuration usage:** No `os.environ.get`/`os.getenv` calls for tunable
config — everything is hardcoded in the `SERVICES`/`EXTERNAL_DEPENDENCIES`
lists and module-top path constants:
- `PROJECT_ROOT` — this script's own directory.
- `REPORTING_DIR = PROJECT_ROOT/reporting_module`.
- `ACCOMPLISH_UI_ROOT = r"C:\Users\ADMIN\Downloads\accomplish-ui\accomplish-ui"`
  — a completely separate checkout (the frontend), not part of this project.
- `FRONTEND_DIR`, `FRONTEND_VITE_BIN`, `DAEMON_DIR`, `DESKTOP_DIR` — derived
  from `ACCOMPLISH_UI_ROOT`.
- `STATE_FILE = PROJECT_ROOT/.backend_services_state.json`.
- `LOG_DIR = PROJECT_ROOT/service_logs`.
- `PYTHON = sys.executable`.
- Per-service `env` overrides (hardcoded, not read from this process's own
  environment): `superset` sets `SUPERSET_CONFIG_PATH =
  r"C:\Superset\superset_config.py"`; `daemon` sets `ACCOMPLISH_DAEMON_DEV=1`
  and `ACCOMPLISH_APP_PATH=<desktop dir>`.
- Does not import/use `config.py` or `db.py`.

**The 10 managed services:**

| # | Service name | Launch mechanism | Host:Port | Health check |
|---|---|---|---|---|
| 1 | `upload_server` | `[PYTHON, upload_server.py]`, cwd=project root | `127.0.0.1:3000` | `http_2xx` on `GET /docs` |
| 2 | `fastapi_router` | `[PYTHON, fastapi_router.py]`, cwd=project root | `127.0.0.1:5000` | `http_2xx` on `GET /docs` |
| 3 | `hitl_router` | `[PYTHON, hitl_router.py]`, cwd=project root | `127.0.0.1:5002` | `http_2xx` on `GET /docs` |
| 4 | `scrub_mcp_server` | `[PYTHON, scrub_mcp_server.py]`, cwd=project root | `192.168.1.27:8004` | `http_any` on `GET /` (FastMCP streamable-HTTP has no health page; any response proves the process is bound and serving) |
| 5 | `reporting_mcp_server` | `[PYTHON, reporting_module/mcp_server.py]`, cwd=`reporting_module/` (out of scope) | `192.168.1.27:8005` | `http_any` on `GET /` |
| 6 | `bom_qa_lookup_server` | `[PYTHON, bom_qa_lookup_server.py]`, cwd=project root | `192.168.1.27:8006` | `http_2xx` on `GET /` |
| 7 | `python_bridge` (script is `duck_db_api.py`) | `[PYTHON, duck_db_api.py]`, cwd=project root | `192.168.1.27:3010` | `http_2xx` on `GET /docs` |
| 8 | `web_frontend` | `cmd=[vite.CMD]` (invoked directly, not via `pnpm dev`), cwd = external `accomplish-ui/apps/web` | `192.168.1.27:5180` | `http_2xx` on `GET /` |
| 9 | `superset` | `cmd=[superset.exe run -h 0.0.0.0 -p 8088 ...]`, cwd=`C:\Superset`, env `SUPERSET_CONFIG_PATH` set explicitly | `127.0.0.1:8088` | `http_2xx` on `GET /health` |
| 10 | `daemon` | pre-build `pnpm run build`, then `cmd=[node, dist/index.js]`, cwd = external `accomplish-ui/apps/daemon` | `localhost:9234` | `http_2xx` on `GET /health` |

Services 8–10 are **not** files in this project: `web_frontend`/`daemon` live
in a separate checkout (`accomplish-ui`), and `superset` is a separately
installed venv console app. Only services 1–7 are Python files documented in
this reference.

Plus 3 externally-managed dependencies (health-checked, not started):
`postgres (logic_db/file_metadata_db)` (`tcp` on `localhost:5432`), `ollama`
(`http_2xx` on `http://localhost:11434/api/tags`), `mcp_jungle_gateway`
(`http_any` on `http://localhost:8080/`).

**Related files:** Launches, as subprocess targets: `upload_server.py`,
`fastapi_router.py`, `hitl_router.py`, `scrub_mcp_server.py`,
`bom_qa_lookup_server.py`, `duck_db_api.py`, plus `reporting_module/mcp_server.py`
(out of scope). Reads/writes `.backend_services_state.json`. Writes to
`service_logs/`.

---

## `.backend_services_state.json`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum intake\.backend_services_state.json`

**Purpose:** Runtime state cache (not source code) persisted by
`manage_backend.py`, recording the last-known launch state of each managed
process so a separate `status`/`stop`/`monitor` invocation can act on state a
different `start` invocation created.

**Structure:** A flat JSON object keyed by service name (matching
`SERVICES[i]["name"]`). Each value has:
- `pid` (int) — OS process ID.
- `started_at` (str) — ISO-8601 UTC timestamp with `Z` suffix.
- `log_file` (str) — absolute path to the service's log under `service_logs/`.
- `port` (int) — the port the service was launched on.

At last inspection it held entries for all 9 process-tracked services (all of
`SERVICES` except nothing — `web_frontend`, `superset`, and `daemon` are
tracked the same way as the 7 in-project Python services, since they too are
launched via `subprocess.Popen`).

**Related files:** Written by `save_state()`, read by `load_state()` — both in
`manage_backend.py`. No other file touches it.

---

## `fastapi_router.py`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum intake\fastapi_router.py`

**Purpose:** The central DMR ("Dify Managed Router") bridge — port 5000. This
is the HTTP surface an external Dify workflow drives in a step-by-step tool
execution loop: on each step, Dify asks this service which tool runs next
(indirectly, via a separate routing-sequence lookup) and then asks this
service to execute a named tool with arguments, which this service forwards to
the MCP Jungle gateway and interprets the result to decide whether/how to
advance the RFQ's workflow state in Postgres.

**Responsibilities:**
- Expose the "what should run next" data (routing sequence + current stage)
  for a given RFQ and profile.
- Execute a named MCP tool with given arguments via the MCP Jungle gateway,
  gating execution against the live routing profile (skip disabled tools),
  resolving the RFQ's active version and rewriting arguments for
  version-scoped tools, and interpreting the tool's JSON response to decide
  whether to advance `rfq_process_stage`, set/clear `hitl_required`, and
  notify the frontend of skill progress.
- Emit best-effort skill-progress notifications to a separate
  `accomplish-ui` daemon endpoint (`http://192.168.1.27:9234/api/internal/
  emit-skill-progress`) for "running"/"completed"/"failed" step states.
- Maintain a single lazily-created, process-global MCP session
  (`get_mcp_session()`), reconnecting on demand if `None`.

**Dependencies:**
- Stdlib: `json`, `ast`, `datetime.datetime`.
- Third-party: `fastapi` (`FastAPI`, `HTTPException`), `fastapi.responses.
  JSONResponse`, `uvicorn`, `pydantic.BaseModel`, `typing.Dict/Any/Optional`,
  `httpx`.
- Local: `tool_calling` (`create_session`, `call_tool`), `db`
  (`increment_skill_index`, `get_skill_by_code`, `get_active_version`,
  `versioned_key`, `set_hitl_required`, and `get_routing_sequence` aliased to
  `get_live_routing_sequence` — this module defines its own function also
  named `get_routing_sequence`, hence the alias). No `sys.path` manipulation
  (does not touch `reporting_module`).

**Public interfaces:**
- `ToolExecuteRequest(BaseModel)` — request schema for `/tool/execute`:
  `rfq_id: Optional[Any] = None`, `tool_name: str`, `arguments: Dict[str, Any]`.
- `notify_skill_progress(rfq_id, skill_code, skill_name, macro_category,
  macro_category_name, step_status, error=None)` — POSTs a skill-progress
  payload to the accomplish-ui daemon's internal SSE-emit endpoint, 5s
  timeout, no error handling at the call site (callers wrap it in try/except).
- `_notify_execute_failure(rfq_id, tool_name, error_message)` — best-effort
  wrapper that looks up skill metadata by tool name and calls
  `notify_skill_progress` with `step_status="failed"`; any lookup/notify
  failure here is swallowed (printed only), since it must never mask the real
  error being returned to the caller.
- `get_mcp_session()` — returns the process-global `mcp_session`, creating it
  via `create_session()` on first use (or after a `None` reset); raises
  `HTTPException(503)` on connection failure.
- `get_routing_sequence(rfq_id: str, profile_name: str)` — see endpoint table
  below.
- `execute_tool(request: ToolExecuteRequest)` — see endpoint table below.

**HTTP endpoints:**

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/pipeline/routing-sequence/{rfq_id}/{profile_name}` | Returns `{routing_sequence, skill_index}` for an RFQ + profile by querying `logic_db.quote_routing_profiles` and `file_metadata_db.rfq_process_tracking` **directly through the MCP Jungle gateway** (via `postgres_logic__execute_sql` / `postgres_metadata__execute_sql` tools, not through `db.py`'s own Postgres connections) — used by Dify at the start of/during a run to know what the routing sequence is and where the RFQ currently stands. |
| `POST` | `/tool/execute` | Executes one MCP tool by name/arguments for an RFQ: applies the routing-profile skip gate, resolves/rewrites the RFQ's active version into the arguments, calls the tool via `tool_calling.call_tool`, interprets the JSON result (`hitl`/`status` fields) to advance or hold `rfq_process_stage`, and emits progress notifications throughout. This is the core loop endpoint Dify calls once per skill. |
| (implicit) | `GET /docs` | FastAPI's auto-generated Swagger UI — used by `manage_backend.py` as this service's health-check path. |

**Internal execution flow:**

- **`get_routing_sequence(rfq_id, profile_name)`** (the endpoint, not
  `db.py`'s function of the same name): (1) opens a **new** MCP session
  (`create_session()`, not the shared `get_mcp_session()`); (2) best-effort
  "wakes up" the Postgres MCP server via a `resources/list` call (failure is
  swallowed); (3) calls `postgres_logic__execute_sql` with a raw
  string-interpolated `SELECT routing_sequence FROM quote_routing_profiles
  WHERE profile_name = '{profile_name}'` (⚠ not parameterized — `profile_name`
  is not sanitized before interpolation); (4) surfaces the JSON-RPC error
  explicitly if `"result"` is absent (rather than an opaque `KeyError`); (5)
  parses the returned text via `ast.literal_eval`; (6) repeats the same
  pattern for `rfq_process_stage` from `postgres_metadata__execute_sql`
  against `rfq_process_tracking`; (7) returns `{routing_sequence,
  skill_index}`, or an `{"error": ...}` dict (HTTP 200, not a raised
  exception) if the profile/RFQ isn't found or any step fails.
- **`execute_tool(request)`** (the `/tool/execute` handler) — the most
  important function in the whole codebase:
  1. Resolves `effective_rfq_id` from either `request.rfq_id` or
     `request.arguments["rfq_id"]` (fallback `"UNKNOWN_RFQ"`).
  2. **Routing gate**: fetches the live routing sequence via
     `get_live_routing_sequence("Standard_BOM_Flow")` — a fresh, uncached
     lookup every call, since a Skills Settings toggle must take effect
     immediately. On lookup failure, **fails open** (treats the tool as
     enabled) rather than silently stalling every RFQ. If the tool is not in
     the live sequence: looks up skill metadata (best-effort), increments
     `rfq_process_stage` anyway, clears `hitl_required`, sends a "completed"
     progress notification, and returns `{"skipped": True, "hitl": 0,
     "tool_name": ...}` immediately — the disabled skill is transparently
     skipped, not executed.
  3. **Version resolution**: resolves `get_active_version(effective_rfq_id)`;
     for tools in `DUCKDB_SCOPED_TOOLS` (the 6 `reporting_module` MCP tools:
     `centum_reporting__cbom`, `__enrich_erp`, `__enrich_costing_sheet`,
     `__resolve_final_selection`, `__generate_reports`, `__export_reports`),
     rewrites `arguments["rfq_id"]` to the versioned key; for tools in
     `SCRUB_TOOLS` (the 4 `scrub_mcp_server.py` intake tools:
     `centum_intake__standardize_scrub_bom`, `__standardize_quote_win`,
     `__standardize_erp`, `__standardize_costing_sheet`), leaves `rfq_id` bare
     but adds an explicit `arguments["version"]`. On any failure here, again
     **fails open** — falls through with arguments untouched (bare rfq_id),
     matching pre-versioning behavior.
  4. Obtains the shared MCP session via `get_mcp_session()`.
  5. Sends a "running" progress notification **before** calling the tool
     (best-effort; a failure here must not block the actual call) — without
     this, a slow LLM-backed tool call would look silent/stuck to the
     frontend.
  6. Calls `tool_calling.call_tool(...)`, extracts
     `mcp_envelope["result"]["content"][0]["text"]`, parses it as JSON
     (`clean_json_body`).
  7. Reads `hitl_flag = bool(clean_json_body.get("hitl"))` and `tool_failed =
     clean_json_body.get("status") == "failed"`. If neither is set (a clean,
     non-hitl success or a "skipped" result): clears `hitl_required`, looks up
     the completed skill, calls `increment_skill_index`, sends a "completed"
     notification. If `hitl_flag` is set: sets `hitl_required=True`, logs
     "awaiting human review," does **not** advance the stage. If
     `tool_failed` (and not `hitl_flag`): also sets `hitl_required=True` (so
     the checkpoint is recorded), does **not** advance the stage, and sends a
     `_notify_execute_failure` — this is a documented bug fix: previously a
     tool reporting `status="failed"` had no `hitl` key either, so
     `hitl_flag` alone was `False`, silently advancing the stage past a real
     failure.
  8. Returns the original `clean_json_body` as the HTTP response body
     (status 200) in the success/hitl/failed-but-handled cases. Any exception
     during JSON extraction or the outer tool call returns HTTP 500 with
     `{"hitl": 1, "error": ...}` — this convention (`hitl: 1` on error) is
     deliberate: something needs human attention before the RFQ can proceed,
     and previously an uncaught exception fell through with an empty body
     that Dify couldn't distinguish from a real result.

**Configuration usage:**
- `MCP_JUNGLE_URL` — hardcoded module-level string
  `"http://localhost:8080/mcp"` (does **not** import `config.py`'s version —
  see the drift note under `config.py` above).
- Hardcoded external URL: `http://192.168.1.27:9234/api/internal/
  emit-skill-progress` (the accomplish-ui daemon's internal SSE-emit
  endpoint).
- Reads no other env vars directly; relies on `db.py`'s env vars transitively.

**Related files:** Imports `tool_calling.py` and `db.py`. Called by the
external Dify workflow. Calls out to the accomplish-ui daemon (external
project) for progress notifications. Its `/tool/execute` endpoint is the
trigger point for all four `scrub_mcp_server.py` tools and all six
`reporting_module` MCP tools (out of scope).

---

## `hitl_router.py`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum intake\hitl_router.py`

**Purpose:** Human-in-the-loop (HITL) review API — port 5002 — specifically
for the `resolve_final_selection` gate: when a BOM item has multiple candidate
price/source values (from ERP, Costing Sheet, and QuoteWin) that disagree, a
human reviewer must pick which source wins before the pipeline can continue.
This router exposes the pending-conflicts list, a summary, and the resolution
submission endpoint, and is responsible for resuming the RFQ's Postgres
workflow state once every conflict is resolved.

**Responsibilities:**
- Read/write `logic_db.final_selection_conflicts` (workflow/review state — not
  analytical CBOM data).
- Apply a reviewer's chosen resolution into `cbom.duckdb`'s `final_*` columns
  and recompute derived columns, reusing `reporting_module`'s own
  `database.connect()`/`final_selection` functions rather than duplicating
  that DuckDB access/aliasing logic.
- Advance `rfq_process_stage` **past** the `resolve_final_selection` skill's
  own position once all conflicts for an RFQ are resolved, so a later `GET
  /api/dify/start/{rfq_id}` (in `upload_server.py`) can resume the Dify run.
- Resolve the active-version-scoped DuckDB key for every operation, since
  `final_selection_conflicts` (Postgres) is `cbom_item_id`-scoped to one
  specific version's `cbom.duckdb` rows.

**Dependencies:**
- Stdlib: `os`, `sys`, `typing.List/Optional`.
- Third-party: `fastapi` (`FastAPI`, `HTTPException`),
  `fastapi.middleware.cors.CORSMiddleware`, `pydantic.BaseModel`.
- Local: `db` (`get_logic_connection`, `increment_skill_index`,
  `advance_skill_index_to_at_least`, `get_active_version`, `versioned_key`,
  `get_routing_sequence`).
- **`sys.path.insert` trick**: at module top,
  ```python
  _THIS_DIR = os.path.dirname(os.path.abspath(__file__))
  _REPORTING_DIR = os.path.join(_THIS_DIR, "reporting_module")
  for _dir in (_THIS_DIR, _REPORTING_DIR):
      if _dir not in sys.path:
          sys.path.insert(0, _dir)
  ```
  This is the documented coupling pattern used across this codebase to import
  from the sibling `reporting_module` package as if it were a top-level
  module. After this, the file does `import database as reporting_database`
  and `import final_selection` — both resolved from `reporting_module/`, not
  from any installed package. `reporting_module.database.connect()` is used
  deliberately instead of a bare `duckdb.connect()` because it sets up the
  `cbom_db`/`input_db` `ATTACH` aliases that `final_selection.py`'s SQL (e.g.
  `cbom_db.cbom`) expects.

**Public interfaces:**
- `_advance_past_resolve_final_selection(rfq_id: str) -> int` — looks up
  `resolve_final_selection`'s index in the live `Standard_BOM_Flow` routing
  sequence, calls `advance_skill_index_to_at_least(rfq_id, that_index + 1)`;
  falls back to a blind `increment_skill_index` if the routing sequence can't
  be resolved (fail-open — a human already approved, so an unrelated lookup
  failure must not re-block them).
- `_resolve_cbom_key(rfq_id: str) -> str` — returns `versioned_key(rfq_id,
  get_active_version(rfq_id))`, falling back to the bare `rfq_id` on any
  error (fail-open for RFQs predating the versioning feature).
- `ResolutionItem(BaseModel)` — `conflict_id: str`, `resolved_source: str`
  (`'costing' | 'erp' | 'qw'`), `resolved_by: str`.
- `ResolveBatchRequest(BaseModel)` — `resolutions: List[ResolutionItem]`.
- `get_pending_conflicts(rfq_id, cursor=None, limit=100)` — see endpoint
  table.
- `get_summary(rfq_id)` — see endpoint table.
- `submit_resolutions(rfq_id, request: ResolveBatchRequest)` — see endpoint
  table.

**HTTP endpoints:**

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/rfq/{rfq_id}/final-selection/pending` | Keyset/cursor-paginated list of unresolved `final_selection_conflicts` rows for an RFQ (never OFFSET-based — an RFQ can have thousands of conflicts). Params: `cursor` (last item's `conflict_id`), `limit` (default 100, clamped 1–500). |
| `GET` | `/api/rfq/{rfq_id}/final-selection/summary` | Lightweight `{total, resolved, remaining}` counts only — safe to poll for a progress UI. |
| `POST` | `/api/rfq/{rfq_id}/final-selection` | Batch/incremental resolution submission. Accepts a subset of pending conflicts at a time (repeatable, not all-or-nothing). Updates Postgres, applies resolved values into `cbom.duckdb`, and — only once every conflict for the RFQ is resolved — calls `_advance_past_resolve_final_selection` to resume the pipeline. |
| (implicit) | `GET /docs` | FastAPI Swagger UI — `manage_backend.py`'s health-check path. |

**Internal execution flow:**

- **`get_pending_conflicts`**: resolves the version-scoped `cbom_key`; runs
  one of two parameterized SQL queries against `logic_db` depending on
  whether `cursor` is supplied (keyset predicate `(fg, cpn,
  cbom_item_id) > (?, ?, ?)` vs. no predicate), both `ORDER BY conflict_id`
  (actually `fg, cpn, cbom_item_id` per the SQL — note the endpoint's
  `next_cursor` is keyed on `conflict_id` while the sort key visible in the
  query is `fg, cpn, cbom_item_id`); returns items plus a `next_cursor` if a
  full page was returned.
- **`submit_resolutions`**: 
  1. Resolves `cbom_key`.
  2. **Empty-resolutions branch**: if `request.resolutions` is empty, this is
     only accepted as a no-op "confirm" if there are genuinely zero
     unresolved conflicts remaining (e.g. only one pricing source was ever
     uploaded, so `resolve_final_selection` halted with nothing to
     reconcile) — otherwise raises `HTTPException(400)`. If accepted, calls
     `_advance_past_resolve_final_selection` and returns
     `fully_approved=True`.
  3. **Normal branch**: for each `ResolutionItem`, runs an `UPDATE
     final_selection_conflicts SET resolved_source=..., resolved_by=...,
     resolved_at=now() WHERE conflict_id=... AND rfq_id=... AND
     resolved_source IS NULL RETURNING cbom_item_id, available_sources` — a
     `None` result (already resolved, e.g. a retried request, or a
     mismatched rfq_id) is silently skipped, not an error. Validates that
     `item.resolved_source` is actually one of the row's
     `available_sources`, raising `HTTPException(400)` otherwise. After the
     loop, counts remaining unresolved conflicts and commits.
  4. If any rows were resolved, opens a DuckDB connection via
     `reporting_database.connect()`, wraps the whole batch in
     `BEGIN TRANSACTION` / per-row `final_selection.apply_resolved_conflict(...)`
     / `final_selection.recompute_derived_columns(...)` / `COMMIT`, with a
     `ROLLBACK` + close on any exception (re-raised).
  5. If `remaining == 0`, calls `_advance_past_resolve_final_selection` and
     sets `fully_approved=True`; otherwise logs "not advancing" and leaves it
     `False`.
  6. Returns `{status, rfq_id, resolved_count, remaining, fully_approved}`.

**Configuration usage:** No direct env vars beyond what `db.py` reads
transitively. CORS is wide open (`allow_origins=["*"]`,
`allow_credentials=True`, all methods/headers).

**Known open item (per the file's own module docstring):**
`unified_quote_package.approved_by` (in `logic_db`) was originally planned as
a lightweight sign-off marker once every conflict for an rfq_id is resolved,
but is **not wired up** — `unified_quote_package.rfq_id` and
`rfq_master.rfq_id` are both UUID-typed and keyed off `rfq_master.rfq_number`,
while no `rfq_master` row exists for the VARCHAR-style rfq_id scheme (e.g.
`"CE-005570"`) used everywhere else in this pipeline. Writing to
`unified_quote_package` would fail (invalid UUID) or require an unreconciled
mapping. The functionally critical behavior (advancing `rfq_process_stage`)
does not depend on this and works correctly. Flagged in-code as "revisit once
the rfq_id ↔ rfq_master relationship is clarified."

**Related files:** Imports `db.py`. Couples into `reporting_module/database.py`
and `reporting_module/final_selection.py` via the `sys.path.insert` trick
(out of scope, documented separately). Its resolution-advance logic is the
counterpart to `fastapi_router.py`'s HITL-hold logic (a tool's `hitl=1`
response there is what this router's confirm endpoint eventually clears).
Called (indirectly, via a resumed Dify run) after `upload_server.py`'s
`GET /api/dify/start/{rfq_id}`.

---

## `upload_server.py`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum intake\upload_server.py`

**Purpose:** The customer/UI-facing file intake API — port 3000. This is
where BOM, QuoteWin, and Costing Sheet files are actually uploaded from the
React canvas frontend, staged to disk, recorded in Postgres telemetry, and
used to trigger (or resume) the external Dify workflow run.

**Responsibilities:**
- Accept multipart file uploads for BOM (new-version-creating), QuoteWin, and
  Costing Sheet (both version-following, i.e. tagged to whatever version is
  currently active).
- Persist uploaded files to `staged/inbox/` on disk with a randomized,
  role-tagged filename.
- Maintain `rfq_file_telemetry` rows (one active row per `(rfq_id, version,
  file_role)`, deactivating any prior active row for the same role before
  inserting a new one).
- Maintain `rfq_process_tracking` rows: a new BOM upload to an rfq_id with no
  active version creates version 1; a BOM upload to an rfq_id that already has
  an active version creates a new, isolated version (deactivating the old one)
  rather than overwriting it.
- Trigger the external Dify workflow (`POST {DIFY_BASE_URL}/workflows/run`)
  both on initial BOM upload and via an explicit "start/resume" endpoint,
  logging the outcome into `rfq_file_telemetry.execution_logs` (a JSONB
  column, appended to via `||`).

**Dependencies:**
- Stdlib: `os`, `random`, `json`, `typing.Optional`.
- Third-party: `requests`, `fastapi` (`FastAPI`, `UploadFile`, `File`, `Form`,
  `HTTPException`), `fastapi.middleware.cors.CORSMiddleware`, `psycopg2`.
- Local: `db` (module-level import, used as `db.ensure_version_schema()`,
  `db.get_active_version(...)`). No `sys.path` manipulation.

**Public interfaces:**
- `get_db_connection()` — returns a fresh `psycopg2.connect(DB_CONFIG)`
  connection. Note: this is a **separate, independent** connection path from
  `db.py`'s `get_metadata_connection()` — same target database, same
  hardcoded credentials, but not the same code path (this file does not call
  `db.get_metadata_connection`).
- `trigger_dify_workflow_internal(rfq_id: str)` — POSTs to Dify's
  `/workflows/run`, logs the outcome to `rfq_file_telemetry.execution_logs`;
  returns `(dify_status, dify_response_summary)`.
- `process_file_upload(rfq_id, file_obj, file_label, version) -> str` (async)
  — validates extension, writes the file to `staged/inbox/`, deactivates any
  prior active telemetry row for `(rfq_id, file_label)`, inserts a new active
  `rfq_file_telemetry` row; returns the saved file path.
- `start_dify_workflow(rfq_id)` — see endpoint table.
- `upload_rfq_file(bom_file, rfq_id)` — see endpoint table.
- `upload_quotewin_file(quotewin_file, rfq_id)` — see endpoint table.
- `upload_costing_sheet_file(costing_sheet_file, rfq_id)` — see endpoint
  table.

**HTTP endpoints:**

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/dify/start/{rfq_id}` | Manually/externally triggers (or resumes) the Dify workflow run for a given RFQ ID. Used by the frontend's upload-modal flow to resume a paused pipeline once follow-up uploads (QuoteWin/Costing Sheet) succeed. |
| `POST` | `/api/rfq/upload` | Initial BOM upload. Ensures the versioned schema exists (`db.ensure_version_schema()`), determines whether this is a brand-new RFQ (version 1) or a re-upload creating a new version (deactivates the prior active version first), inserts the new `rfq_process_tracking` row at stage 0 ("STAGED_INTAKE"), stages the file, then triggers the Dify workflow. |
| `POST` | `/api/rfq/upload/quotewin` | Follow-up QuoteWin upload for an RFQ already in progress. Always resolves and tags the file with whichever version is **currently active** — never mints a new version. |
| `POST` | `/api/rfq/upload/costing_sheet` | Follow-up Costing Sheet upload. Same version-following behavior as QuoteWin. Docstring notes this endpoint **replaces** an earlier ERP upload endpoint — ERP has no upload path in the current product (its MCP tool/schema/routing remain in the codebase, unused, for future reintroduction), and Costing Sheet took its place as the optional third input. |
| (implicit) | `GET /docs` | FastAPI Swagger UI — health-check path. |

**Internal execution flow:**

- **`process_file_upload`**: (1) derives a safe filename/extension, rejects
  unsupported extensions with `HTTPException(415)`; (2) builds a randomized
  `{6-digit}_{file_label}_{original_name}` filename under `staged/inbox/`; (3)
  writes the uploaded bytes to disk; (4) **first** runs `UPDATE
  rfq_file_telemetry SET is_active = FALSE WHERE rfq_id=... AND
  file_role=...` (deactivating any prior row for this exact role — this fixes
  a documented bug: previously a re-uploaded file of the same role never
  stopped being "active" alongside the new one, leaving
  `scrub_mcp_server.py`'s `_fetch_file_path()` non-deterministic against
  real data that already had 2–3 duplicate rows for several rfq_ids); (5)
  inserts the new row with `is_active=TRUE`; (6) commits.
- **`upload_rfq_file`** (`POST /api/rfq/upload`): (1) validates `rfq_id`; (2)
  calls `db.ensure_version_schema()` (idempotent, safe on every call); (3)
  checks whether an active version already exists for this rfq_id; (4) if
  not, `new_version = 1`; if so, computes `MAX(version) + 1` and deactivates
  the old active row first; (5) inserts the new `rfq_process_tracking` row at
  `rfq_process_stage=0`, `hitl_required=False`, `triggered_by="UI_CANVAS_PORT_3000"`;
  (6) stages the BOM file tagged with the new version; (7) triggers the Dify
  workflow; (8) returns success payload including the new version number. On
  any exception, rolls back the connection and raises `HTTPException(500)`.
- **`trigger_dify_workflow_internal`**: POSTs `{"inputs": {"rfq_id": rfq_id},
  "response_mode": "streaming", "user": f"system-user-{rfq_id}"}` to Dify with
  a `(10, 120)`-second (connect, read) timeout; classifies the outcome into
  `TRIGGERED`/`TRIGGER_FAILED`/`CONNECTION_REFUSED`; appends a JSON summary to
  `rfq_file_telemetry.execution_logs` via a JSONB `||` concat, scoped to
  `file_role='BOM' AND is_active=TRUE` — logging failures here are caught and
  printed, never propagated (a logging failure must not fail the upload/
  trigger itself).

**Configuration usage:**
- `DIFY_BASE_URL` — env var, required, no fallback.
- `DIFY_API_KEY` — env var, required, no fallback (⚠ **security concern,
  resolved**: this used to default to a live-looking Dify API key committed
  directly in source; the fallback has been removed).
- `UPLOAD_DIR` — `os.path.join(os.getcwd(), "staged", "inbox")`, created if
  missing.
- `DB_CONFIG` — now `db.FILE_METADATA_DB_URL` (imported from `db.py`, which
  itself requires `FILE_METADATA_DB_URL` to be set) rather than a separate
  hardcoded literal.
- `ALLOWED_FILE_TYPES` — a fixed set of ~18 extensions (csv, xls/xlsx, EDI
  X12-ish codes `274x`/`274-d`/`x2`/`x3`, pdf, zip, eml, image formats, CAD
  formats `stp`/`step`/`dwg`/`dxf`).
- CORS wide open (`allow_origins=["*"]`).

**Related files:** Imports `db.py` (for `ensure_version_schema`,
`get_active_version`) but maintains its **own independent** psycopg2
connection function (`get_db_connection`) rather than reusing `db.py`'s
context managers. Its uploads are what `scrub_mcp_server.py`'s
`_fetch_file_path()` (via `rfq_file_telemetry`) later reads to locate files
for standardization. Its `/api/dify/start/{rfq_id}` is the resume trigger
referenced in `db.py`'s `set_hitl_required`/`get_hitl_state` docstrings and in
`hitl_router.py`'s comments.

---

## `duck_db_api.py`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum intake\duck_db_api.py`

**Purpose:** The frontend's "Python Bridge" — port 3010 (service name
`python_bridge` in `manage_backend.py`) — serving the costed BOM ("CBOM")
preview grid: paginated read, inline-edit save, and Excel export downloads.
Wraps `reporting_module`'s own DuckDB connection/aliasing and derived-column
recomputation functions directly rather than duplicating that logic.

**Responsibilities:**
- Serve a paginated, keyset-cursor preview of `cbom_db.cbom` rows for a given
  `(rfq_id, volume_no)`.
- Apply inline cell edits (a fixed allow-list of `final_*` fields) to
  `cbom_db.cbom` and recompute derived columns afterward.
- Locate and serve the most recently generated CBOM export workbook, both as
  metadata and as a downloadable file.
- Serve a CBOM-only stripped-down variant of the same export (removing every
  sheet but "CBOM") for the "Finalize Price" wizard stage, entirely in memory.

**Dependencies:**
- Stdlib: `os`, `sys`, `glob`, `io`, `datetime.datetime`.
- Third-party: `fastapi` (`FastAPI`, `HTTPException`, `Query`),
  `fastapi.responses.FileResponse/StreamingResponse`, `duckdb`, `openpyxl`,
  `typing.Any/Optional`, `fastapi.middleware.cors.CORSMiddleware`.
- Local: `db` (`get_active_version`, `versioned_key`).
- **`sys.path.insert` trick** (identical pattern to `hitl_router.py`):
  ```python
  _CENTUM_INTAKE_DIR = os.path.dirname(os.path.abspath(__file__))
  _REPORTING_MODULE_DIR = os.path.join(_CENTUM_INTAKE_DIR, "reporting_module")
  for _dir in (_CENTUM_INTAKE_DIR, _REPORTING_MODULE_DIR):
      if _dir not in sys.path:
          sys.path.insert(0, _dir)
  ```
  Followed by `import database as reporting_database`, `import
  final_selection`, `import config as reporting_config`, `import helpers as
  reporting_helpers` — all four resolved from the sibling `reporting_module`
  package (out of scope, documented separately). `reporting_database.connect()`
  is reused for the same reason as in `hitl_router.py`: it sets up the
  `cbom_db`/`input_db` `ATTACH` aliases that raw SQL against `cbom_db.cbom`
  requires.

**Public interfaces:**
- `_resolve_cbom_key(rfq_id: str) -> str` — identical pattern to
  `hitl_router.py`'s function of the same name: `versioned_key(rfq_id,
  get_active_version(rfq_id))`, falling back to the bare `rfq_id` on error.
- `EDITABLE_FIELDS` (module constant) — the 9 `final_*` columns a reviewer may
  edit: `final_mfg_name`, `final_unit_of_measure`, `final_price_conv`,
  `final_price_original`, `final_currency_original`, `final_supp_name`,
  `final_pkg_qty`, `final_moq`, `final_lead_time`.
- `PREVIEW_COLUMNS` (module constant) — the 20 columns returned by the preview
  endpoint (identifiers, descriptive fields, all `final_*` fields, and
  computed flags like `is_costed`/`abc_classification`/`price_control`).
- `get_preview_data(rfq_id, volume_no=None, cursor_fg=None, cursor_cpn=None,
  cursor_id=None, limit=200)` — see endpoint table.
- `batch_update_bom(rfq_id, updates: list[dict])` — see endpoint table.
- `_find_latest_export(cbom_key: str) -> Optional[str]` — globs
  `reporting_config.EXPORTS_DIR` for `CBOM_Report_{slugify(cbom_key)}_*.xlsx`
  (reusing `reporting_module`'s own `slugify()` so the pattern matches exactly
  how `exporter.py` names files), returns the most recently modified match.
- `get_latest_export(rfq_id)` — see endpoint table.
- `download_latest_export(rfq_id)` — see endpoint table.
- `download_cbom_only_export(rfq_id)` — see endpoint table.

**HTTP endpoints:**

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/bom/preview/{rfq_id}` | FG-wise (`ORDER BY fg, cpn, cbom_item_id`), keyset-cursor-paginated preview of `cbom_db.cbom` for one `(rfq_id, volume_no)`. If `volume_no` omitted, defaults to `MIN(volume_no)` for the RFQ. Params: `volume_no`, `cursor_fg`, `cursor_cpn`, `cursor_id`, `limit` (default 200, max 1000). Non-JSON-native values (UUID/date-ish) are stringified before returning. |
| `PUT` | `/api/bom/batch-update/{rfq_id}` | Applies inline cell edits (full row snapshots keyed by `bom_item_id`, restricted to `EDITABLE_FIELDS`) to `cbom_db.cbom` inside a transaction, then calls `final_selection.recompute_derived_columns` (the same function `hitl_router.py` uses) before committing. |
| `GET` | `/api/bom/export/{rfq_id}` | Metadata (`filename`, `generated_at`) for the most recently generated export workbook — lets the frontend show a "Download <filename>" link without guessing the name/timestamp. 404 if none exists. |
| `GET` | `/api/bom/export/{rfq_id}/download` | Streams the full export workbook as a file download (`Content-Disposition: attachment`). |
| `GET` | `/api/bom/export-cbom/{rfq_id}/download` | Strips every sheet except "CBOM" from the already-generated combined workbook (in-memory via `openpyxl`, no temp files) and streams it as `..._CBOM_ONLY.xlsx`. Used by the "Finalize Price" wizard stage. |
| (implicit) | `GET /docs` | FastAPI Swagger UI — health-check path. |

**Internal execution flow:**

- **`get_preview_data`**: resolves `cbom_key`; if `volume_no` is `None`,
  queries `MIN(volume_no)` for the RFQ and defaults to `1` if none found;
  builds one of two SQL variants depending on whether a full 3-part cursor
  (`cursor_fg`, `cursor_cpn`, `cursor_id`) was supplied, using the tuple
  comparison `(fg, cpn, CAST(cbom_item_id AS VARCHAR)) > (?, ?, ?)` for
  cursor-based pagination (chosen because the sort key is the composite `(fg,
  cpn)`, not `cbom_item_id` alone); executes, converts rows to dicts, stringifies
  non-JSON-native values, computes `next_cursor` from the last row if a full
  page was returned.
- **`batch_update_bom`**: opens a DuckDB transaction; for each update row,
  builds a dynamic `SET` clause from only the fields present in
  `EDITABLE_FIELDS ∩ row.keys()`, applies a `WHERE bom_item_id=? AND
  rfq_id=?` (optionally `AND volume_no=?` if given); after all rows, calls
  `final_selection.recompute_derived_columns(con, cbom_key)` once; commits or
  rolls back the whole batch atomically on any error.
- **`download_cbom_only_export`**: loads the latest export workbook via
  `openpyxl.load_workbook`, deletes every sheet except `"CBOM"` in place,
  writes to an in-memory `io.BytesIO()` buffer, streams it back — no
  filesystem writes for the stripped copy.

**Configuration usage:**
- No direct `os.getenv` calls in this file; relies on `reporting_config`
  (`EXPORTS_DIR`) and `db.py`'s env vars transitively.
- Binds `0.0.0.0:3010` (not a fixed LAN IP) — comment notes this matches
  every other service in the pipeline, since binding to one specific
  interface address would silently refuse connections on other interfaces
  (e.g. a NetBird virtual adapter) regardless of firewall rules.
- CORS wide open, all methods including `PATCH`/`DELETE`, `expose_headers=["*"]`.

**Related files:** Imports `db.py`. Couples into `reporting_module/database.py`,
`reporting_module/final_selection.py`, `reporting_module/config.py`,
`reporting_module/helpers.py` via the `sys.path.insert` trick (out of scope,
documented separately). Reads export files that `reporting_module`'s
`exporter.py` (triggered via `fastapi_router.py`'s `/tool/execute` →
`centum_reporting__export_reports`) produces.

---

## `bom_qa_lookup_server.py`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum intake\bom_qa_lookup_server.py`

**Purpose:** A scripted, non-LLM Q&A lookup service for the accomplish-ui demo
chatbot — port 8006. Deliberately **not** an MCP server and **not** part of
any LLM/agent tool-calling loop: the accomplish-ui daemon calls `POST /ask`
directly as a plain backend HTTP call *before* a chat message is ever handed
to OpenCode/Ollama, and short-circuits with a scripted answer if the question
matches one of two known literal shapes.

**Responsibilities:**
- Match incoming questions against exactly two known regex-based templates
  ("How many FGs does {rfq_id} contain?" and "What's the final conv price of
  MPN {mfg_part_num}?").
- Answer matched questions via read-only DuckDB queries against
  `reports.duckdb` (with `cbom_db`/`input_db` attached, all **read-only**).
- Report `{"matched": false}` for anything that doesn't match, letting the
  daemon fall through to its normal agent flow unaffected.

**Dependencies:**
- Stdlib only: `json`, `os`, `re`, `sys`, `http.server`
  (`BaseHTTPRequestHandler`, `ThreadingHTTPServer`). Deliberately avoids
  FastAPI/FastMCP/any web framework "to keep this as small and boring as
  possible" — module docstring explains this exists as a separate Python
  process purely because Node's native `duckdb` bindings are blocked by this
  machine's Application Control policy (confirmed against both `duckdb` and
  `@duckdb/node-api` npm packages, both failing `ERR_DLOPEN_FAILED`).
- Third-party: `duckdb`.
- **`sys.path.insert` trick** (same pattern as `hitl_router.py`/
  `duck_db_api.py`): inserts this file's own directory and
  `reporting_module/` onto `sys.path`, then does `import config as
  reporting_config` for `REPORTS_DB_PATH`/`CBOM_DB_PATH`/`INPUT_DB_PATH`.

**Public interfaces:**
- `_open_readonly_connection()` — opens `duckdb.connect(REPORTS_DB_PATH,
  read_only=True)` as the main catalog, then `ATTACH ... AS cbom_db
  (READ_ONLY)` and `ATTACH ... AS input_db (READ_ONLY)` — mirrors
  `reporting_module/database.py`'s alias convention but with every database
  opened strictly read-only (unlike that module's own `connect()`, which
  opens `cbom.duckdb` read-write for the pipeline's own generation steps).
  This matters: using the read-write connect() here would compete for the
  same write lock whenever the pipeline is actively running.
- `_run_query_raw(sql: str) -> dict` — runs a pre-trusted `SELECT`
  (constructed by callers from a regex-constrained ID token, never raw user
  text) and returns `{"rows": [...]}` or `{"error": str, "rows": []}`.
- `_fg_count_for_rfq(rfq_id: str) -> str` — `SELECT COUNT(DISTINCT fg) ...
  WHERE rfq_id = '{rfq_id}'`; returns a natural-language sentence.
- `_mpn_price(mpn: str) -> str` — `SELECT DISTINCT final_price_conv ... WHERE
  mfg_part_number = '{mpn}' AND final_price_conv IS NOT NULL`; handles zero,
  one, or multiple distinct prices found.
- `try_hardcoded_answer(question: str) -> str | None` — tries the FG-count
  regex then the MPN-price regex; returns `None` if neither matches.
- `Handler(BaseHTTPRequestHandler)` — the HTTP handler class:
  - `_send_json(status, payload)` — writes a JSON response with proper
    headers.
  - `do_GET(self)` — `GET /` returns `{"status": "ok"}`; anything else 404s.
  - `do_POST(self)` — `POST /ask` only; parses `{"question": str}` from the
    body, returns `{"matched": false}` or `{"matched": true, "answer": ...}`.
  - `log_message(self, format, *args)` — overridden to prefix log lines with
    `[bom_qa_lookup_server]`.

**HTTP endpoints** (raw `http.server`, not FastAPI — no auto-docs):

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Trivial liveness check, returns `{"status": "ok"}` — this is `manage_backend.py`'s health-check path (`health_kind: http_2xx`). |
| `POST` | `/ask` | Accepts `{"question": "..."}`, returns `{"matched": false}` if no scripted template matches, or `{"matched": true, "answer": "..."}` if one does. 400 on missing/invalid body. |

**Internal execution flow:**
- `try_hardcoded_answer`: strips the question, tries `_FG_COUNT_RE` (`how
  many fgs? does ([\w-]+) contain`, case-insensitive) then `_MPN_PRICE_RE`
  (`final conv price of mpn ([\w-]+)`, case-insensitive); on a match, strips
  trailing punctuation from the captured group and calls the corresponding
  handler function, which opens a fresh read-only connection, runs the query,
  and formats a natural-language sentence from the result (handling
  zero-results and multiple-distinct-values cases explicitly).

**Configuration usage:**
- Reads `reporting_config.REPORTS_DB_PATH` / `CBOM_DB_PATH` / `INPUT_DB_PATH`
  (from `reporting_module/config.py`, out of scope).
- Binds `0.0.0.0:8006` (not a fixed LAN IP — same interface-binding rationale
  as other services in this codebase).

**Related files:** Couples into `reporting_module/config.py` via the
`sys.path.insert` trick. Called by accomplish-ui's daemon
(`apps/daemon/src/task-service.ts`, external project) before any LLM
involvement. Queries the same `cbom_db.cbom` table that `duck_db_api.py` and
`hitl_router.py` also query, but exclusively read-only and via its own
independent connection (does not import `db.py` or `reporting_module/
database.py`'s `connect()`).

---

## `scrub_mcp_server.py`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum intake\scrub_mcp_server.py`

**Purpose:** The MCP tool server (via FastMCP, streamable-HTTP transport) —
port 8004 — exposing the four "standardize" intake tools that
`fastapi_router.py`'s `/tool/execute` calls through the MCP Jungle gateway.
This is the actual execution point for turning an uploaded raw Excel file
(BOM, QuoteWin, ERP, or Costing Sheet) into standardized rows written to
`input_db.duckdb`.

**Responsibilities:**
- Register 4 MCP tools (`standardize_scrub_bom`, `standardize_quote_win`,
  `standardize_erp`, `standardize_costing_sheet`) via FastMCP's `@mcp.tool()`
  decorator.
- For each tool: look up the registered file path for the RFQ's given
  `(version, file_role)` from Postgres (via the MCP Jungle gateway's
  `postgres_metadata__execute_sql` tool, **not** via `db.py`'s own
  connections), run the corresponding `<thing>_processing.py` standardization
  function, then persist via the corresponding `<thing>_to_database.py`
  function.
- Signal the post-`standardize_scrub_bom` HITL checkpoint (`hitl: 1` on fresh
  success) so the pipeline pauses for the frontend to collect QuoteWin/
  Costing Sheet uploads before continuing.
- Validate RFQ ID strings against a strict allow-list regex before SQL
  interpolation.

**Dependencies:**
- Stdlib: `ast`, `json`, `re`, `traceback`.
- Third-party: `fastmcp.FastMCP`.
- Local: `scrub_bom_processing.process_scrub_bom_workbook`,
  `scrub_bom_to_database` (`process_scrub_bom_to_database`,
  `process_volume_to_database`, `process_batch_to_database`),
  `quote_win_processing.process_quote_win`,
  `quote_win_to_database.process_quote_win_to_database`,
  `erp_processing.process_erp`, `erp_to_database.process_erp_to_database`,
  `costing_sheet_processing.process_costing_sheet`,
  `costing_sheet_to_database.process_costing_sheet_to_database`,
  `tool_calling` (`call_tool`, `create_session`), `db.versioned_key`. No
  `sys.path` manipulation (does not touch `reporting_module` — all its
  imports are project-root siblings).

**Public interfaces:**
- `_validate_id(value: str) -> str` — raises `ValueError` unless `value`
  matches `^[A-Za-z0-9_\-]+$`; a defense against SQL-unsafe characters before
  string interpolation into the metadata-lookup SQL.
- `_fetch_file_path(session, rfq_id_str, version, file_role)` — builds and
  executes (via `call_tool`/`postgres_metadata__execute_sql`) a `SELECT
  file_path FROM rfq_file_telemetry WHERE rfq_id=... AND version=... AND
  file_role=... AND is_active=TRUE ORDER BY processed_at DESC LIMIT 1`;
  returns the path or `None` if no row exists. `version` is a required
  parameter (not optional) specifically to prevent a re-upload's new version
  from accidentally resolving to an older version's file.
- `standardize_scrub_bom(rfq_id, version=1) -> str` — MCP tool. See flow
  below.
- `standardize_quote_win(rfq_id, version=1) -> str` — MCP tool. Parallel
  structure to `standardize_scrub_bom` but for the QuoteWin file/table; fails
  (not skips) if no file is found, since QuoteWin is a required input.
- `standardize_erp(rfq_id, version=1) -> str` — MCP tool. ERP currently has no
  upload path in the product (superseded by Costing Sheet in
  `upload_server.py`), so this **always returns `"skipped"`** today; kept
  fully functional for future reintroduction. `version` accepted for
  signature symmetry but unused (ERP isn't in the active
  `system_skills_registry` routing sequence).
- `standardize_costing_sheet(rfq_id, version=1) -> str` — MCP tool. Optional
  input — returns `"skipped"` (not failed) if no file was uploaded.

**Internal execution flow (`standardize_scrub_bom`, the most complex tool):**
1. Validates/normalizes `rfq_id`; computes the versioned DuckDB key via
   `versioned_key(rfq_id_str, version_int)`.
2. Opens an MCP session (`create_session()` — a **new** session per call, not
   shared/cached).
3. Fetches the BOM file path via `_fetch_file_path(..., "BOM")`; returns a
   `{"status": "failed", ...}` JSON string if the lookup errors or no file is
   registered (BOM is always required).
4. Calls `process_scrub_bom_workbook(bom_file)` (from
   `scrub_bom_processing.py`), which reads all three sheets (SCRUB BOM,
   Settings, Batch) and returns a dict of three standardized DataFrames.
5. Persists each DataFrame via `process_scrub_bom_to_database`,
   `process_volume_to_database`, `process_batch_to_database` (from
   `scrub_bom_to_database.py`), keyed by the versioned key.
6. Combines the three per-table results; `overall_status = "success"` only if
   every table reports `"success"`.
7. **HITL gate**: if `overall_status == "success"` **and** not every table
   was already `already_processed` (i.e. this is a fresh, first-time
   success), sets `response["hitl"] = 1` — this deliberately halts
   `fastapi_router.py`'s advancement of `rfq_process_stage` so the frontend
   can collect QuoteWin/Costing Sheet uploads. It is explicitly **not**
   re-asserted on a no-op re-run (all tables already processed), because
   Dify's own workflow unconditionally re-calls this tool on every resume
   trigger regardless of whether it already succeeded, and re-pausing here
   would wrongly stall an already-advancing pipeline back at the start.
8. Returns the JSON-serialized response. Any exception anywhere in the try
   block is caught and returned as `{"status": "failed", "error": ...,
   "traceback": ...}`.

The other three tools (`standardize_quote_win`, `standardize_erp`,
`standardize_costing_sheet`) follow the same fetch → process → persist →
JSON-return shape but without the HITL-gate step (only `standardize_scrub_bom`
sets `hitl`).

**Configuration usage:** No direct env vars in this file; relies on
`tool_calling.py`'s `MCP_JUNGLE_URL` (via `config.py`) and each
`*_to_database.py`'s `DB_PATH` transitively. Binds `0.0.0.0:8004` via
`mcp.run(transport="http", host="0.0.0.0", port=8004)`.

**Related files:** Imports all four `<thing>_processing.py` and
`<thing>_to_database.py` pairs, plus `tool_calling.py` and `db.py`. Is itself
called (as an MCP tool server) via `fastapi_router.py`'s `/tool/execute`
through the MCP Jungle gateway, for tool names in the `SCRUB_TOOLS` set
(`centum_intake__standardize_scrub_bom`, `__standardize_quote_win`,
`__standardize_erp`, `__standardize_costing_sheet`). Reads file paths that
`upload_server.py` writes into `rfq_file_telemetry`.

---

## `scrub_bom_processing.py`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum intake\scrub_bom_processing.py`

**Purpose:** Business logic for standardizing a "SCRUB BOM" workbook (the
customer's raw bill-of-materials export) into a canonical schema — schema
mapping and column standardization only; explicitly **no** volume expansion,
consolidation, or duplicate-CPN detection (out of scope for this module).

**Responsibilities:**
- Use an LLM (via `ollama`) to semantically map incoming column headers to a
  fixed canonical schema (`SCRUB_BOM_TEMPLATE_HEADERS`).
- Force a small set of critical mappings deterministically when the exact
  header text is present, since dry-run testing showed the LLM mapped them
  inconsistently across repeated runs.
- Standardize the `SCRUB BOM` sheet's data types (notably `item_number` as a
  free-form VARCHAR and `ltb_date` as a real DATE).
- Compute a `hierarchy_multiplier` column — the cumulative ancestor
  sub-assembly quantity multiplier for each row — fixing a confirmed
  real-data quantity roll-up bug.
- Standardize the wide-format `Settings` (→ `volume`) and `Batch` (→ `batch`)
  sheets into long-format tables, tolerating either sheet being entirely
  absent from some real-world export templates.

**Dependencies:**
- Stdlib: `json`, `re`.
- Third-party: `ollama`, `pandas`.
- No local module imports (this is a "processing" module with zero project
  coupling — it's a pure function library over `pandas.DataFrame`s and an
  Excel file path).

**Public interfaces:**
- `SHEET_SCRUB_BOM`, `SHEET_SETTINGS`, `SHEET_BATCH` — the three expected
  sheet names (`"SCRUB BOM"`, `"Settings"`, `"Batch"`).
- `SCRUB_BOM_TEMPLATE_HEADERS` — the 21-column canonical schema list.
- `semantic_mapping_scrub(headers) -> dict` — calls
  `ollama.chat(model="qwen2.5-coder:7b", ...)` with a strict system/user
  prompt, parses the JSON response, backfills any schema field the LLM
  omitted with `None`.
- `_coerce_item_number(value)` — normalizes `item_number` representation:
  `NaN`/`None` → `None`; whole-number float → clean integer string (no
  trailing `.0`); anything else → `str(value)` unchanged. Documented fix for
  a real bug where `item_number` was previously `INTEGER`-typed and crashed
  the whole insert on any free-text or oversized-numeric value (confirmed
  real case: RFQ-000015's CPN `5010980138` is a genuine CPN, not a line
  number, and was being incorrectly nulled/rejected).
- `_build_hierarchy_multipliers(df) -> pd.Series` — the core BOM-rollup fix.
  See flow below.
- `_coerce_ltb_date(series) -> pd.Series` — parses `DD-MM-YYYY` first, falls
  back to a general `dayfirst=True` parse for anything unparsed; mirrors
  `quote_win_processing.py`'s date-handling pattern.
- `standardize_scrub_bom(df, mapping) -> pd.DataFrame` — renames columns per
  the mapping (first-match-wins, no double-claiming a source column),
  backfills missing target columns with `None`, reorders to the canonical
  schema, applies `_coerce_item_number`, `_coerce_ltb_date`, and
  `_build_hierarchy_multipliers`.
- `process_scrub_bom(bom_file, sheet_name=0) -> pd.DataFrame` — the "SCRUB
  BOM" sheet's full pipeline: load → strip headers → LLM-map → force-override
  critical fields → validate required fields → standardize → print summary.
- `_VOLUME_QTY_SUFFIX_RE`, `_BATCH_QTY_SUFFIX_RE` — regexes stripping a
  trailing `"Qty"`/`"Batch Qty"` suffix from wide-format scenario column
  names.
- `_coerce_numeric(series) -> pd.Series` — strips whitespace then
  `pd.to_numeric(..., errors="coerce")`; fixes a real bug where a stray space
  (`' 750'`) made DuckDB's VARCHAR→DOUBLE cast fail outright.
- `_find_fg_column(columns)` — case-insensitive lookup for a column literally
  named `"FG"`; raises `ValueError` if absent.
- `process_volume_sheet(volume_df) -> pd.DataFrame` — melts the wide
  `Settings` sheet (one FG per row, one column per volume scenario) into
  long-format `(fg, volume_name, batch_qty)` rows.
- `process_batch_sheet(batch_df) -> pd.DataFrame` — same melt pattern for the
  `Batch` sheet into `(fg, volume, batch_qty)` rows.
- `_resolve_sheet_name(file_path, expected_name, required=True)` — 
  case-insensitive sheet-name lookup using `pd.ExcelFile` as a context manager
  (explicitly closing the file handle — fixes a real bug where an
  unclosed handle left every uploaded BOM locked on disk on Windows,
  blocking later cleanup/delete); returns `None` if not found and not
  `required`, else raises `ValueError`.
- `process_scrub_bom_workbook(file_path) -> dict` — the top-level
  orchestrator. See flow below.
- `if __name__ == "__main__":` — CLI entry point:
  `python scrub_bom_processing.py <scrub_bom.xlsx> [output.xlsx]`, writes the
  standardized SCRUB BOM sheet to an output Excel file.

**Internal execution flow:**

- **`_build_hierarchy_multipliers(df)`** — the core fix for a confirmed
  real-data bug (documented as `Test_fixes/BOM_MATRIX_QTY_ROLLUP_BUG.md`,
  out of scope): every FG-wide quantity roll-up elsewhere in the codebase was
  a flat sum of each row's own local `quantity`, never multiplied by how many
  times its parent sub-assembly is itself used, under-counting parts nested
  inside multiply-instantiated sub-assemblies. Algorithm: (1) build the set
  of `(fg, assembly)` pairs that are themselves used as an `assembly` value
  somewhere (i.e. structural/assembly-role rows); (2) build a flat `parent_of:
  (fg, cpn) -> (parent_assembly, qty)` map from every structural row
  (excluding the FG's own self-referencing root, `cpn == assembly`); (3) for
  each row, walk from its own `assembly` value up through `parent_of` toward
  the FG root, multiplying each ancestor's own local `qty` (treating
  null/NaN as `1`), memoizing per `(fg, assembly)` pair; (4) a `seen` set
  per-walk plus a `_MAX_HIERARCHY_DEPTH = 64` backstop guard against
  malformed cyclic BOMs. Result is always `>= 1` (a no-op multiplier for rows
  at or unreachable-from the FG root).
- **`process_scrub_bom(bom_file, sheet_name=0)`**: loads the sheet via
  `pd.read_excel`, strips column names; runs `semantic_mapping_scrub`; force-
  overrides `quantity`/`commodity`/`part_status`/`drawing_reference` mappings
  whenever the exact uppercase header text is present verbatim (documented:
  15 repeated dry-run calls against the same real headers showed these
  fields mapping inconsistently — up to 14/15 null for
  `drawing_reference`); validates that `cpn`/`mpn`/`quantity` all mapped
  successfully, raising `ValueError` listing the missing ones if not; prints
  a mapping table and a before/after row-count summary; calls
  `standardize_scrub_bom`.
- **`process_scrub_bom_workbook(file_path)`**: resolves all three sheet
  names (SCRUB BOM required, Settings/Batch optional — some real exports,
  e.g. a confirmed Thales template with an entirely different sheet set,
  omit Settings/Batch entirely); runs `process_scrub_bom` on the required
  sheet; runs `process_volume_sheet`/`process_batch_sheet` on the optional
  sheets if present, else returns empty DataFrames with the correct column
  shape (so downstream `queries.detect_volumes()` in `reporting_module`, out
  of scope, can fall back to "no configured volumes" gracefully); returns
  `{"scrub_bom": ..., "volume": ..., "batch": ...}`.

**Configuration usage:** No env vars or `config.py` values. Hardcoded LLM
model name `qwen2.5-coder:7b` (via the local `ollama` daemon, presumably
`http://localhost:11434` per `manage_backend.py`'s external-dependency check).
Hardcoded sheet names (`"SCRUB BOM"`, `"Settings"`, `"Batch"`) and the 21-field
canonical header list.

**Related files:** Called by `scrub_mcp_server.py`'s `standardize_scrub_bom`
tool (`process_scrub_bom_workbook`). Its `_build_hierarchy_multipliers` and
`_coerce_item_number` functions are directly unit-tested by
`test_hierarchy_multiplier.py` and `test_scrub_bom_processing.py`
respectively. Its output DataFrames are persisted by
`scrub_bom_to_database.py`.

---

## `scrub_bom_to_database.py`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum intake\scrub_bom_to_database.py`

**Purpose:** DuckDB persistence layer for `scrub_bom_processing.py`'s three
output DataFrames (`scrub_bom_items`, `volume`, `batch`), writing into
`input_db.duckdb`. Also defines `DB_PATH`, which every other `<thing>_to_
database.py` module in this codebase imports as the shared DuckDB connection
target.

**Responsibilities:**
- Own the canonical DDL for `scrub_bom_items`, `volume`, and `batch` tables,
  applied idempotently (`CREATE TABLE IF NOT EXISTS`, never `DROP TABLE`).
- Run in-place schema migrations for two historical schema changes
  (`item_number` retyped `INTEGER` → `VARCHAR`; `hierarchy_multiplier` column
  added) so existing DuckDB files self-upgrade on first use after a code
  change, without data loss.
- Insert standardized rows scoped by `rfq_id` (which may be a versioned key,
  e.g. `"CE-005570__v2"`), treating a pre-existing non-zero row count for
  that key as an idempotent no-op (not a failure) — because Dify
  unconditionally re-calls `standardize_scrub_bom` on every resume trigger.

**Dependencies:**
- Stdlib: `os`, `uuid`, `pathlib.Path`.
- Third-party: `duckdb`.
- No local module imports (this is the base module other `*_to_database.py`
  files import `DB_PATH` from).

**Public interfaces:**
- `DB_PATH` (module constant) — resolved from env var `CENTUM_INPUT_DB`,
  default `<this file's dir>/database/input_db.duckdb`. Comment explicitly
  notes this points at the project's own `database/input_db.duckdb` (which
  matches `reporting_module/config.py`'s own default and has the
  correct/complete schema), **not** the separate production file at
  `C:\SRIM-DB-SETUP\Centum_DB\` (an older, incompatible schema, confirmed
  untouched by this codebase).
- `SCRUB_BOM_ITEMS_DDL` — the `CREATE TABLE IF NOT EXISTS scrub_bom_items
  (...)` DDL string (18 data columns + `bom_item_id UUID PRIMARY KEY`,
  `rfq_id`, `imported_at`/`exported_at`/`display_order` tracking columns).
- `_column_type(conn, table, column)` — returns a column's declared type via
  `DESCRIBE {table}`, or `None` if not found.
- `_ensure_schema(conn)` — runs the two idempotent migrations (retype
  `item_number`, add `hierarchy_multiplier`) before the `CREATE TABLE IF NOT
  EXISTS`, then ensures an index on `rfq_id`.
- `process_scrub_bom_to_database(rfq_id, standardized_df) -> dict` — see flow
  below.
- `VOLUME_DDL`, `_ensure_volume_schema(conn)`,
  `process_volume_to_database(rfq_id, volume_df) -> dict` — same pattern for
  the `volume` table.
- `BATCH_DDL`, `_ensure_batch_schema(conn)`,
  `process_batch_to_database(rfq_id, batch_df) -> dict` — same pattern for
  the `batch` table.

**Internal execution flow:**

- **`_ensure_schema(conn)`**: must run **before** `CREATE TABLE IF NOT
  EXISTS` (which is a no-op against an already-existing table). First checks
  if `scrub_bom_items` exists with `item_number` still typed `INTEGER`; if
  so, drops `idx_scrub_bom_items_rfq` first (DuckDB blocks retyping *any*
  column on a table with an index present, confirmed), runs `ALTER COLUMN
  item_number TYPE VARCHAR`, then lets the later `CREATE INDEX IF NOT
  EXISTS` recreate the index. Separately checks for a missing
  `hierarchy_multiplier` column and adds it directly (no index drop needed
  for a new column). Then runs the DDL and ensures the index.
- **`process_scrub_bom_to_database(rfq_id, standardized_df)`**: copies the
  input DataFrame; generates a fresh `bom_item_id` UUID per row (no DB
  default exists for this column) and a `display_order` sequence preserving
  input row order; opens a DuckDB connection, ensures schema; counts existing
  rows for this `rfq_id` — if any exist, returns `{"status": "success",
  "rows_inserted": 0, "already_processed": True, "existing_rows": ...}`
  immediately (documented as deliberately *not* a failure — see
  `scrub_mcp_server.py`'s HITL-gate logic, which relies on this
  `already_processed` flag to avoid re-pausing an already-advancing
  pipeline); otherwise registers the DataFrame as a temp view and runs an
  explicit column-by-column `INSERT ... SELECT ... FROM temp_df`.
- `process_volume_to_database`/`process_batch_to_database` follow the
  identical shape (ensure schema → check existing count → idempotent no-op
  or insert) against their respective simpler tables.

**Configuration usage:**
- Env var `CENTUM_INPUT_DB` (default: `<project dir>/database/
  input_db.duckdb`).

**Related files:** `DB_PATH` from this file is imported by
`quote_win_to_database.py`, `erp_to_database.py`, and
`costing_sheet_to_database.py` — all four `*_to_database.py` modules write to
the **same physical DuckDB file**, just different tables. Called by
`scrub_mcp_server.py`'s `standardize_scrub_bom` tool. Consumes DataFrames
produced by `scrub_bom_processing.py`.

---

## `quote_win_processing.py`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum intake\quote_win_processing.py`

**Purpose:** Business logic for standardizing a "QuoteWin" (SupplyWin/Awards
Part Number Listing) export — a report with a variable-length metadata
preamble, an aggregate summary block, and the actual per-part award/pricing
data table — into the canonical `quote_win` schema.

**Responsibilities:**
- Dynamically locate the real header row inside the raw sheet (since the
  preamble/summary block length varies between exports, e.g. grouped
  reports), rather than assuming a fixed row index.
- Strip repeated header rows (grouped reports repeat the header before each
  group) and fully-blank separator rows.
- Use an LLM to semantically map headers to the canonical schema, with forced
  deterministic overrides for fields shown to map inconsistently in testing.
- Standardize date columns (`eff_date`, `exp_date`), stringify stray
  date/time-typed cells in otherwise free-text columns (fixing a real DuckDB
  cast-failure bug), and coerce numeric-designated columns to null-on-failure
  rather than crashing the insert.
- De-duplicate rows that are genuinely redundant (identical award status and
  pricing on every slot for the same manufacturer part), while conservatively
  preserving legitimate multi-supplier-quote rows.

**Dependencies:**
- Stdlib: `datetime`, `json`.
- Third-party: `ollama`, `pandas`.
- No local module imports.

**Public interfaces:**
- `QUOTE_WIN_TEMPLATE_HEADERS` — the 33-column canonical schema list.
- `_HEADER_ROW_SIGNATURE` — `["Part Number", "Mfg Part Number", "Commodity"]`,
  the set of literal header values that must all be present in a row for it
  to be recognized as the Group Detail table's header row.
- `_find_header_row(raw_df)` — scans every row of the header-less raw sheet
  for one containing all of `_HEADER_ROW_SIGNATURE`; raises `ValueError` if
  none found.
- `load_quote_win_table(file_path, sheet_name=0) -> pd.DataFrame` — reads the
  sheet with `header=None`, locates the real header row, slices data below
  it, drops any row that repeats the header verbatim (grouped reports) and
  any fully-blank row.
- `semantic_mapping_quote_win(headers) -> dict` — same `ollama.chat` pattern
  as the scrub-BOM/ERP/costing-sheet mappers, against
  `QUOTE_WIN_TEMPLATE_HEADERS`.
- `_NUMERIC_HEADERS`, `_DATE_HEADERS` — the columns typed
  `DOUBLE`/`DATE` respectively in the `quote_win` DDL; used to decide which
  columns skip the generic date/time stringification pass.
- `standardize_quote_win(df, mapping) -> pd.DataFrame` — see flow below.
- `_deduplicate_awarded_rows(df) -> pd.DataFrame` — see flow below.
- `process_quote_win(file_path, sheet_name=0) -> pd.DataFrame` — top-level
  orchestrator: load table → strip headers → LLM-map → force-override
  `pkg_qty`/`part_qty`/`ncnr`/`no_bid_reason` when present verbatim →
  validate `part_number`/`mfg_part_number` mapped → standardize → dedupe →
  print summary.
- `if __name__ == "__main__":` — CLI entry point, same shape as
  `scrub_bom_processing.py`'s.

**Internal execution flow:**

- **`standardize_quote_win(df, mapping)`**: renames/reorders columns per the
  canonical schema (same first-match-wins pattern as `scrub_bom_processing.
  py`); parses `eff_date`/`exp_date` from `"DD/MM/YY"` format first, falling
  back to a general `dayfirst=True` parse for unparsed values; **stringifies**
  any `datetime.date`/`datetime.time` value found in any column that is
  neither in `_NUMERIC_HEADERS` nor `_DATE_HEADERS` — this fixes a confirmed
  real bug (a WAGO/CE-005808 export) where a "Quote Validity" column mixed
  real dates (`datetime.datetime` via openpyxl) with a handful of
  bare-time-of-day cells (`datetime.time(0,0)`), and DuckDB's insert raised
  `"Unimplemented type for cast (TIME -> TIMESTAMP)"`, silently dropping
  every row (and every price) for the whole file; finally coerces every
  `_NUMERIC_HEADERS` column via `pd.to_numeric(errors="coerce")`, fixing
  another confirmed real bug (RFQ-000012's Lead Time column containing the
  literal text `"Internal Stock"`, which crashed the whole insert with
  `"Could not convert string ... to DOUBLE"`).
- **`_deduplicate_awarded_rows(df)`**: for each pair of award/price "slots"
  present (`award_1`/`price_original_1`, `award_2`/`price_original_2` — fixed
  at 2 slots per the canonical schema, not dynamically detected), groups by
  `mfg_part_number`; a row is only ever collapsed into an earlier one if it
  is fully awarded (`award_N == 100` on every present slot) **and** its
  price fingerprint (rounded to 6 decimals per slot) exactly matches a
  previously-seen row for the same `mfg_part_number` — any differing price
  or award percentage on even one slot keeps both rows. This deliberately
  preserves the legitimate "multiple suppliers genuinely quoting the same
  part" case (handled later by `reporting_module`'s `selected_quote`
  tie-break view, out of scope), only removing true no-distinction
  duplicates before that view ever sees them. Prints a count of dropped rows
  if any.

**Configuration usage:** No env vars/`config.py`. Hardcoded LLM model
`qwen2.5-coder:7b`. Hardcoded header-row signature and canonical schema.

**Related files:** Called by `scrub_mcp_server.py`'s `standardize_quote_win`
tool. Its `_deduplicate_awarded_rows` and `standardize_quote_win` functions
are directly unit-tested by `test_quote_win_processing.py`. Output persisted
by `quote_win_to_database.py`.

---

## `quote_win_to_database.py`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum intake\quote_win_to_database.py`

**Purpose:** DuckDB persistence layer for `quote_win_processing.py`'s
standardized output, writing into the `quote_win` table in the same
`input_db.duckdb` file as `scrub_bom_to_database.py`.

**Responsibilities:**
- Own the canonical DDL for the `quote_win` table (no primary key, mirrors
  live production schema exactly).
- Insert standardized rows scoped by `rfq_id`.
- Reject (not silently skip) a re-insert for an `rfq_id` that already has
  rows — unlike `scrub_bom_to_database.py`'s idempotent no-op pattern, this
  module treats a duplicate as a hard failure.

**Dependencies:**
- Third-party: `duckdb`.
- Local: `from scrub_bom_to_database import DB_PATH` — reuses the same
  DuckDB file path constant rather than redefining it.

**Public interfaces:**
- `QUOTE_WIN_DDL` — the `CREATE TABLE IF NOT EXISTS quote_win (...)` DDL
  (33 data columns matching `QUOTE_WIN_TEMPLATE_HEADERS` plus `rfq_id`).
- `_ensure_schema(conn)` — runs the DDL, ensures an index on `rfq_id`.
- `process_quote_win_to_database(rfq_id, standardized_df) -> dict` — see flow
  below.

**Internal execution flow:**
- **`process_quote_win_to_database`**: ensures schema; counts existing rows
  for `rfq_id`; if any exist, returns `{"status": "failed", "error": f"RFQ ID
  {rfq_id} already exists in quote_win", "existing_rows": ...}` — **note this
  differs from `scrub_bom_to_database.py`'s pattern**, which treats the same
  situation as a successful no-op. This means a Dify resume-retrigger that
  re-calls `standardize_quote_win` after it already succeeded once will
  report a "failed" status here, which `fastapi_router.py`'s `/tool/execute`
  will interpret as `tool_failed=True` and correctly halt advancement — an
  intentional (if differently-implemented) safety behavior, but worth noting
  as an inconsistency in idempotency handling across the four intake tools.
  Otherwise registers the DataFrame and runs an explicit
  column-by-column `INSERT ... SELECT ... FROM temp_df`.

**Configuration usage:** None directly; inherits `DB_PATH`'s `CENTUM_INPUT_DB`
env var via import from `scrub_bom_to_database.py`.

**Related files:** Imports `DB_PATH` from `scrub_bom_to_database.py`. Called
by `scrub_mcp_server.py`'s `standardize_quote_win` tool. Consumes DataFrames
from `quote_win_processing.py`.

**Inference:** The differing failure-vs-no-op behavior between this module
and `scrub_bom_to_database.py`/`costing_sheet_to_database.py` (which also
fails hard, see below) versus `scrub_bom_to_database.py` (idempotent no-op)
appears intentional given `scrub_mcp_server.py`'s comment about
`standardize_scrub_bom` specifically needing the `already_processed` signal
for its HITL gate — QuoteWin/Costing Sheet have no equivalent gate to protect,
so a hard failure on re-run may simply not have been revisited, rather than
being a deliberately different design choice for those two tools specifically.

---

## `erp_processing.py`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum intake\erp_processing.py`

**Purpose:** Business logic for standardizing an ERP purchase-history export
into the canonical `erp` schema. Currently unused in the live product (no
upload path exists — see `upload_server.py`'s costing-sheet endpoint, which
replaced the original ERP upload endpoint) but kept fully functional for
future reintroduction.

**Responsibilities:**
- LLM-based header mapping against a fixed 13-column canonical schema.
- Standardize `last_po_date` (parses `"DD/MM/YY"`, falls back to general
  `dayfirst` parse).
- Validate that all NOT-NULL-constrained fields (everything except
  `supplier_name`, `last_po_number`, `last_po_date`, `notes`) mapped
  successfully.

**Dependencies:**
- Third-party: `ollama`, `pandas`.
- Stdlib: `json`.
- No local module imports.

**Public interfaces:**
- `ERP_TEMPLATE_HEADERS` — the 13-column canonical schema (`mpn`, `mfr`,
  `quantity`, `uom`, `last_purchase_price`, `currency`, `supplier_name`,
  `in_stock_qty`, `reserved_qty`, `available_qty`, `last_po_number`,
  `last_po_date`, `notes`). Note `id`/`imported_at` are DB-generated and
  excluded from this schema.
- `semantic_mapping_erp(headers) -> dict` — same `ollama.chat` pattern as the
  other processing modules.
- `standardize_erp(df, mapping) -> pd.DataFrame` — rename/reorder per the
  canonical schema; parse `last_po_date`.
- `process_erp(file_path, sheet_name=0) -> pd.DataFrame` — top-level
  orchestrator: load → LLM-map → validate 9 required fields → standardize →
  print summary.
- `if __name__ == "__main__":` — CLI entry point, same shape as the other
  processing modules.

**Internal execution flow:** Structurally identical to
`costing_sheet_processing.py`/`scrub_bom_processing.py`'s main-sheet
pipeline: load, strip headers, LLM-map, validate required fields (raises
`ValueError` listing missing ones), standardize, print a mapping table and
row-count summary.

**Configuration usage:** No env vars. Hardcoded LLM model `qwen2.5-coder:7b`.

**Related files:** Called by `scrub_mcp_server.py`'s `standardize_erp` tool
(which, per that file's own comment, always short-circuits to `"skipped"`
today since no ERP file is ever uploaded in the current product). Output
would be persisted by `erp_to_database.py`. Not covered by any dedicated unit
test file among the 26 top-level files.

---

## `erp_to_database.py`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum intake\erp_to_database.py`

**Purpose:** DuckDB persistence layer for `erp_processing.py`'s standardized
output, writing into the `erp` table in the shared `input_db.duckdb`.

**Responsibilities:**
- Own the canonical DDL for the `erp` table.
- Insert standardized rows — **unlike every other Centum table**, `erp` has
  no `rfq_id` column at all: it's a standing, cross-RFQ purchase-history
  reference table, so imports from different RFQs' ERP exports simply
  accumulate rows rather than being gated by an existence check.

**Dependencies:**
- Third-party: `duckdb`.
- Local: `from scrub_bom_to_database import DB_PATH`.

**Public interfaces:**
- `ERP_DDL` — DDL with `id UUID DEFAULT uuid()` and `imported_at TIMESTAMP
  DEFAULT CURRENT_TIMESTAMP` both DB-generated; several `NOT NULL` columns
  matching `erp_processing.py`'s required-fields validation.
- `_ensure_schema(conn)` — runs the DDL, ensures an index on `mpn` (not
  `rfq_id`, since there is none).
- `process_erp_to_database(standardized_df) -> dict` — note the signature has
  **no `rfq_id` parameter** at all (the only `*_to_database.py` module with
  this shape) — ensures schema, registers the DataFrame, runs an
  unconditional `INSERT ... SELECT ... FROM temp_df` (no existing-rows check,
  since rows are never scoped/deduplicated by RFQ).

**Configuration usage:** None directly; inherits `DB_PATH` via import.

**Related files:** Imports `DB_PATH` from `scrub_bom_to_database.py`. Would
be called by `scrub_mcp_server.py`'s `standardize_erp` tool if that path were
ever exercised (currently always short-circuited to `"skipped"` before
reaching this module). Consumes DataFrames from `erp_processing.py`.

---

## `costing_sheet_processing.py`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum intake\costing_sheet_processing.py`

**Purpose:** Business logic for standardizing a "Costing Sheet" export (the
optional third pricing/cost input, which replaced ERP as the product's active
third upload) into the canonical `costing_sheet` schema.

**Responsibilities:**
- LLM-based header mapping against a fixed 21-column canonical schema.
- Force deterministic overrides for `ncnr`/`price_control`/`price_type`
  (shown to map inconsistently across repeated LLM runs against the same
  real file) and a positional fallback for `assembly` (no reliable header
  text to match on across real exports — sometimes a bare `"1"`, sometimes
  `"Project "` — so it's forced to the sheet's first column whenever the LLM
  leaves it unmapped).
- Standardize `exp_date`, including converting bare Excel serial date
  numbers (confirmed real-data bug: a genuine date like serial `46196`
  misread by the string-based dayfirst parser as nanoseconds-since-epoch,
  producing a near-1970 garbage timestamp) before the normal string-based
  date parsing.

**Dependencies:**
- Third-party: `ollama`, `pandas`.
- Stdlib: `json`.
- No local module imports.

**Public interfaces:**
- `COSTING_SHEET_TEMPLATE_HEADERS` — the 21-column canonical schema.
- `semantic_mapping_costing_sheet(headers) -> dict` — same `ollama.chat`
  pattern as the other processing modules.
- `_excel_serial_to_date(value)` — converts a numeric (non-bool) value via
  `pd.to_datetime(value, unit="D", origin="1899-12-30")` (the standard Excel
  serial-date epoch); leaves anything else (strings, already-parsed
  date/datetime objects, `NaN`) untouched.
- `standardize_costing_sheet(df, mapping) -> pd.DataFrame` — rename/reorder;
  applies `_excel_serial_to_date` to `exp_date` first, then the same
  `"DD/MM/YY"`-then-`dayfirst`-fallback date parse used elsewhere.
- `process_costing_sheet(file_path, sheet_name=0) -> pd.DataFrame` — top-level
  orchestrator: load → LLM-map → force-override 3 fields + positional
  `assembly` fallback → validate `part_number`/`mfg_part_number` mapped →
  standardize → print summary.
- `if __name__ == "__main__":` — CLI entry point, same shape as the other
  processing modules.

**Internal execution flow:** Same overall shape as
`scrub_bom_processing.py`/`quote_win_processing.py`'s main pipelines. The
distinguishing logic is the `_excel_serial_to_date` pre-pass on `exp_date`
and the positional-fallback rule for `assembly`
(`mapping["assembly"] = raw_df.columns[0]` if still unmapped after the LLM
and the deterministic overrides).

**Note on the "Formula blank-guard pattern" from user memory:** this file
handles **input-side** standardization (parsing an incoming Costing Sheet
Excel file into DataFrame rows) — it does not generate Excel formulas or
export workbooks itself. The blank-guard/`#VALUE!` formula-generation concern
documented in the user's memory (`formula_blank_guard_pattern.md`) pertains to
**output-side** CBOM export generation, which lives in `reporting_module`'s
`excel_formulas.py`/`exporter.py` (out of scope for this file — not found
here). No Excel-formula-writing code was found in this file.

**Configuration usage:** No env vars. Hardcoded LLM model `qwen2.5-coder:7b`.

**Related files:** Called by `scrub_mcp_server.py`'s
`standardize_costing_sheet` tool. Output persisted by
`costing_sheet_to_database.py`.

---

## `costing_sheet_to_database.py`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum intake\costing_sheet_to_database.py`

**Purpose:** DuckDB persistence layer for `costing_sheet_processing.py`'s
standardized output, writing into the `costing_sheet` table in the shared
`input_db.duckdb`.

**Responsibilities:**
- Own the canonical DDL for the `costing_sheet` table (no primary key).
- Insert standardized rows scoped by `rfq_id`; reject (hard failure, same
  pattern as `quote_win_to_database.py`) a re-insert for an `rfq_id` that
  already has rows.

**Dependencies:**
- Third-party: `duckdb`.
- Local: `from scrub_bom_to_database import DB_PATH`.

**Public interfaces:**
- `COSTING_SHEET_DDL` — 21 data columns matching
  `COSTING_SHEET_TEMPLATE_HEADERS` plus `rfq_id`; note `lead_time` is typed
  `INTEGER` here (unlike `quote_win`'s `lead_time DOUBLE`).
- `_ensure_schema(conn)` — runs the DDL, ensures an index on `rfq_id`.
- `process_costing_sheet_to_database(rfq_id, standardized_df) -> dict` — 
  ensures schema; counts existing rows for `rfq_id`; if any exist, returns
  `{"status": "failed", "error": f"RFQ ID {rfq_id} already exists in
  costing_sheet", "existing_rows": ...}`; otherwise registers the DataFrame
  and inserts via an explicit column-by-column `INSERT ... SELECT ... FROM
  temp_df`.

**Configuration usage:** None directly; inherits `DB_PATH` via import.

**Related files:** Imports `DB_PATH` from `scrub_bom_to_database.py`. Called
by `scrub_mcp_server.py`'s `standardize_costing_sheet` tool. Consumes
DataFrames from `costing_sheet_processing.py`.

---

## `test_hierarchy_multiplier.py`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum intake\test_hierarchy_multiplier.py`

**Purpose:** Regression/unit test suite locking in the fix for the "BOM
Matrix quantity roll-up bug" (`Test_fixes/BOM_MATRIX_QTY_ROLLUP_BUG.md`, out
of scope) — validates that nested sub-assembly quantities compound correctly
across multiple levels, rather than only counting the immediate parent
(which previously under-counted parts reused inside multiply-instantiated
sub-assemblies).

**Responsibilities:**
- Test `scrub_bom_processing.py`'s `_build_hierarchy_multipliers()` directly:
  multi-level compounding, cycle termination, null-quantity defaulting,
  per-row independence for a repeated leaf CPN under different parents, and
  graceful degradation with no `assembly` column.
- Test `reporting_module/templates/excel_mappings.py`'s `fg_part_qty_sums()`
  (out of scope, but exercised here) to confirm it actually *applies* the
  `hierarchy_multiplier` column before summing, and is backward-compatible
  when that column is absent.

**Dependencies:**
- Stdlib: `os`, `sys`, `time`, `unittest`.
- Third-party: `pandas`.
- Local: `from scrub_bom_processing import _build_hierarchy_multipliers`
  (project root).
- **`sys.path.insert` trick**: `sys.path.insert(0, os.path.join(os.path.
  dirname(os.path.abspath(__file__)), "reporting_module"))`, followed by
  `from templates.excel_mappings import fg_part_qty_sums` — reaches into
  `reporting_module/templates/excel_mappings.py` (out of scope) as if it were
  a top-level `templates` package.

**Public interfaces:**
- `class HierarchyMultiplierTests(unittest.TestCase)`:
  - `test_two_level_compounding` — FG→SUB-A(qty 2)→SUB-B(qty 3)→LEAF(qty 1);
    asserts LEAF's multiplier is `6.0` (2×3), proving compounding beyond the
    original bug report's single-level reproduction case.
  - `test_cyclic_reference_terminates` — a malformed BOM with a genuine
    assembly cycle (SUB-X↔SUB-Y); asserts completion under 5 seconds and all
    multipliers finite and `>= 1.0`.
  - `test_null_structural_quantity_treated_as_one` — a `None` quantity on a
    structural row; asserts the multiplier treats it as `1`.
  - `test_leaf_repeating_under_different_parents_is_independent_per_row` —
    mirrors the bug report's own real example (a leaf CPN under two different
    sub-assemblies with different quantities); asserts independent per-row
    multipliers (`1.0` vs `2.0`).
  - `test_no_assembly_column_returns_all_ones` — degenerate direct-call case;
    asserts multiplier defaults to `1.0`.
- `class FgPartQtySumsMultiplierTests(unittest.TestCase)`:
  - `test_applies_multiplier_before_cross_assembly_sum` — mirrors a real case
    (a sub-assembly used with quantity 2, containing a part with local
    quantity 1 and `hierarchy_multiplier=2.0`); asserts the summed result is
    `2` (1×2), not `1`.
  - `test_missing_hierarchy_multiplier_column_is_a_noop` — asserts backward
    compatibility (defaults to `1.0`) for data predating this column.

**Internal execution flow:** Each test builds a small synthetic in-memory
`pd.DataFrame` representing a BOM fragment, calls the function under test
directly, and asserts on specific row-index or dict-key values. No I/O, no
database, no fixtures beyond literal DataFrames.

**Configuration usage:** None.

**Related files:** Exercises `scrub_bom_processing.py`'s
`_build_hierarchy_multipliers` and `reporting_module/templates/
excel_mappings.py`'s `fg_part_qty_sums` (out of scope). Run via `python -m
unittest test_hierarchy_multiplier -v`.

---

## `test_quote_win_processing.py`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum intake\test_quote_win_processing.py`

**Purpose:** Unit tests for `quote_win_processing.py`, covering two distinct
concerns: (1) `_deduplicate_awarded_rows()`'s duplicate-collapsing logic, and
(2) `standardize_quote_win()`'s handling of messy real-world Excel data —
mixed date/time cell types and non-numeric placeholder text in numeric
columns — both of which previously caused DuckDB insert failures that
silently dropped an entire file's worth of quote/price data.

**Responsibilities:**
- Confirm duplicate-row collapsing only fires when award percentages **and**
  prices match on every slot for the same `mfg_part_number`; never merges
  legitimately distinct supplier quotes; never cross-collapses different
  manufacturer parts; safely no-ops if slot columns are entirely absent.
- Confirm `datetime.datetime`/`datetime.time` values in a free-text column
  (`quote_validity`) are stringified, while plain strings pass through
  unchanged and numeric/date-designated columns (`cost_1_conv`, `eff_date`)
  are untouched by that stringification pass.
- Confirm numeric-designated columns coerce non-numeric placeholder text
  (e.g. `"Internal Stock"`, `"TBD"`) to null rather than crashing.

**Dependencies:**
- Stdlib: `datetime`, `unittest`.
- Third-party: `pandas`.
- Local: `from quote_win_processing import QUOTE_WIN_TEMPLATE_HEADERS,
  _deduplicate_awarded_rows, standardize_quote_win` (project root). No
  database access at all — pure in-memory DataFrame tests.

**Public interfaces:**
- `_row(mfg_part, award_1, price_1, award_2, price_2, supp_name)` — helper
  building one dict-shaped quote-win row with two award slots.
- `class QuoteWinDedupTests(unittest.TestCase)` — 7 tests:
  `test_true_duplicates_collapse_to_first_occurrence`,
  `test_different_price_on_any_slot_is_not_collapsed`,
  `test_different_award_percent_on_any_slot_is_not_collapsed`,
  `test_normal_one_awarded_one_not_is_left_untouched`,
  `test_different_manufacturer_parts_never_cross_collapsed`,
  `test_three_duplicates_and_one_distinct_row`,
  `test_missing_slot_columns_returns_df_unchanged`.
- `class StandardizeQuoteWinDateTimeStringificationTests(unittest.TestCase)`
  — `_minimal_raw_df`/`_identity_mapping` helpers, plus
  `test_mixed_datetime_and_time_values_are_stringified`,
  `test_plain_string_values_pass_through_unchanged`,
  `test_numeric_and_date_columns_are_not_touched_by_stringification` —
  documented as a regression test for a real CE-005808/WAGO export.
- `class StandardizeQuoteWinNumericCoercionTests(unittest.TestCase)` — same
  helper pattern, plus `test_non_numeric_placeholder_text_becomes_null_not_a_
  crash`, `test_every_numeric_designated_column_is_coerced` — documented as a
  regression test for a real RFQ-000012 export.

**Internal execution flow:** Dedup tests build small DataFrames via `_row()`
varying award/price/supplier values and assert on `_deduplicate_awarded_rows`'s
resulting row set. Stringification/coercion tests build a minimal
all-`None`-baseline DataFrame covering every `QUOTE_WIN_TEMPLATE_HEADERS`
column via `_minimal_raw_df`, inject the value(s) under test into one column,
run through `standardize_quote_win` with an identity mapping, and assert on
the resulting column's dtype/values.

**Configuration usage:** None.

**Related files:** Tests `quote_win_processing.py` directly. Run via `python
-m unittest test_quote_win_processing -v`.

---

## `test_scrub_bom_processing.py`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum intake\test_scrub_bom_processing.py`

**Purpose:** Focused unit tests for `scrub_bom_processing.py`'s
`_coerce_item_number()` — confirming `item_number` values are normalized in
*representation* only (numeric-looking values become clean strings without a
trailing `.0`), never truncated, nulled, or rejected based on numeric size or
shape.

**Responsibilities:**
- Confirm `None`/`NaN` → `None`.
- Confirm plain int/float → clean string (`5.0` → `"5"`, not `"5.0"`).
- Confirm arbitrary free text passes through unchanged.
- Confirm large numeric CPN-like values (real case: RFQ-000015's
  `5010980138`) are preserved in full as a string, whether given as float,
  int, or already a string.
- Confirm negative values are preserved.

**Dependencies:**
- Stdlib: `unittest`.
- Local: `from scrub_bom_processing import _coerce_item_number` (project
  root). No pandas needed, no I/O.

**Public interfaces:**
- `class CoerceItemNumberTests(unittest.TestCase)` — 6 tests:
  `test_none_and_nan_become_none`, `test_plain_int_and_float_become_clean_
  strings`, `test_free_text_passes_through_unchanged`, `test_large_cpn_like_
  numeric_value_is_preserved_not_nulled`, `test_large_cpn_like_text_value_is_
  preserved`, `test_negative_value_is_preserved`.

**Internal execution flow:** Each test is a single direct call to
`_coerce_item_number(value)` with an `assertEqual`/`assertIsNone` — no setup
or fixtures beyond literal inputs.

**Configuration usage:** None.

**Related files:** Tests `scrub_bom_processing.py` directly. Run via `python
-m unittest test_scrub_bom_processing -v`.

---

## `clear_demo_data.py`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum intake\clear_demo_data.py`

**Purpose:** A one-off operational utility (explicitly documented in its own
module docstring as "not meant to be kept as permanent tooling — run once,
then delete") that wipes all demo/RFQ data across every data store in the
platform, in preparation for a clean client demo, while leaving
authentication and system-configuration tables untouched.

**Responsibilities:**
- Delete all rows (not `DROP TABLE`) from `input_db.duckdb`'s pipeline tables:
  `scrub_bom_items`, `quote_win`, `volume`, `batch`, `costing_sheet`, `erp`.
- Delete all rows from `cbom.duckdb`'s `cbom` table.
- Delete all rows from `reports.duckdb`'s tables, using `reporting_module/
  constants.py`'s `REPORT_ORDER` list (out of scope) as the table manifest.
- Delete all rows from `file_metadata_db` (Postgres) tables in FK-safe order:
  `rfq_project_tracking`, `projects`, `customers`, `rfq_process_tracking`,
  `rfq_file_telemetry`.
- Delete all rows from `logic_db` (Postgres): `final_selection_conflicts`.
- Print before/after row counts per table as a manual audit trail.
- Explicitly preserve `users`, `password_resets`, `quote_routing_profiles`,
  `system_skills_registry` (never referenced/touched anywhere in this
  script), confirmed via a printed closing message.

**Dependencies:**
- Stdlib: `sys`.
- Third-party: `duckdb`.
- Local: `db` (`get_logic_connection`, `get_metadata_connection`).
- **`sys.path.insert` trick**: hardcodes
  `_CENTUM_INTAKE_DIR = r"C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum
  intake"` and `_REPORTING_MODULE_DIR = _CENTUM_INTAKE_DIR +
  r"\reporting_module"`, inserting both onto `sys.path` before importing
  `config as reporting_config` and `from constants import REPORT_ORDER` (both
  from `reporting_module`, out of scope) and `from db import
  get_logic_connection, get_metadata_connection` (project root).

**Public interfaces:**
- `INPUT_DB_TABLES`, `CBOM_DB_TABLES`, `REPORTS_DB_TABLES` (= `REPORT_ORDER`),
  `FILE_METADATA_DB_TABLES`, `LOGIC_DB_TABLES` — the table manifests driving
  the wipe.
- `clear_duckdb(db_path: str, tables: list[str]) -> None` — opens a DuckDB
  connection, and per table: counts rows, `DELETE FROM {table}`, counts
  again, prints a before→after line; closes in a `finally` block.
- `clear_postgres(conn, tables: list[str]) -> None` — identical count/delete/
  count/print pattern over an already-open Postgres connection/cursor,
  commits once at the end.
- `main() -> None` — orchestrates all five wipes in sequence with section
  headers, then a final confirmation message.

**Internal execution flow:** Fully sequential, no conditionals, no dry-run
mode, no confirmation prompt — an unguarded, irreversible wipe the moment it
runs. The docstring instructs operators to first stop every write-holding
service (`upload_server`, `fastapi_router`/`python_bridge`, `hitl_router`,
`scrub_mcp_server`, `reporting_mcp_server`) to avoid DuckDB write-lock
contention, but the script itself does **not** verify or enforce that — it's
a manual precondition documented only in a comment. SQL is built via plain
f-string interpolation (`f"DELETE FROM {table}"`) rather than parameterized
queries; acceptable here only because every `table` value is a hardcoded
literal in this file, never external input.

**Configuration usage:**
- `reporting_config.INPUT_DB_PATH`/`CBOM_DB_PATH`/`REPORTS_DB_PATH` (from
  `reporting_module/config.py`, out of scope).
- Via `db.py`, transitively depends on `LOGIC_DB_URL`/`FILE_METADATA_DB_URL`
  env vars, defaulting to the same plaintext-credential connection strings
  flagged under `db.py` above.
- Hardcoded absolute Windows path for the `sys.path` injection (not portable
  — acceptable for a documented one-off local script).

**Related files:** Uses `db.py` directly for Postgres access. Uses
`reporting_module/config.py` and `reporting_module/constants.py` (out of
scope). Its table manifest exactly matches (and must be manually kept in
sync with — no shared constant) `backup_postgres_demo_data.py`'s manifest,
which is meant to be run first as a safety net.

---

## `backup_postgres_demo_data.py`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum intake\backup_postgres_demo_data.py`

**Purpose:** A one-off operational utility (also explicitly "not meant to be
kept as permanent tooling") that dumps every row of the Postgres tables
`clear_demo_data.py` is about to wipe into timestamped JSON files, as a
restore point ahead of that wipe.

**Responsibilities:**
- Connect to both `logic_db` and `file_metadata_db` via `db.py`.
- For each table in a fixed manifest (mirroring `clear_demo_data.py`'s
  Postgres table lists), fetch all rows/columns and serialize to JSON.
- Create a timestamped output directory
  (`database_backup_pg_{UTC_timestamp}`) under the project root.
- Print per-table row counts backed up and a completion message.

**Dependencies:**
- Stdlib: `json`, `sys`, `os`, `datetime` (`datetime`, `timezone`).
- Local: `from db import get_logic_connection, get_metadata_connection`, via
  `sys.path.insert(0, r"C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum
  intake")`.

**Public interfaces:**
- `TS` — UTC timestamp string, `%Y%m%d_%H%M%S` format.
- `OUT_DIR` — `database_backup_pg_{TS}` directory path under the project
  root; created via `os.makedirs(OUT_DIR, exist_ok=True)`.
- `LOGIC_DB_TABLES = ["final_selection_conflicts"]`,
  `FILE_METADATA_DB_TABLES = ["rfq_project_tracking", "projects",
  "customers", "rfq_process_tracking", "rfq_file_telemetry"]` — exactly
  mirror `clear_demo_data.py`'s manifests, confirming these two scripts are a
  matched backup-then-clear pair.
- `dump_table(conn, table_name: str) -> int` — runs `SELECT * FROM
  {table_name}`, zips column names with each row into a list of dicts, writes
  to `{OUT_DIR}/{table_name}.json` via `json.dump(..., default=str,
  indent=2)` (the `default=str` handles non-JSON-native types like dates/
  Decimals), returns the row count.
- `main() -> None` — dumps every `LOGIC_DB_TABLES` table via
  `get_logic_connection()`, then every `FILE_METADATA_DB_TABLES` table via
  `get_metadata_connection()`, printing per-table counts and a final
  completion message.

**Internal execution flow:** Straightforward sequential execution — no
try/except around any database call or file write; a failure partway through
raises and stops, potentially leaving a partial backup directory. No CLI
arguments; every run produces a new differently-named output directory (old
backups accumulate, never overwritten).

**Configuration usage:**
- Same as `clear_demo_data.py` via `db.py`: `LOGIC_DB_URL`/
  `FILE_METADATA_DB_URL` env vars, same plaintext-credential defaults.
- **Additional security concern:** writes full, unredacted table contents
  (potentially including customer/project PII from `customers`, `projects`,
  `rfq_project_tracking`) to plaintext JSON files on local disk with no
  encryption and no access controls beyond the OS filesystem.
- Hardcoded absolute Windows path (same portability caveat as
  `clear_demo_data.py`).

**Related files:** Uses `db.py` directly, identical pattern to
`clear_demo_data.py`. Companion/precursor script to `clear_demo_data.py`
(manifests must be kept in sync manually).

---

## `master_test_summary.md`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum intake\master_test_summary.md`

**What it documents:** Results of a bulk/regression validation run of the
**Reporting Module**'s CBOM (Consolidated BOM) report-generation pipeline
(out of scope for this reference — this file only records the *results*, not
the test code) across the numbered `test_1`..`test_21` fixture folders
(also out of scope).

**Scope and scale:**
- Generated `2026-07-30T11:15:38.496200Z`; total run duration 1682.79s
  (~28 minutes).
- 21 test folders discovered and executed (100% of discovered fixtures).
- 7 folders included a Costing Sheet input and were each run twice —
  generating `CBOM_Report_With_Costing.xlsx` and
  `CBOM_Report_Without_Costing.xlsx` — to validate both code paths.
- The remaining 14 folders lacked a Costing Sheet and were run once each,
  producing a single `CBOM_Report.xlsx`.
- Total: 28 scenario executions (7×2 + 14×1).

**Results:** All 28 scenarios **PASSED**. Zero failures, zero errors, zero
"problem folders." Every one of the 21 per-folder sections reads PASS /
"Issues documented: No."

**Conclusions:** The "All issues discovered" section is empty ("None."). The
closing "Production readiness assessment" states: *"No critical issues or
unhandled errors across any test folder/scenario. Module appears
production-ready pending review of any Major/Minor issues listed above."*
Since no Major/Minor issues are actually listed anywhere in the document,
this reads as an unqualified clean bill of health for the reporting module's
report-generation pipeline as of the July 30, 2026 run.

**Note on scope:** This is a results artifact, not test source code — it
does not reveal which specific processing modules
(`scrub_bom_processing.py`, `quote_win_processing.py`,
`costing_sheet_processing.py`, etc.) were exercised under the hood, only that
end-to-end report generation succeeded for each of the 21 fixture RFQ
datasets. **Inference:** the harness that produced this summary is very
likely a script that iterates the `test_1`..`test_21` fixture directories
(explicitly out of scope for this reference) and is not among the 26
top-level files documented here.

---

## Cross-cutting observations

- **The `sys.path.insert` coupling to `reporting_module`** appears in exactly
  three files at this top level: `hitl_router.py`, `duck_db_api.py`, and
  `bom_qa_lookup_server.py` (plus the two ops scripts `clear_demo_data.py` and
  `test_hierarchy_multiplier.py`, which use the same trick to reach
  `reporting_module/constants.py` and `reporting_module/templates/
  excel_mappings.py` respectively). In every case the pattern is: insert this
  file's own directory and `<this dir>/reporting_module` onto `sys.path`,
  then `import <module>` as if `reporting_module`'s internals were top-level
  packages. This only works because both directories are added, and because
  none of the imported module names (`database`, `final_selection`, `config`,
  `helpers`, `constants`, `templates`) collide with a top-level module in
  this folder — except `config`, which **does** exist at this top level
  (`config.py`, documented first above) and is shadowed/aliased explicitly as
  `reporting_config` wherever both are needed in the same file.
- **Two different idempotency conventions on RFQ re-run**: intake tables
  populated by `scrub_bom_to_database.py` (`scrub_bom_items`, `volume`,
  `batch`) treat a pre-existing `rfq_id` as a successful no-op
  (`already_processed: True`); tables populated by `quote_win_to_database.py`
  and `costing_sheet_to_database.py` treat the same situation as a hard
  `"failed"` status. This matters because Dify's workflow unconditionally
  re-calls every `standardize_*` tool on every resume trigger — only the
  scrub-BOM path's HITL gate in `scrub_mcp_server.py` actually depends on
  the `already_processed` flag to avoid re-pausing an already-advancing
  pipeline.
- **Plaintext Postgres credentials** (`postgres`/`DigiBull`) are hardcoded as
  the default connection strings in `db.py` and independently re-hardcoded
  (not reused) in `upload_server.py`'s `DB_CONFIG`. A live-looking Dify API
  key is also hardcoded in `upload_server.py`. These should be treated as
  findings for remediation (secrets management, credential rotation) rather
  than accepted as-is.
- **Two independent Postgres connection code paths to the same
  `file_metadata_db`** exist: `db.py`'s `get_metadata_connection()`
  (context-managed, reused everywhere else) and `upload_server.py`'s own
  `get_db_connection()` (a bare `psycopg2.connect(DB_CONFIG)`). They point at
  the same database with the same default credentials but are not the same
  code — an env-var override of `FILE_METADATA_DB_URL` would not affect
  `upload_server.py`'s hardcoded `DB_CONFIG`.
