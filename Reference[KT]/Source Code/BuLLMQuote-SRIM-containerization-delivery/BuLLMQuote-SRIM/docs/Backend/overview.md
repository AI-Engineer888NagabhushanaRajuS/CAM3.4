# Backend Overview

## Table of Contents

- [Scope](#scope)
- [Service map](#service-map)
- [Startup process](#startup-process)
- [Folder structure](#folder-structure)
- [Middleware / cross-cutting concerns](#middleware--cross-cutting-concerns)
- [Related documents](#related-documents)

## Scope

"Backend" here means everything orchestrated by `manage_backend.py`, living
at `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum intake\` — the FastAPI
routers, the live FastMCP tool servers, and their shared data-access
modules. Full per-file documentation is in
[Backend/file-reference.md](./file-reference.md); this document is the
service-level map and startup story.

## Service map

All 10 services `manage_backend.py` starts/stops/health-checks, confirmed
live and healthy throughout this documentation effort's own session:

| Service | Host:Port | Entry point | Role |
|---|---|---|---|
| `upload_server` | `127.0.0.1:3000` | `upload_server.py` | Receives BOM/QuoteWin/Costing Sheet uploads; triggers the Dify DMR workflow |
| `fastapi_router` | `127.0.0.1:5000` | `fastapi_router.py` | Routing-sequence lookup + `/tool/execute` — called by the Dify workflow |
| `hitl_router` | `127.0.0.1:5002` | `hitl_router.py` | Human-review endpoints for the `resolve_final_selection` HITL gate |
| `scrub_mcp_server` | `192.168.1.27:8004` | `scrub_mcp_server.py` | 4 BOM/QuoteWin/Costing/ERP standardization tools (live) |
| `reporting_mcp_server` | `192.168.1.27:8005` | `reporting_module\mcp_server.py` | 6 CBOM/reporting tools (live) |
| `bom_qa_lookup_server` | `192.168.1.27:8006` | `bom_qa_lookup_server.py` | Scripted Q&A shortcut for accomplish-ui's chatbot, bypassing the LLM/MCP loop entirely for known question shapes |
| `python_bridge` | `192.168.1.27:3010` | `duck_db_api.py` | HTTP/DuckDB bridge — file listing, downloads, exports |
| `web_frontend` | `192.168.1.27:5180` | `accomplish-ui\apps\web` (external repo) | The React/Vite frontend |
| `superset` | `127.0.0.1:8088` | External install at `C:\Superset\` | Reporting dashboards |
| `daemon` | `localhost:9234` | `accomplish-ui\apps\daemon` (external repo) | Node/Express backend-for-frontend; also receives the DMR's HITL notifications |

Plus 3 external dependencies `manage_backend.py` also health-checks but
does not itself start: **Postgres** (`logic_db`/`file_metadata_db`),
**Ollama**, and the **MCP Jungle gateway**.

## Startup process

`manage_backend.py` (see
[Backend/file-reference.md](./file-reference.md#manage_backendpy) for full
detail) supports:
```
python manage_backend.py start      # start every service not already running
python manage_backend.py stop       # stop every service this script started
python manage_backend.py restart    # stop, then start
python manage_backend.py status     # one-shot health report, exit 0 if all healthy else 1
python manage_backend.py monitor [--interval SECONDS] [--auto-restart]
```
Each service is launched as a plain subprocess (no containers); PIDs, log
paths, and start times are persisted to `.backend_services_state.json` so
`status`/`stop`/`monitor` work correctly even from a separate invocation
than the one that ran `start`. Per-service stdout/stderr is captured to
`centum intake\service_logs\`.

**Known limitation, confirmed directly**: every service's launch path is a
hardcoded absolute filesystem path (e.g. pointing at
`C:\Users\ADMIN\Downloads\accomplish-ui\accomplish-ui\apps\web\` for the
frontend). Moving any of these services to a new location breaks this
script's ability to manage them until the paths are updated — this was
encountered directly while building the `BuLLMQuote-SRIM` consolidated repo
(see [Deployment/deployment.md](../Deployment/deployment.md)).

## Folder structure

```
centum intake/
├── *.py                     -- 26 root files: routers, MCP server, db access, processing scripts (see file-reference.md)
├── reporting_module/        -- separate self-contained package, see Reporting/reporting-module.md
├── database/                -- live runtime DuckDB files (cbom.duckdb, input_db.duckdb, reports.duckdb)
├── staged/inbox/            -- staging area for incoming uploads awaiting processing
├── test_1 .. test_21/       -- CBOM pipeline validation fixtures
├── Test_fixes/              -- bug-fix validation scripts and reference workbooks
├── database_backup_*/       -- point-in-time DB snapshots (manual, not automated)
├── deprecated/              -- explicitly retired code
└── service_logs/            -- per-service stdout/stderr
```

Not a git repository — no version control was found at this root as of this
writing (in contrast to `accomplish-ui`, which is its own git repo — see
[Frontend/accomplish-ui.md](../Frontend/accomplish-ui.md)).

## Middleware / cross-cutting concerns

No shared middleware layer (auth, request logging, rate limiting) was found
applied uniformly across the FastAPI services — each of `fastapi_router.py`/
`hitl_router.py`/`upload_server.py`/`duck_db_api.py` configures its own
CORS middleware independently (confirmed: each imports
`fastapi.middleware.cors.CORSMiddleware` separately rather than sharing one
app factory). See [Architecture/overview.md](../Architecture/overview.md#security)
for the security implications of this.

## Related documents

- [Backend/file-reference.md](./file-reference.md) — every file in this folder, in full detail
- [APIs/endpoints.md](../APIs/endpoints.md) — every HTTP endpoint these services expose
- [Deployment/deployment.md](../Deployment/deployment.md) — orchestration, current vs. target state
- [DMR/dynamic-master-router.md](../DMR/dynamic-master-router.md) — how `fastapi_router.py` is actually driven
