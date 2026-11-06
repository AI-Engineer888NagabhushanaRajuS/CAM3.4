# CAM 3.4 Running Stack: Access and Login

Status captured 2026-11-03 from the running Windows machine. This records what was checked, not a guarantee that temporary ports or the NetBird address will remain unchanged.
Updated 2026-11-05: everything below is kept as originally captured; additions and status changes are marked **Update 2026-11-05**.

## Quick start: build and run with one command (Update 2026-11-05)

From `C:\CAM[3.4]-RFQ_centum\CAM-Source` (never deletes volumes or data):

```powershell
.\scripts\run-cam34.ps1            # start everything, wait until it answers, print the URLs
.\scripts\run-cam34.ps1 -Build     # rebuild the service images from the source first, restart the UI + daemon
.\scripts\run-cam34.ps1 -Status    # show what is up, change nothing
.\scripts\run-cam34.ps1 -Stop      # stop the UI, the daemon and the containers (volumes are kept)
```

`scripts\run-cam34.cmd` does the same without a PowerShell execution-policy prompt. Logs of the host processes: `CAM-Source\.run\`.
Needs: Docker Desktop, Node 24 + pnpm, Ollama with `qwen2.5-coder:7b` and `qwen3:8b`, and `CAM-Source\.env` (copy `.env.example`; `POSTGRES_PASSWORD`, `JWT_SECRET`, `OPENROUTER_API_KEY` must have values).
The script uses the existing Docker project name `cam-e2e`, so the existing volumes (database, inbox, exports) are reused.

## Browser links

| Service | Local URL | NetBird URL checked | What to expect |
|---|---|---|---|
| CAM web app | http://localhost:5181 | http://100.121.124.118:5181 | BuLLMQuote RFQ dashboard |
| Temporal UI | http://localhost:8082 | http://100.121.124.118:8082 | Temporal namespaces and workflow history; no login was requested |
| FastAPI router docs | http://localhost:15100/docs | http://100.121.124.118:15100/docs | Tool router API |
| HITL router docs | http://localhost:15102/docs | Not separately checked | Human-in-the-loop API |
| Upload API docs | http://localhost:13100/docs | Not separately checked | RFQ upload API |
| Python bridge docs | http://localhost:13110/docs | Not separately checked | DuckDB bridge API |
| Temporal gRPC | localhost:7233 | Host service | Worker connection; not a browser page |
| Temporal HTTP API | http://localhost:8233 | Host service | Temporal server HTTP API; use Temporal UI for workflow inspection |
| Keycloak | http://localhost:8080 | Not checked | A separate Keycloak service, not Temporal UI or CAM app login |

The current NetBird IPv4 address observed on interface `wt0` was `100.121.124.118`. HTTP requests to the web app, Temporal UI, router docs, and upload docs returned 200 using that address from this machine. A remote NetBird peer was not tested.

The web UI selected port 5181 because the default development port was unavailable. The dev server was started with:

```powershell
Set-Location -LiteralPath 'C:\CAM[3.4]-RFQ_centum\CAM-Source\accomplish-ui'
pnpm dev:web --host 0.0.0.0
```

**Update 2026-11-05:** `run-cam34.ps1` now starts it with `--port 5181 --strictPort`. The UI finds the backends through `accomplish-ui/apps/web/.env.local` (`VITE_BACKEND_URL=http://localhost:9334`, `VITE_RFQ_UPLOAD_URL=http://localhost:13100`, `VITE_PYTHON_BRIDGE_URL=http://localhost:13110`, `VITE_HITL_BRIDGE_URL=http://localhost:15102`, `VITE_FDE_UPLOAD_URL=http://localhost:13100`; ignored by git). Other published ports: reporting MCP :18105, intake :18002, scrub-intake :18004, gerber :18007, distributor :18003, Postgres :15432.

## CAM development login

Use the CAM page at http://localhost:5181, then click **Sign in as Tester**. Verified local development account:

- Username: `digibull`
- Password: `srim-test-2026`
- Display identity: DigiBull Staging (`tester@digibull.ai`)

This is the app's local development/test login from `accomplish-ui/apps/web/src/client/pages/LoginPage.tsx` and `accomplish-ui/apps/daemon/src/test-login.ts`. It is not a production account and is not a Keycloak or NetBird credential. The browser test successfully signed into the CAM dashboard using the button.

The daemon was started with this PowerShell environment in its process:

```powershell
Set-Location -LiteralPath 'C:\CAM[3.4]-RFQ_centum\CAM-Source\accomplish-ui'
$env:ACCOMPLISH_BACKEND_PORT = '9334'
$env:ACCOMPLISH_TEST_LOGIN = '1'
pnpm -F @accomplish/daemon dev
```

The daemon reported its Browser API on port 9334 and a successful Postgres handshake. A GET request to the API root returned 401, which is an authentication response, not evidence that the daemon is down. Keep the daemon terminal running while using the browser app.

**Update 2026-11-05:** `run-cam34.ps1` starts the daemon the same way (hidden window, log in `CAM-Source\.run\daemon.log`). Its own settings are in `accomplish-ui/apps/daemon/.env` (database URLs, `PYTHON_SERVICE_URL=http://localhost:13110`, `BOM_QA_LOOKUP_URL`, `SUPERSET_URL`, `OLLAMA_BASE_URL=http://localhost:11434`, `OLLAMA_MODEL=qwen3:8b`). The OpenRouter API key for the assistant is entered in the app's **Settings** (it is stored by the daemon, not in `.env`).

## Keycloak, Postgres, DuckDB, and NetBird credentials

- **Keycloak:** port 8080 is owned by the separate `keycloak` container. The login page shown was Keycloak, not the CAM app and not Temporal UI. The username/email was visible in the user's screenshot, but its validity and Keycloak realm were not verified. The password is deliberately not copied into this document. Do not use the CAM test login here, and no Keycloak password was changed.
- **Postgres:** CAM's Docker service is configured as database user `centum`; its password comes from `POSTGRES_PASSWORD` in the ignored `CAM-Source/.env`. The checked-in `.env.example` contains placeholders, not usable production credentials. The running `cam-e2e-postgres-1` container was healthy and listening on host port 15432. The daemon also logged a successful Postgres handshake.
- **DuckDB:** no login page or username/password. It is file-backed; CAM compose mounts the `database` directory, and `BOM_STORAGE_DB` is configured for `/app/database/bom_storage.duckdb` in containers.
- **NetBird:** a mesh/VPN, not an app database login. The machine had the NetBird interface and address listed above. The separate `ai-platform_netbird-management` Docker container was restarting with `failed creating JWT validator: Get \"\": unsupported protocol scheme \"\"`; signal and dashboard containers were up. This indicates the NetBird management service has a missing URL configuration and was not repaired as part of the CAM restart. Local NetBird IP access to the checked pages did work from this machine.
- **Temporal UI:** in this machine's current Docker setup, port 8080 belongs to Keycloak. Temporal UI was launched separately as container `cam34-temporal-ui` on port 8082, connected to the existing `cam34-net` Docker network and Temporal service at `temporal:7233`. It loaded the workflow list. No Temporal UI credential was requested.

Do not put real passwords, API keys, or tokens in this document. Use the local ignored `.env` or the organization's approved secret store for real values.

**Update 2026-11-05 (where each secret lives, names only):** `CAM-Source/.env` holds `POSTGRES_PASSWORD`, `JWT_SECRET`, `OPENROUTER_API_KEY` (compose refuses to start without these three), `CAM_PG_APP_USER`/`CAM_PG_APP_PASSWORD`, `LOGIC_DB_URL`, `FILE_METADATA_DB_URL`, the DigiKey / Mouser / Element14 keys, `BOM_STORAGE_DB`, `REPORTING_INPUT_DB`. Dev login: `digibull` / `srim-test-2026` (above). The assistant's OpenRouter key: app Settings. The root `SECRETS.md` lists where the rest are kept.

## Runtime checked

The active CAM backend is the `cam-e2e` Compose project, using `CAM-Source/docker-compose.yml` plus a temporary e2e override. This is why a plain `docker compose up` created/conflicted with a second project. The following `cam-e2e` containers were up after restart:

- Postgres (healthy), Temporal (healthy), Temporal worker
- Upload server, FastAPI router, HITL router, Python bridge
- Reporting, intake, distributor-pricing, Gerber integration, and scrub-intake MCP servers
- Separate Temporal UI container `cam34-temporal-ui`
- Local web dev server on port 5181 and daemon on port 9334

The `cam-e2e` containers were restarted in dependency order without deleting volumes. The default `cam-source-postgres-1` container had a stale/legacy mount and port conflict; it was not used for the active stack. No database volume was deleted.

**Update 2026-11-05:** the same 12 `cam-e2e` containers are up (reporting rebuilt with LibreOffice). The e2e override file the project was created with is `C:\Users\ADMIN\AppData\Local\Temp\claude\C--CAM-3-4--RFQ-centum\f77df3a1-b486-48d0-bcea-7b64608e2d5b\scratchpad\e2e\override.yml` (a Temp folder: it can disappear). It only adds test-input mounts and Ollama env; the Ollama settings for intake are now in the base `docker-compose.yml`, so `run-cam34.ps1` does not need it.

## Remaining issues found

1. The dashboard browser console reported `relation "system_skills_registry" does not exist` when loading routing-profile skills. The app opened, but routing skill loading against this database is not verified. Do not apply a schema change without inspecting the live database and its seed/migration expectations.
2. The RFQ-memory service was not running in the active `cam-e2e` container list. A real `OPENROUTER_API_KEY` is required; the placeholder `change-me` is not a working key.
3. NetBird management is restarting due to empty URL configuration, although this machine's NetBird interface and local mesh-IP HTTP requests worked.
4. The default Compose Temporal UI image reference `temporalio/ui:2.26` failed to resolve. The explicit `temporalio/ui:2.26.0` image was pulled and used for the temporary UI container.
5. Local HTTP checks returned 200 for the CAM app, Temporal UI, FastAPI docs, HITL docs, upload docs, and Python bridge docs. The browser showed active Temporal workflows. This verifies reachability, not a full RFQ execution.

**Update 2026-11-05, status of the five items above:**
1. `system_skills_registry` exists in `logic_db_2` (8 rows, checked directly). Whether the daemon's pool points at that database is still to be confirmed in the browser console.
2. The assistant does not need the RFQ-memory service: it now answers from the RFQ's own results. The local model (`qwen3:8b` through Ollama) works; the OpenRouter key goes in Settings (being wired, see "Bugs" below).
3. Unchanged (not a CAM service).
4. Fixed in `docker-compose.yml`: image `temporalio/ui:2.26.0`, host port 8082. The old manual `cam34-temporal-ui` container uses 8082 too: stop it before starting the compose one.
5. Superseded: full RFQ runs through the real UI completed (acceptance takes 22-24, evidence in `acceptance_evidence/`), and the exports were checked cell by cell.

## Bugs found while verifying 3.4, with status (Update 2026-11-05)

Fixed and committed on `master` (git log in `CAM-Source`):
1. `scan_local_file` ran the Windows ClamAV path, so every file FAILED in Linux: `CLAMSCAN_PATH`, ClamAV in the intake image (`684183b`).
2. Its telemetry write used `INSERT ... ON CONFLICT (rfq_id)`, which the versioned table cannot match, so `scan_status` stayed PENDING: plain UPDATE (`684183b`).
3. intake / distributor / gerber used `input_db.duckdb` instead of `bom_storage.duckdb` (`import_bom` failed: no `processed_bom_items`): `BOM_STORAGE_DB`, table created on first use (`684183b`).
4. Files saved by the upload server were invisible to the tool containers: shared `inbox` volume (`684183b`).
5. The UI's "continue" started a second workflow while the parked one waited forever: `resume_rfq_workflow`; a new upload supersedes a parked run (`ed8eaa0`).
6. Nothing told the UI a human review was needed (`hitl:request`): router pushes it to the daemon (`ed8eaa0`).
7. Progress was posted to a hard-coded mesh IP: `CAM_DAEMON_URL` (`ed8eaa0`).
8. The Python bridge (JWT tokens, BOM preview, inline edit, exports) was not in compose: `python-bridge` service (`2988249`).
9. Several report and Excel-compatibility fixes (Ex Inv guards, COUNTIFS, `_xlfn.NUMBERVALUE`, NRE sheets, Manifest + GO/NO-GO, error-cell gate) by the earlier session.

Fixed in the working tree (not yet committed):
10. Exports stored no cached values: 34,095 formula cells showed blank in Excel Protected View, previews and phones. `mcp-tools/reporting/superset/cached_values.py` recalculates with LibreOffice (inside the reporting container, about 10 s) and stores each value; formulas, styles and `fullCalcOnLoad` are kept. Verified on the real PROOF-23/24 workbooks: 34,095 of 34,095 cached, 0 error cells, Manifest says GO.
11. `docker-compose.yml`: Ollama for intake, Temporal UI tag and port, LibreOffice build arg for reporting.

Found 2026-11-05 and being fixed now (the RFQ assistant, middle pane):
12. The assistant pane posts to a relative URL, so the Vite dev server answers `404 Not Found` (`POST http://localhost:5181/api/rfq/<id>/chat`) and the pane says "Couldn't reach the chat service". It never reached the daemon.
13. The daemon grounds answers only through the Cognee memory service (not running) and, when that returns nothing or no RFQ is selected, sends the raw prompt to Ollama with no context: ungrounded, so it can hallucinate. New: answers come only from the RFQ's results (exported workbook values + live RFQ state), with citations, a refusal when the evidence is missing, and a check that every number and part number in an answer exists in the evidence (`fastapi-router/chat_evidence.py`, bridge endpoint `POST /api/rfq/{id}/chat/evidence`, tests in `testing/test_chat_evidence.py`).
14. With no RFQ selected, a prompt starts a generic one-shot task and navigates to the Execution page: the chat "closes" after one prompt and has no composer. The middle pane must stay the persistent assistant.
15. The OpenRouter key entered in Settings is not read by the assistant (only an environment variable is). To be wired.

Open:
16. `POST /auth/token` on the Python bridge issues a token for any `rfq_id` without authentication (security finding).
17. Intermittent: containers cannot resolve DNS (`Name or service not known`), so `pip install` fails during image builds (`scripts\run-cam34.ps1 -Build` stops with pip errors). Retry when the Docker network is healthy.
18. Distributor and gerber end to end need the DigiKey / Mouser / Element14 keys; Superset needs its credentials; RFQ_Flow end to end depends on those.
19. The 16 `#VALUE!` cells reported in Batchwise Cashflow do not reproduce on takes 23 and 24 (0 error cells in any tab).

## File paths

| What | Path |
|---|---|
| Repo (git, branch `master`) | `C:\CAM[3.4]-RFQ_centum\CAM-Source` |
| Run script | `CAM-Source\scripts\run-cam34.ps1` (+ `.cmd`), logs `CAM-Source\.run\` |
| Compose file / image recipe | `CAM-Source\docker-compose.yml`, `CAM-Source\docker\python-service.Dockerfile` |
| Secrets (ignored by git) | `CAM-Source\.env`, `accomplish-ui\apps\daemon\.env`, `accomplish-ui\apps\web\.env.local` |
| Web UI / daemon source | `CAM-Source\accomplish-ui\apps\web`, `...\apps\daemon` (dev login: `apps\daemon\src\test-login.ts`, `apps\web\src\client\pages\LoginPage.tsx`) |
| RFQ assistant | web `apps\web\src\client\components\rfq\RFQChatPane.tsx`; daemon `apps\daemon\src\rfq-chat\*` and the route in `browser-api-server.ts`; evidence `fastapi-router\chat_evidence.py` |
| Services | `CAM-Source\fastapi-router` (upload, router, HITL, bridge), `CAM-Source\mcp-tools\*`, `CAM-Source\temporal_worker` |
| Reporting / export (cached values) | `CAM-Source\mcp-tools\reporting\superset\exporter.py`, `cached_values.py`, `mcp_server.py` |
| DuckDB files (bind mount) | `CAM-Source\database\*.duckdb`; in containers `/app/database` (`bom_storage.duckdb`, `input_db.duckdb`, `cbom.duckdb`, `reports.duckdb`) |
| Docker volumes | `cam-e2e_inbox` (uploads), `cam-e2e_exports` (workbooks), `cam-e2e_postgres-data` |
| Tests | `CAM-Source\testing`, run `python -m pytest -q` from `CAM-Source` (212+ tests) |
| Evidence of full UI runs | `C:\CAM[3.4]-RFQ_centum\acceptance_evidence` (`proof_take1..`, `runs\take*_run.log`, `acceptance_runner.py`, `test_inputs\`) |
| Specs, goal ledger, handoff | `SPECS\` (`progress.json`), `docs\CAM-3.4-MEGA-GUIDE.md`, `docs\CAM-3.4-ANTIGRAVITY-GOAL.md`, `HANDOFF-2026-11-03.md`, `CAM-3.4-HANDOFF.md` (diagram transcription) |

## Safe start/check commands

Check the currently running CAM containers without stopping unrelated services:

```powershell
docker ps --filter 'name=cam-e2e' --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
docker ps --filter 'name=cam34-temporal-ui' --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
```

For this machine's current running setup, open the links above. Keep the existing `cam-e2e` project, daemon, and Vite terminals running. Do not run `docker compose down -v`, delete Docker volumes, or change Keycloak credentials as a troubleshooting shortcut.

### More commands (Update 2026-11-05)

```powershell
# everything (preferred)
cd 'C:\CAM[3.4]-RFQ_centum\CAM-Source'
.\scripts\run-cam34.ps1 -Status

# rebuild and restart ONE service of the running project (the .env supplies the secrets; --no-deps keeps Postgres/Temporal untouched)
docker compose -p cam-e2e -f docker-compose.yml up -d --build --no-deps reporting-mcp-server

# logs
docker logs --tail 100 cam-e2e-fastapi-router-1
Get-Content 'C:\CAM[3.4]-RFQ_centum\CAM-Source\.run\daemon.log' -Tail 50

# the workflow of one RFQ in Temporal (text)
docker exec cam-e2e-temporal-1 sh -c 'tctl --address $(hostname -i):7233 workflow describe -w rfq-<RFQ_ID>'

# database checks (user centum; password from .env)
docker exec cam-e2e-postgres-1 psql -U centum -d file_metadata_db_2 -c "select rfq_id, version, rfq_process_stage, hitl_required from rfq_process_tracking order by updated_at desc limit 10"
docker exec cam-e2e-postgres-1 psql -U centum -d logic_db_2 -c "select skill_index, mcp_tool_name from system_skills_registry order by 1"

# tests (backend)
cd 'C:\CAM[3.4]-RFQ_centum\CAM-Source'; python -m pytest -q -p no:cacheprovider
# tests (web / daemon)
cd accomplish-ui; pnpm -F @accomplish/web test:unit; pnpm -F @accomplish/daemon test
```

Git Bash note: `docker exec` with absolute paths needs `MSYS_NO_PATHCONV=1`. The folder name contains `[3.4]`, a wildcard for PowerShell `Test-Path` / `Get-Content` and Python `glob`: use `-LiteralPath` / `os.listdir`.
