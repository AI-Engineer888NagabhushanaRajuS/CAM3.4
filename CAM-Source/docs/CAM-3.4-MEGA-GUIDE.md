# CAM 3.4 Mega Guide

Status: repository/source audit prepared 2026-11-03. This guide describes the checked-out CAM 3.4 code and calls out runtime observations separately. It is not a claim that every end-to-end acceptance test has passed.

## 1. Scope and truth rules

CAM 3.4 is the Centum RFQ application in this repository. The target is to make the current 3.4 implementation work end to end, prove it with the real web UI, and document failures honestly. Do not silently expand the task into CAM 4.x, BAM, or another machine project.

Use these evidence labels in task notes:

- **Source-verified:** inspected in current repo code/config/docs.
- **Test-verified:** freshly run test output is recorded with command and result.
- **Runtime-verified:** live process/container/browser interaction observed now, with timestamp and evidence.
- **Reported:** mentioned by a handoff or an earlier session but not independently reproduced now.
- **Unknown:** not yet checked. Do not turn unknown into a fact by inference.

Priority when repo records disagree: engineering diagrams and current code for architecture; current SPEC acceptance criteria for scoped work; current handoff for latest investigation; older handoff/TODO and memory for historical clues only. Record unresolved contradictions instead of papering them over.

Do not inspect or commit `.env`, `SECRETS.md`, tokens, credential dumps, logs containing secrets, DuckDB/Postgres data files, generated bundles, `node_modules`, caches, or other projects. `Reference[KT]` is read-only. Do not delete volumes or database contents. Keep credentials in the ignored environment file or an approved secret manager. The visible local test account is not a production or Keycloak credential.

## 2. Repository map

The git repository is `CAM-Source/`; the workspace root is its parent. The primary owners are:

| Area | Responsibility | Main entry points |
|---|---|---|
| `fastapi-router/` | Upload, routing gate, HITL, browser bridge, DB access, progress notifications | `upload_server.py`, `fastapi_router.py`, `hitl_router.py`, `duck_db_api.py` |
| `temporal_worker/` | Durable RFQ orchestration, activities, Temporal client and worker | `workflow.py`, `activities.py`, `client.py`, `worker.py` |
| `manifests/` | Runtime tool names, service identifiers, ports, input/output declarations | Six `centum_*.json` files |
| `mcp-tools/` | Tool implementations: scrub intake, intake/BOM, reporting, distributor pricing, Gerber, RFQ memory | Each service's `mcp_server.py` |
| `database/` | Seed SQL and local DuckDB files | `pg_dump_seed/01-cam34-schema.sql` plus ignored/binary DB data |
| `scripts/` | Manifest validation/generation/import and registration | `validate_manifests.py`, `generate_manifests.py`, `import_manifest.py` |
| `accomplish-ui/apps/web/` | Browser user experience: RFQ creation, uploads, progress, HITL, outputs, chat | `src/client/App.tsx`, pages, RFQ components |
| `accomplish-ui/apps/daemon/` | Host-side browser API, SSE, auth, RFQ chat proxy, local services | `src/index.ts`, `src/browser-api-server.ts`, auth and RFQ chat modules |
| `testing/` | Python backend, reports, manifests, routing, Temporal, security and intake tests | `test_*.py` |
| `SPECS/` | Acceptance contracts and progress history | `SPEC-001` through `SPEC-018`, `progress.json`, `TODO-3.4.md` |

The Accomplish monorepo has generated/bundled trees under `apps/*/dist`, `dist-*`, and `node_modules`; those are not source-of-truth implementation leaves. Inspect the authored `src/`, configs, tests, and package scripts instead.

## 3. Runtime architecture

### 3.1 Request and orchestration path

1. The browser app creates/chooses an RFQ and uploads the required BOM and volume files to `fastapi-router/upload_server.py`. QuoteWin/costing and optional Gerber files use their own upload routes. Upload handling records metadata and paths in Postgres and stages files in the shared inbox.
2. The upload service starts `RFQWorkflow` through `temporal_worker/client.py` when Temporal is enabled. `temporal_worker/workflow.py` obtains a routing sequence and iterates its real string tool names. Each activity in `activities.py` calls the preserved router HTTP contract.
3. `fastapi-router/fastapi_router.py` validates RFQ/tool state against Postgres routing data, applies versioning and gate logic, reports progress to the daemon, and dispatches the tool.
4. `fastapi-router/config.py` loads `manifests/*.json` and maps each declared tool to its service's direct `/mcp` endpoint. `fastapi-router/tool_calling.py` implements FastMCP streamable HTTP initialization/session/call behavior. The active router does not require Bifrost or MCP Jungle.
5. The selected FastMCP service processes the RFQ. Scrub intake standardizes files; reporting builds CBOM and reports; optional tools handle BOM import, distributor pricing, and Gerber data. They share database/inbox volumes or connect to Postgres as configured.
6. When work needs a person, the router/service emits a HITL request. `hitl_router.py` records the decision and signals the waiting Temporal workflow. The browser receives request/progress events through the daemon's RFQ-scoped SSE API, renders the relevant control, and submits the user decision.
7. The Python bridge (`duck_db_api.py`) supports browser-authenticated database actions such as BOM preview/edit and output download. Reporting tools write report artifacts; the UI's right/output pane displays progress, review state, previews, and exports.

Function and endpoint names containing `dify` are compatibility-era naming; the default runtime is Temporal in current 3.4 configuration. Do not infer the orchestration engine from a legacy URL or symbol name; inspect `CAM_USE_TEMPORAL` and its actual caller.

### 3.2 Important ownership boundaries

| Data/service | Primary owner/use | Caution |
|---|---|---|
| Postgres logic DB | Routing profiles, skill registry, current skill index, HITL/final-selection state | Validate live database/schema before any repair; seed scripts do not run again on an already-initialized volume |
| Postgres file metadata DB | RFQ versions, file paths/roles, processing stages and upload telemetry | File paths must be visible from all relevant containers through the same inbox mount |
| Temporal | Workflow state/history and task queue | Server/worker are separate processes; check both before a UI run |
| `input_db.duckdb` | Standardized input tables | Mounted/shared path must agree across tool containers |
| `cbom.duckdb` and `reports.duckdb` | Reporting CBOM and report tables | Reporter and browser bridge need consistent database directory mounts |
| `bom_storage.duckdb` | Intake/distributor/Gerber BOM structures and enrichment | Uses `BOM_STORAGE_DB`; never overwrite real RFQ data during a test |
| RFQ-memory store | Chat context and citations | Requires its service plus real model/provider settings; placeholder API keys are not functional |
| Daemon storage | Local app session/config data and browser API | Host process, separate from Compose; run with CAM-approved dev settings for a local test |

These are architectural ownership summaries from code/config, not a live SQL audit. Confirm actual schemas and DB names before modifying rows.

## 4. UI acceptance flow

The actual acceptance is the human-visible workflow, not a curl script or a green backend-only test. Execute in the real browser in this order:

1. Open the Vite app, authenticate through the app's local development sign-in only where enabled, and capture the starting state.
2. Create a fresh unique RFQ through the UI. Do not reuse an RFQ with existing rows or a running workflow.
3. Upload the BOM and required volume file through the UI. Verify the selected RFQ, filenames, upload acknowledgement, and first workflow in Temporal.
4. Watch the app's live progress stream and confirm the left stage/timeline and right output pane change from actual server events.
5. Wait for the intake gate. Confirm the UI offers the QuoteWin/Costing Sheet action only when the workflow is genuinely waiting for it.
6. Upload the test QuoteWin file (and costing sheet if the selected workflow needs it) through the UI. Use the actual Continue/resume control. Confirm the same Temporal workflow resumes; do not approve it with a direct endpoint or script.
7. Reach final-selection review. Confirm the modal/panel appears, conflicts and choices are readable, select and submit an option in the UI, and verify the corresponding workflow signal/state transition.
8. Allow report generation/validation/export to complete. Confirm all expected result entries and downloadable artifacts are visible in the right pane, not just a success toast or backend row count.
9. Download the output through the UI and verify the file opens and contains the expected sheets/data. Record any intentionally unsupported/missing vendor API behavior separately.

At every step, save milestone screenshots, browser console/page errors, network request/response evidence, RFQ/workflow IDs, and timestamps. Redact authorization headers, cookies, JWTs, API keys, and private BOM/customer data from evidence. A browser page returning HTTP 200 is a reachability check, not an end-to-end pass.

## 5. Continuous screen recording requirement

For acceptance, capture **one uninterrupted screen recording** beginning before the first browser interaction and ending only after final output is visible in the right pane and the exported file has been checked. The recording must show the human-like actions, upload progress, HITL review, workflow resume, final review, and all visible results. Do not satisfy this with stitched clips or screenshots.

Before recording, ensure the recording tool is actually capturing the browser/desktop, select an evidence directory outside source/test data, and verify a short start/stop probe file if that can be done without consuming the acceptance recording. Start the full recording before creating the RFQ. Keep it running throughout waits and the flow; do not pause at HITL or while results load. Save the original recording and a brief metadata note (duration, resolution, start/end timestamps, RFQ/workflow IDs). Never embed credentials or private customer source data in a public artifact.

If the UI is visibly wrong, automatically diagnose the nearest owning code, make the smallest fix, run a focused test, and then do a **new complete recording from the beginning with a new RFQ**. Preserve earlier failed recordings and their evidence; do not claim a stitched or interrupted take is complete. A maximum of two targeted repair cycles per distinct UI defect and three full E2E attempts total prevents infinite retry. If the limit is reached, stop the loop, preserve evidence, state the blocker and exact next action, and do not claim acceptance.

If no screen-recording mechanism is available in the environment, do not silently substitute screenshots. Mark the E2E recording criterion blocked, explain the missing capability, and provide the viable manual recorder procedure needed to complete it.

## 6. Environment, startup, and address map

The following are source-configured Compose host ports; they are not proof that a process is running:

| Component | Host port | Container port / notes |
|---|---:|---|
| Postgres | 15432 | 5432 |
| Temporal gRPC | 7233 | 7233 |
| Temporal server HTTP | 8233 | 8233 |
| Temporal UI in stock Compose | 8080 | 8080; may conflict with an unrelated local service |
| Upload API | 13100 | 3100 |
| FastAPI router | 15100 | 5100 |
| HITL router | 15102 | 5102 |
| Python bridge | 13110 | 3110 |
| Reporting MCP | 18105 | 8105 |
| Intake MCP | 18002 | 8002 |
| Distributor-pricing MCP | 18003 | 8003 |
| Scrub-intake MCP | 18004 | 8004 |
| Gerber MCP | 18007 | 8007 |
| RFQ-memory service | 18108 / 18109 | 8108 / 8109 |

Host UI services are separate: Vite's current checked-in config defaults to port 5181 (Vite may auto-select another free port), while the Accomplish daemon Browser API is configured to run on 9334 for this CAM web setup. UI endpoint variables must target the **host-published** Compose ports when Vite runs on the host. A container callback to the host needs `host.docker.internal`/host-gateway or the correct reachable NetBird address, depending on deployment.

Observed on 2026-11-03 in this workstation session, not a durable project default:

- `cam-e2e` Compose containers for Postgres, Temporal, worker, router, upload, HITL, bridge, and tool servers were running; Postgres and Temporal reported healthy.
- Keycloak from a separate Compose project owned port 8080. Temporal UI was therefore separately launched on host 8082 as `cam34-temporal-ui`, attached to `cam34-net`. It displayed workflow history. Never assume 8080 is Temporal UI on this host.
- The web UI ran at `http://localhost:5181`; current NetBird interface IP observed was `100.121.124.118`. Local requests to web, Temporal UI, router docs, and upload docs via that IP returned 200 from this same machine. Remote peer access was not tested.
- The daemon was running on 9334 and logged a Postgres handshake. The browser dev tester button entered the CAM dashboard.
- The browser console reported `relation "system_skills_registry" does not exist` when the dashboard tried to load routing skills. The cause was not resolved or confirmed against the live DB.
- NetBird management container `ai-platform_netbird-management` was reported restarting with an empty URL/JWT-validator error; local interface and tested mesh URLs still worked. RFQ memory was not running because a real provider key was unavailable.

Start only the already-identified CAM project/compose configuration. Inspect `docker compose ls`, container labels, current ports and the running project's Compose files before running `up`, `down`, or rebuilding. Do not blindly start a second default Compose project: it can conflict on ports and select a different database volume. Do not use `down -v`, delete volumes, reset passwords, or stop unrelated project services as a shortcut.

## 7. Configuration and credential handling

- `CAM-Source/.env.example` is a template, not a credential source. Values like `change-me` cannot authenticate to production services.
- Compose Postgres user defaults to `centum`; its password is supplied via `POSTGRES_PASSWORD`. Other DB/app connections use their own URL/user settings. Verify actual live runtime configuration without printing secrets.
- Keycloak is an identity provider for its own configured realm/app clients. A Keycloak sign-in page is not the CAM application login and its password is not the CAM dev login. Do not change the Keycloak password unless explicitly tasked and after identifying its owner/application impact.
- DuckDB is file-based and has no built-in username/password login screen.
- NetBird is a VPN/mesh and access path, not a shared database credential.
- The local app's **Sign in as Tester** path is development-only and intentionally distinct from Keycloak/production login. Use it only in the local dev build.
- Never paste the local `.env`, database container environment, tokens, cookies, or password values into terminal output, docs, screenshots, recordings, or git. Do not commit `.env`, `.env.*` secrets, or `SECRETS.md`.

## 8. Manifest and routing contracts

`manifests/centum_*.json` describe actual hand-written tool servers; they are not a code-generation input in CAM 3.4. `scripts/validate_manifests.py` validates shapes, `generate_manifests.py` derives manifests from code, and `import_manifest.py` can write registrations to Postgres. Read the script help and test coverage before use. Registry/apply operations have database side effects; use dry-run first and never run `--apply` against a live database without explicit approved target, backup, and verified rollback receipt.

The routing resolver depends on exact tool names found in a manifest. A name missing from all manifests fails dispatch; a container being healthy does not prove its manifest host/port, `/mcp` endpoint, or router session is correct. Prove a tool by a real list/call path with non-empty results and record the selected manifest/server.

Current architecture: direct FastMCP HTTP calls with service URL derived from the manifest and optionally overridden per service in Compose. Bifrost is not an active 3.4 service. MCP Jungle may exist as an external/legacy running container or registration utility, but it is not the normal 3.4 router hop. Treat old comments that say otherwise as drift and verify any purported active caller before relying on them.

## 9. Test and evidence strategy

Run the narrow behavior test while iterating, then the full backend suite from `CAM-Source`:

```powershell
python -m pytest -q -p no:cacheprovider
```

UI package test/typecheck commands must be taken from the current `accomplish-ui/apps/web/package.json` and workspace scripts; inspect before running. For Temporal logic use the SDK time-skipping workflow tests as well as a live worker/UI check. For SQL/schema claims, inspect the actual initialized database or use an isolated disposable test DB. For manifest changes validate every manifest and run direct-routing tests.

Evidence record per check: timestamp, exact command/action, exit status, relevant unedited output, test count, skipped/xfail reasons, RFQ/workflow ID if applicable, screenshot/recording path, console and network failures. Do not turn prior handoff test counts into fresh verification.

## 10. Current worktree state and immediate decisions

At the start of this documentation task, git reported branch `feat/cam34-verification`, HEAD `30aef90`, and these modified/untracked files:

- Modified: `accomplish-ui/apps/web/src/client/App.tsx`
- Modified: `accomplish-ui/apps/web/src/client/components/rfq/RfqIntakeProgressPanel.tsx`
- Modified: `fastapi-router/upload_server.py`
- Modified: `mcp-tools/intake/bom_to_database.py`
- Modified: `mcp-tools/reporting/superset/mcp_server.py`
- Modified: `scripts/import_manifest.py`
- Modified: `testing/test_intake_tools.py`
- Untracked: `.dockerignore`
- Untracked: `database/backfill_macro_category.sql`
- Added for this task: `docs/CAM-3.4-MEGA-GUIDE.md` and `docs/CAM-3.4-ANTIGRAVITY-GOAL.md`

Validation on 2026-11-03: backend `python -m pytest -q -p no:cacheprovider` -> **200 passed, 4 skipped**; web typecheck -> success; web unit suite -> **29 files, 371 tests passed**. Combined web `pnpm -F @accomplish/web test` -> **9 integration files failed, 3 passed; 57 tests failed, 96 passed**. Failure signatures include test doubles missing `window.accomplish.onDaemonReconnected` and integration assertions expecting the old Accomplish brand while current UI is Centum-branded. Those integration failures remain open; the backend/unit passes do not prove full UI acceptance.

The initial local branch query found `feat/cam34-verification` but no `master` or `main`. The user requested local `master`: after reviewing and committing the authorized CAM changes on the current feature branch, create `master` at that exact commit and check it out with a clean worktree. Keep both local refs at the same commit. Do not push, force-push, or rewrite history. Never include ignored secrets, generated files, test databases, runtime recordings, or unrelated project files.



This is the reviewed source/config/test surface index, not a list of every generated or third-party file.

### Router and workflow

- Router leaves: `fastapi-router/auth.py`, `bom_qa_lookup_server.py`, `config.py`, `db.py`, `duck_db_api.py`, `fastapi_router.py`, `hitl_router.py`, `manage_backend.py`, `rfq_memory_client.py`, `tool_calling.py`, `upload_server.py`.
- Temporal leaves: `temporal_worker/__init__.py`, `activities.py`, `client.py`, `config.py`, `worker.py`, `workflow.py`.
- Runtime control: `docker-compose.yml`, `docker/python-service.Dockerfile`, `.env.example`, `pytest.ini`, `requirements.txt`, `requirements-test.txt`.

### Tool services

- Intake: `mcp-tools/intake/apply_alternatives.py`, `bom_processing.py`, `bom_to_database.py`, `config.py`, `detect_alternates.py`, `matrix_bom_volume_enrichment.py`, `mcp_server.py`, `tool_calling.py`.
- Scrub intake: `mcp-tools/scrub-intake/analytics_events.py`, `analytics_posthog_client.py`, `costing_sheet_processing.py`, `costing_sheet_to_database.py`, `db.py`, `erp_processing.py`, `erp_to_database.py`, `quote_win_processing.py`, `quote_win_to_database.py`, `scrub_bom_processing.py`, `scrub_bom_to_database.py`, `scrub_mcp_server.py`, `tool_calling.py`.
- Distributor pricing: `mcp-tools/distributor-pricing/__init__.py`, `apply_alternatives.py`, `config.py`, `currency.py`, `detect_alternates.py`, `digikey_client.py`, `element14.py`, `enrichment.py`, `export_bom.py`, `models.py`, `mcp_server.py`, `mouser_client.py`, `quote_summary.py`.
- Gerber: `mcp-tools/gerber-integration/config.py`, `extraction_pipeline.py`, `gerber_tables.py`, `mcp_server.py`, `pcba_schemas.py`, `pcb_geometry_service.py`, `tool_calling.py`; submodules `bom_parser/parser.py`, `checklist_extractor/extractor.py`, `component_intel/packages.py`, and `config/package_map.yaml`.
- Reporting core: `mcp-tools/reporting/superset/batch_validate_all_tests.py`, `cbom_generator.py`, `config.py`, `constants.py`, `currency.py`, `database.py`, `enrich_issue_docs.py`, `enrichment.py`, `excel_formulas.py`, `excel_formatter.py`, `exporter.py`, `final_selection.py`, `helpers.py`, `logging_utils.py`, `mcp_server.py`, `migrations.py`, `queries.py`, `report_generator.py`, `reporting_pipeline.py`, `schema.py`, `scrap_factor.py`, `validator.py`.
- Reporting leaves: `reports/aclass_parts.py`, `batchwise_cashflow.py`, `bom_matrix.py`, `cbom_vl.py`, `ex_inv_vl.py`, `lead_time_consolidated.py`, `lead_time_fg.py`, `mech_em_nre.py`, `missing_notes.py`, `part_num_vs_mfg_num.py`, `pcb_nre_fai_charge.py`, `price_control.py`, `revision_history.py`, `sum_and_count.py`, `sum_and_count_detailed.py`, `summary.py`; templates `excel_mappings.py`, `excel_styles.py`, `formula_templates.py`.
- RFQ memory/shared: `mcp-tools/rfq-memory/citation_store.py`, `config.py`, `ingest.py`, `memory_service.py`, `query.py`, `versioning.py`, `test_versioning.py`; `mcp-tools/shared/highlight_style.py`.
- Manifests: `centum_distributor_pricing.json`, `centum_gerber_integration.json`, `centum_intake.json`, `centum_reporting.json`, `centum_rfq_memory.json`, `centum_scrub_intake.json`.
- Scripts and schema: `scripts/generate_manifests.py`, `import_manifest.py`, `validate_manifests.py`; `database/pg_dump_seed/01-cam34-schema.sql` and `database/backfill_macro_category.sql`.

### UI and daemon high-value source surfaces

- Web routing/session/config: `accomplish-ui/apps/web/src/client/App.tsx`, `router.tsx`, `config/endpoints.ts`, `lib/session.ts`, `lib/accomplish-backend.ts`.
- Web RFQ and outputs: `components/rfq/RfqCreateForm.tsx`, `RfqExecutionCard.tsx`, `RfqIntakeUploadModal.tsx`, `RfqIntakeProgressPanel.tsx`, `RfqErpQuoteWinUploadModal.tsx`, `RFQChatPane.tsx`, and `components/execution/StageExecutionOutput.tsx`.
- Web login: `pages/LoginPage.tsx` plus its shared auth components and the UI package scripts/config.
- Daemon request/events/auth: `apps/daemon/src/browser-api-server.ts`, `auth-server.ts`, `auth/routes.ts`, `auth/pg-auth.ts`, `test-login.ts`, `db.ts`, `rfq-chat/rfq-chat-client.ts`, `task-service.ts`, `index.ts`.

### Test coverage index

- Report behavior: `test_aclass_lead_time_text.py`, `test_aclass_shares_and_turns.py`, `test_batchwise_empty_section.py`, `test_bom_matrix_no_volumes.py`, `test_bom_matrix_root_only.py`, `test_cbom_tree_dual_role.py`, `test_ex_inv_previous_sheet.py`, `test_ex_inv_volume_type.py`, `test_final_selection_resolved.py`, `test_lead_time_first_volume.py`, `test_missing_notes_null_ids.py`, `test_mpn_normalize.py`, `test_null_mpn_quantity.py`, `test_report_proto_volume.py`, `test_revision_history_volume_two.py`, `test_summary_revision_isolation.py`, `test_sum_and_count_consistency.py`, `test_exporter_reference_sheet.py`, `test_report_validators.py`, `test_reports.py`.
- Runtime/security/routing: `test_daemon_push.py`, `test_database_fresh_connect.py`, `test_database_rebuild.py`, `test_hitl_decision_signal.py`, `test_hitl_resolve_confirm_signal.py`, `test_hitl_signals.py`, `test_hitl_temporal_config.py`, `test_intake_tools.py`, `test_manifest_pipeline.py`, `test_mcp_routing_config.py`, `test_posthog_events.py`, `test_reporting_imports.py`, `test_rfq_chat.py`, `test_router_session_retry.py`, `test_routing.py`, `test_security_fixes.py`, `test_sql_hardening.py`, `test_shadow_run_parity.py`, `test_temporal_live_signal.py`, `test_temporal_resume.py`, `test_temporal_workflow.py`, `test_upload_temporal_trigger.py`.
- No evidence in this indexed Python suite establishes a complete create/upload/HITL/export browser E2E. Add or run a real browser-level acceptance flow and preserve its recording/evidence.

For exact call behavior, read the implementation and its neighboring tests. This index helps find owners; it is not a substitute for reading code before edits.