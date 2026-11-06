# Deployment

## Table of Contents

- [Current reality vs. target state](#current-reality-vs-target-state)
- [Development setup (current, working)](#development-setup-current-working)
- [Orchestration mechanics](#orchestration-mechanics)
- [Networking](#networking)
- [Secrets](#secrets)
- [The BuLLMQuote-SRIM consolidation effort](#the-bullmquote-srim-consolidation-effort)
- [Docker / Kubernetes](#docker--kubernetes)
- [CI/CD](#cicd)
- [Related documents](#related-documents)

## Current reality vs. target state

This section is written to be honest about the gap between what's running
today and what a "production deployment" doc usually implies. As
implemented and directly observed:

| Aspect | Current state |
|---|---|
| Process model | 10 plain OS processes on one Windows machine, no containers |
| Orchestrator | `manage_backend.py` — a Python script, not Docker Compose/Kubernetes |
| Service discovery | Hardcoded absolute file paths + hardcoded host:port pairs |
| Config management | A mix of `.env` files, hardcoded defaults in `config.py`/`db.py`, and hardcoded literals duplicated across files (see [MCP/mcp-jungle.md](../MCP/mcp-jungle.md)'s `MCP_JUNGLE_URL` duplication note) |
| CI/CD | None found for `centum intake` (not a git repo at all); `accomplish-ui` has its own `.github/` CI, unrelated to this platform's own backend |
| Containers | None for the backend; `accomplish-ui` has a `Dockerfile` (for the Accomplish product itself) |
| Backup/DR | None found — see [Database/logic-database.md](../Database/logic-database.md#backup-strategy) |

## Development setup (current, working)

1. Postgres running locally with `logic_db` and `file_metadata_db`
   databases populated (see
   [Database/logic-database.md](../Database/logic-database.md) for the
   expected schema — no `.sql` file exists in this codebase to run; the
   schema is assumed pre-provisioned).
2. `centum intake\database\` populated with `input_db.duckdb` (scrub BOM,
   quote win, etc.) — `reports.duckdb`/`cbom.duckdb` are generated fresh on
   first use if missing.
3. MCP Jungle running and reachable at `http://localhost:8080/mcp`, with
   at least a `postgres-mcp` backing server registered (see
   [MCP/mcp-jungle.md](../MCP/mcp-jungle.md)).
4. Ollama running (health-checked by `manage_backend.py` but not otherwise
   documented in this codebase's own source — an external dependency).
5. From `centum intake\`: `python manage_backend.py start`.
6. A Dify instance (self-hosted or cloud) with the `Dify_DMR` workflow
   imported (see
   [DMR/dynamic-master-router.md](../DMR/dynamic-master-router.md)) and its
   `DIFY_BASE_URL`/`DIFY_API_KEY` configured in `upload_server.py`'s
   environment.

## Orchestration mechanics

`manage_backend.py`'s key functions, confirmed by reading the source:

- `SERVICES` (module-level list) — the declarative list of all 10 managed
  services (see [Backend/overview.md](../Backend/overview.md)'s service
  table), each presumably with its own launch command, working directory,
  health-check URL/method, and dependency info.
- `check_service_health(svc)` — per-service health check; `_tcp_open()` /
  `_http_get()` are the two underlying primitives (a raw TCP connect check
  vs. an HTTP GET check — which one is used depends on the service).
- `check_dependency(dep)` — the same style of check applied to the 3
  external dependencies (Postgres, Ollama, MCP Jungle).
- `start_service(svc, state)` / `stop_service(name, state)` — subprocess
  launch/termination; `is_pid_alive(pid)` guards against acting on a PID
  that's no longer running.
- `wait_for_health(svc, timeout=30, interval=1.0)` — polls after starting
  a service until it reports healthy or times out.
- `load_state()` / `save_state(state)` — persistence to
  `.backend_services_state.json`, so `status`/`stop`/`monitor` work
  correctly even from a separate process invocation than the one that ran
  `start`.
- `print_status(state, verbose=True)` — renders the `HEALTHY` /
  `PROCESS UP, NOT RESPONDING` / `DOWN` table and the overall
  `ALL HEALTHY` / `ONE OR MORE ISSUES` summary line.
- `cmd_start` / `cmd_stop` / `cmd_restart` / `cmd_status` / `cmd_monitor` —
  the 5 CLI subcommands, dispatched from `main()`.

## Networking

Services bind to a mix of `127.0.0.1` (loopback-only:
`upload_server`, `fastapi_router`, `hitl_router`, `superset`) and
`192.168.1.27` (a specific LAN interface: `scrub_mcp_server`,
`reporting_mcp_server`, `bom_qa_lookup_server`, `python_bridge`,
`web_frontend`) — plus `daemon` on `localhost:9234`. `bom_qa_lookup_server.py`
itself notes (in its own inline comment, quoted verbatim) why it
specifically binds `0.0.0.0` internally despite being listed under the
`192.168.1.27` LAN address in the service table: *"0.0.0.0, not a single
fixed LAN IP -- binding to one specific interface address means the
process refuses connections on every OTHER interface (e.g. the NetBird
virtual adapter) regardless of firewall rules."* This inconsistency (some
services LAN-bound, some loopback-only, one deliberately `0.0.0.0`) is
worth normalizing in any future containerization effort.

## Secrets

Confirmed present, in plaintext, in source (flagged for remediation, not
glossed over): `db.py` hardcodes a default Postgres credential
(`postgres`/a plaintext password) as its connection string default;
`upload_server.py` independently re-hardcodes its own copy of that same
style of credential rather than importing `db.py`'s; a Dify API key is
hardcoded in `upload_server.py`. None of these were changed as part of
this documentation effort — they are called out here so they're tracked,
not silently normalized as "how this system works." A real deployment
hardening pass should move all of these to environment variables/a secrets
manager and eliminate the duplicated credential definitions.

## The BuLLMQuote-SRIM consolidation effort

This documentation set itself lives inside a new, separate,
in-progress consolidation repo (`C:\Users\ADMIN\Documents\BuLLMQuote-SRIM\`)
whose own root `README.md` documents its own migration status in detail.
Relevant summary for this Deployment doc:

- `accomplish-ui\` (the whole monorepo: web + daemon + desktop +
  agent-core) has been copied in and dead-code-audited (see
  [Frontend/accomplish-ui.md](../Frontend/accomplish-ui.md)).
- `fastmcp-router\` has 9 backend service files copied in from `centum
  intake\` — 3 of the 9 (`hitl_router.py`, `duck_db_api.py`,
  `bom_qa_lookup_server.py`) require `mcp-tools/reporting/superset/` (see
  below) plus a `REPORTING_DATABASE_DIR` environment override to fully
  function from their new location, since `reporting_module`'s own
  default DB path resolution (`../database`) doesn't reach this repo's
  `database/` folder from the new nesting depth.
- `mcp-tools/reporting/superset\` has `reporting_module` copied in (same
  DB-path caveat as above — documented in
  [Reporting/reporting-module.md](../Reporting/reporting-module.md)).
- `mcp-tools/intake\`, `mcp-tools/bom-processing\`,
  `mcp-tools/distributor-pricing\` are still **empty placeholders** —
  populating them from `Tools\I n D\intake\`/`distributor_pricing\` was
  explicitly deferred pending mapping clarification.
- `database\` has one file populated (`Bom_storage.duckdb`, copied from
  `C:\SRIM-DB-SETUP\Databases\`) — a **different schema** from what the
  migrated `reporting_module` code expects (see
  [Database/logic-database.md](../Database/logic-database.md) and
  [Reporting/reporting-module.md](../Reporting/reporting-module.md) for
  the distinction).
- `INSTALL.bat`, `docker-compose.yml` in this consolidated repo's root are
  still **placeholders** (a real install/compose setup can't function yet
  since the backend migration is only partial) — only `LAUNCH-WEB.bat` is
  fully functional today (runs `apps/web`'s dev server from the new
  location).

**None of this consolidation work has touched the live, currently-running
`centum intake\` system** — every copy operation was one-directional
(source untouched, verified via checksum comparisons at each step), and
`manage_backend.py status` was re-confirmed `ALL HEALTHY` after each
migration step throughout this effort.

## Multi-user production topology

This section documents the outcome of a 2026-08 multi-user (5-concurrent-user)
production-readiness review (`MULTI_USER_PRODUCTION_READINESS.md`, provided
by the platform owner). Decisions below were made explicitly, not inferred
from silent defaults — see the two sub-sections for what was decided and why.

**Decision: one Node daemon (`accomplish-ui/apps/daemon`) per user, not one
shared daemon.** The daemon's task/workspace storage
(`apps/daemon/src/storage-service.ts`) is a single shared SQLite file for the
whole process lifetime — it was never designed as a multi-tenant server.
Rather than rearchitect that storage layer, each of the 5 users runs their
own local daemon + web build (their own `accomplish-dev.db`), and NetBird (or
an equivalent mesh) connects each user's machine to the ONE shared central
application server that hosts the parts that legitimately need to be
centralized: the Python backend (`centum intake`), Postgres, and the DuckDB
files. Today's `manage_backend.py` config (a single `daemon` entry on
`localhost:9234`) reflects the current single-developer dev setup, not this
target topology — moving to real 5-user use is a deployment/runbook change
(each user's machine runs its own daemon), not a further code change.

As a secondary consequence, this topology also shrinks the blast radius of
the HITL cross-user broadcast bug (see below) to zero once adopted, since
separate daemon processes have separate in-memory SSE client sets. The
per-RFQ SSE scoping fix was still implemented, because a single user's own
multiple browser tabs on different RFQs (all served by that user's one
daemon) can still cross-pollinate HITL popups within that one daemon
instance.

**Decision: per-RFQ isolation is accepted as sufficient; no Python-backend
user-identity/auth system will be built.** `centum intake`'s Python backend
(`fastapi_router.py`, `upload_server.py`, `hitl_router.py`, etc.) has no
`user_id`/`username`/session concept anywhere, and no user column on
`rfq_process_tracking`/`rfq_file_telemetry` — every isolation boundary is
`rfq_id` (+`version`), never "who initiated this." This was flagged as a
potential gap (closing it fully would mean adding auth middleware to every
Python endpoint plus schema changes) but was explicitly deferred: the
platform owner decided per-RFQ isolation is enough for now. Treat this as a
documented, accepted limitation, not an oversight — a future hardening pass
that wants real per-user attribution/audit trails in the Python backend will
need to revisit it as new, scoped work.

**Concurrency fixes shipped as part of this review** (all in `centum
intake\`, mirrored into this repo's `fastmcp-router\`/`accomplish-ui\`
copies):

| Issue | Fix | File |
|---|---|---|
| HITL popup broadcast to every connected browser tab regardless of which RFQ they were viewing | Per-rfqId SSE routing (`sseClientsByRfq` map + `sendToRfq()`), plus a client-side rfqId match guard as the always-correct layer | `accomplish-ui/apps/daemon/src/browser-api-server.ts`, `apps/web/src/client/App.tsx` |
| `/tool/execute`'s `async def` route called blocking `requests.post()` directly, freezing the single-worker Uvicorn event loop for every user for the call's full duration | Changed to a plain `def` route (FastAPI dispatches sync routes to its thread pool automatically) | `fastapi_router.py` |
| Two concurrent uploads for the same `rfq_id` could race on computing the next version number | Serialized with `pg_advisory_xact_lock(hashtext(rfq_id))` at the top of the upload transaction | `upload_server.py` |
| Two near-simultaneous Dify-workflow triggers for the same `(rfq_id, active version)` could both start a pipeline run | `db.try_start_pipeline_run()` — a time-based "already processing" guard (default 30 min staleness window); rejects the second trigger with a clear response instead of racing | `db.py`, `upload_server.py` |
| Two `export_reports` calls for the same `rfq_id` within the same second could silently overwrite each other's output file | Added a short random suffix to the export filename | `reporting_module/exporter.py` |

Re-verified as already safe by construction during this review (no change
needed): `hitl_router.py`'s conflict-resolution `UPDATE ... WHERE
resolved_source IS NULL` naturally converges when two users resolve the same
conflict concurrently; DuckDB's file-level locking + MVCC safely serializes
(rather than corrupts) concurrent writes to different `rfq_id` rows.

## Docker / Kubernetes

Not present for the core backend. `accomplish-ui` has its own `Dockerfile`
(for the Accomplish product), unrelated to `centum intake`. No Kubernetes
manifests were found anywhere in scope for this documentation effort.

## CI/CD

None for `centum intake` (no git repo, no CI config found).
`accomplish-ui` has its own `.github/` workflows and `.husky/` git hooks —
these govern that product's own release process, not this platform's
backend.

## Related documents

- [Backend/overview.md](../Backend/overview.md)
- [Database/logic-database.md](../Database/logic-database.md)
- [Architecture/overview.md](../Architecture/overview.md#deployment-model)
- [DeveloperGuide/getting-started.md](../DeveloperGuide/getting-started.md)
