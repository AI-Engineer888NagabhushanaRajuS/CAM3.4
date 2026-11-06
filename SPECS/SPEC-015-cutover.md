# SPEC-015 — Cut-over completeness (part 1: verified defects)

**Status:** IN PROGRESS. Defects D1, D2, D5, D6, D7, D8, D9 fixed and covered by tests. Live verification is NOT done (no services in this session). **Branch:** feat/spec-015-cutover (from feat/spec-014-parity-harness). **Depends on:** SPEC-014.

## Context
HANDOFF §7 and GOAL §3: start with D1, D2, D5, D6, D7, then HITL by signal end to end, Dify call sites removed or behind a flag, upload_server starts the Temporal workflow, Temporal persistence decision. HANDOFF §5: Dify is retired.

## Done in this SPEC (with tests)
| ID | Fix | Where | Test |
|---|---|---|---|
| D1 | `/pipeline/routing-sequence` reads `db.get_routing_sequence()` + `db.get_current_skill_index()` instead of `call_tool` | fastapi-router/fastapi_router.py (import aliased `db_get_routing_sequence` because the endpoint has the same name) | testing/test_shadow_run_parity.py::test_routing_sequence_reads_db_not_gateway (gateway patched down) |
| D2 | `RFQWorkflow` loops over tool-name strings; args = `{"rfq_id": rfq}` (Dify body) | temporal_worker/workflow.py | testing/test_shadow_run_parity.py::test_offline_trace_parity_dify_vs_temporal |
| D5 | worker default router URL `:5100` | temporal_worker/config.py | testing/test_temporal_workflow.py::test_config_defaults (was asserting the bug, now 5100) |
| D6 | per-manifest host via `CAM_MCP_HOST_<MANIFEST_ID>`; compose sets them to service names | fastapi-router/config.py; docker-compose.yml (fastapi-router env) | testing/test_mcp_routing_config.py (4 tests) |
| D7 | rfq-memory manifest port 8008 -> 8108 | manifests/centum_rfq_memory.json | testing/test_mcp_routing_config.py |
| D8 | removed stale Bifrost :8010 health entry (3.4 calls tool servers directly). It did NOT gate startup: `cmd_start` ignores the result; `status` reported ISSUES | fastapi-router/manage_backend.py | covered by suite only (no test) |
| D9 | upload_server docstring: default is Temporal | fastapi-router/upload_server.py | docstring only |

Test-shape fixes: the existing Temporal tests mocked dict steps, which hid D2. They now use the real string shape (testing/test_temporal_workflow.py, testing/test_hitl_signals.py). The parity harness xfails for D1/D2 were removed once fixed.

## Verified
```
pytest -q -rxs --tb=short -p no:cacheprovider   (from CAM-Source)
129 passed, 3 skipped, 2 warnings in 13.65s
```
The 3 skips are the live parity tests (need `CAM_PARITY_LIVE=1` and running services).

## Not done (still open for SPEC-015)
- **Live verification of D6**: no Docker, so the compose network and container hostnames are unverified. The compose test checks only that the keys and service names are consistent.
- **HITL by signal end to end**: the workflow waits for `human_decision` (verified offline by the parity test). hitl_router's signal send was NOT run live.
- **`trigger-hitl` in the Temporal path**: the Dify flow called the daemon's `/api/internal/trigger-hitl` (port 9234) before halting. Whether the Temporal path still needs that UI notification is unverified; OPEN.
- **Profile conflict**: Dify YAML requests `RFQ_Flow`; the Temporal client default and the live test use `Standard_BOM_Flow`. Not resolved. Default for now: the caller passes the profile (no default changed).
- **Temporal persistence**: default Postgres (as compose does). Recorded here as the decision; not verified live.
- **D3** (endpoint field `postgres_stage` holds a version): logged in SPEC-014; not fixed here.
- **`/code-review`** not run on this diff (HANDOFF §8 rule 5). Run before merge.

## Code review (/code-review medium, commit 6877526) and outcome
- Finding 1 (fixed, commit e5cf4fe): a routing-sequence error body (HTTP 200, `{"error"}`) made the workflow report an empty "completed" run. Fixed in `activities.get_routing_sequence`; regression test added.
- Finding 2 (OPEN, not changed): `manifests/centum_rfq_memory.json` port 8108 is the chat listener; 8109 is the internal ingest. The manifest declares no tools, so nothing calls it yet. Harish to confirm which port the manifest should name.
- Finding 3 (fixed): stale xfail comment in test_shadow_run_parity.py.
- Finding 4 (fixed): hoisted `tool_args` out of the loop.
- Commit e5cf4fe holds the fixes. SPEC-015 is still in progress: live verification pending.

## Live verification (this round)
- Compose: `docker compose config` exits 0 (placeholder values for this check only). Fixed: missing docker/python-service.Dockerfile (added); distributor-pricing env_file now optional (commit dff0718).
- Image build NOT possible on this host: the Docker registry (auth.docker.io, registry-1.docker.io) does not resolve, and no python base image is cached. So the D6 container-network check (router -> tool container by service name) is NOT verified. Verified only that compose resolves CAM_MCP_HOST_* to the service names and that each container port equals the manifest port (tests in testing/test_mcp_routing_config.py).
- Live D1 (router on the host, Postgres 18 throwaway container, seeded quote_routing_profiles): GET /pipeline/routing-sequence/CE-LIVE-1/Standard_BOM_Flow returned the DB routing sequence with the gateway not running. PASS.
- Live parity tests (CAM_PARITY_LIVE=1, router :5100, seeded DB): 3 passed (5 with the offline tests). Note: test_api_status_agrees_with_active_version is close to tautological (see its docstring).

## Container bring-up (this round) -- supersedes the earlier "D6 not verified" note for the reporting path
Registry became reachable; images built.
- postgres:18 up and healthy (fixed: mount /var/lib/postgresql, commit 249bdf8).
- fastapi-router up; reporting-mcp-server up (fixed: libmagic1 in the shared image, commit 249bdf8).
- D6 VERIFIED for reporting: router container resolves centum_reporting__cbom to http://reporting-mcp-server:8105/mcp, and MCP initialize + tools/list over the compose network return the reporting tools.
- NOT VERIFIED (containers crash on import, modules missing from the repo): intake (bom_to_database), gerber-integration (extraction_pipeline), distributor-pricing (enrichment), scrub-intake (analytics_events). These modules are imported by the tool servers but are not in the repo or in git history of CAM-Source; the 3.3 baseline does not contain them; the read-only reference copy has bom_to_database.py only. Tests stub these imports, so they did not catch it.
- DECISION NEEDED (single ask): supply the four modules (or confirm the reference copy of bom_to_database.py is the 3.3 source to port, with DB_PATH defaulting to REPORTING_INPUT_DB).

## Missing tool-server modules: the import chain (investigated, NOT ported)
Each crash-looping tool server imports modules that are not in the repo. The reference copy (Reference[KT]/.../BuLLMQuote-SRIM/mcp-tools) is the only source. Its a8c0cbd baseline commit has these files unmodified: bom_to_database, extraction_pipeline, analytics_events, bom_processing, analytics_posthog_client. The CAM-Source v3.3-baseline tag has NO mcp-tools folders at all. distributor-pricing/enrichment.py is untracked in the reference copy (origin unknown).
Chain observed (each step is one more missing module):
- intake: bom_to_database -> needs config.DB_PATH (no intake/config.py) -> bom_processing (needs ollama, in requirements) -> tool_calling (missing in intake)
- scrub-intake: analytics_events -> analytics_posthog_client -> scrub_bom_processing (missing)
- gerber-integration: extraction_pipeline -> bom_parser, checklist_extractor, component_intel, pcb_geometry_service (+ config/ dir), all in reference copy only
- distributor-pricing: enrichment (untracked in reference; origin unknown)
Porting the closure from the reference copy is a scope decision (it may be most of the old tool tree). Nothing was ported or committed; the attempted copies were removed.
DECISION NEEDED: (a) port the full closure from the reference copy as 3.3 source, (b) remove/disable the four tool servers from compose for 3.4 and keep only reporting, or (c) supply the modules. Default recommended: (b) until a decision is made.

## Tool-server port (per your decision: option 2, rules 1-8)
Source of truth: Reference[KT] repo commit a8c0cbd (tagged CAM 3.3 baseline). Correction to earlier notes: the baseline DOES track the closure; the earlier "missing" claim came from checking only root-level .py files. `shared` lives at mcp-tools/shared/ (db_config.py, highlight_style.py), not at the repo root. distributor-pricing is UNTRACKED in the reference repo (no SHA; origin unknown); ported last.

Commits (branch feat/spec-015-tool-servers):
- b4131e9 intake: helpers copied unmodified (bom_to_database, bom_processing, detect_alternates, apply_alternatives, matrix_bom_volume_enrichment, README); config.py and tool_calling.py written for 3.4 (Bifrost removed); Ollama host and bind host from env.
- 60f6962 scrub-intake: helpers copied unmodified (analytics_*, costing_sheet_*, db.py, erp_*, quote_win_*, scrub_bom_*, requirements.txt); tool_calling.py written for 3.4 (Jungle removed).
- 07d4bce gerber-integration: closure copied unmodified (bom_parser/, checklist_extractor/, component_intel/, config/, extraction_pipeline.py, gerber_tables.py, pcb_geometry_service.py, pcba_schemas.py, requirements.txt); config.py and tool_calling.py written for 3.4; bind host from env.
- 8f1bb01 distributor-pricing: copied (untracked source) + shared/highlight_style.py from a8c0cbd; config.py for 3.4; bind host from env; compose PYTHONPATH for shared/.

Each server: container up; from the router container, MCP initialize + tools/list over the compose network. Results:
- intake: import_bom, scan_local_file (manifest centum_intake: 2) MATCH
- scrub-intake: standardize_scrub_bom, standardize_quote_win, standardize_erp, standardize_costing_sheet (manifest centum_scrub_intake: 4) MATCH
- gerber-integration: extraction_pipeline tool extract_features (manifest: extract_features) MATCH
- distributor-pricing: 5 tools (manifest: 5) MATCH; docs (reference docs/MCP) say 4: UNVERIFIED
- reporting (earlier): 7 tools MATCH

Security (rule 4): literal IPs in the four servers' bind lines replaced with CAM_BIND_HOST; OLLAMA host literal replaced with CAM_OLLAMA_URL; Jungle/Bifrost constants removed; no credentials were in the copied modules (distributor API keys come from env, names in .env.example). db_config.py was NOT ported (not imported by the ported code). The 19 other repo files that still contain the NetBird address are NOT yet changed (out of scope of these four servers).

Not verified / still open:
- The real 8-step Standard_BOM_Flow run in compose on a test RFQ including intake steps: NOT RUN (needs the Temporal server and worker up, Ollama for intake header mapping, test BOM/QuoteWin/ERP/costing/Gerber files, and a seeded 8-step routing profile).
- Intake: import_bom and scan_local_file end to end (need Ollama + files). Intake telemetry uses a direct SQL shim (tool_calling.py), replacing the 3.3 Bifrost route.
- distributor: which tables enrich_bom writes in REPORTING_INPUT_DB (UNVERIFIED); tool count 4 vs 5 (UNVERIFIED).
- gerber: extract_features end to end (needs gerber files and pcb geometry deps).
- The four servers' health: MCP handshake only (no HTTP health route in FastMCP); compose has no healthcheck for them.

## 8-step Standard_BOM_Flow run: status (commit fd1edca)
Done (verified in containers):
- postgres from an empty volume: schema fixture seeds logic_db_2 / file_metadata_db_2 and the 8-step Standard_BOM_Flow profile (from docs/Database/logic-database.md, 3.3 baseline).
- temporal (auto-setup 1.24) healthy; temporal-worker connected and listening on cam-rfq-pipeline.
Fixed on the way (all committed): Temporal driver name; Temporal healthcheck address; init-script mount path.

NOT done:
- The tool servers and router were not started together with the worker for the run.
- Test input: the reference staged inbox has BOM and VOLUME workbooks but NO file identifiable as the QuoteWin report (standardize_quote_win needs one). The candidates are the AWARDS_PART_NUMBER_LISTING files; mapping them to the QuoteWin role is UNVERIFIED. Default to propose: use the AWARDS listing for the QuoteWin role, after confirming the column layout against the 3.3 quote_win_processing.py.
- Intake: import_bom and scan_local_file end to end (needs Ollama models, the test files, and the telemetry rows the upload path would normally write).
- The HITL resolve_final_selection step needs the human decision signal (hitl_router signal path, verified offline and in a live Temporal test earlier, not in this flow).
- Result: the real 8-step run has NOT been executed; no output to paste yet.

## First real Standard_BOM_Flow run (in progress; blocked on the Ollama model)
Stack (compose project cam-e2e, scratch override in the scratchpad, NOT in the repo): postgres (schema fixture), temporal (healthy), temporal-worker (listening), fastapi-router, intake, scrub-intake, reporting, gerber, distributor. Ollama on the host.
Test RFQ RFQ-E2E-1: BOM = "369500_BOM_CE-005814-Nexteer ... SCRUB BOM (1).xlsx" (has the SCRUB BOM sheet); QUOTEWIN = "264834_VOLUME_AWARDS_PART_NUMBER_LISTING_CE-005808-WAGO ...xlsx" (DEFAULT CHOSEN, see below); no COSTING_SHEET (costing step returns "skipped", as designed).
QuoteWin default evidence: the AWARDS listing has the QuoteWin header signature (Part Number, Mfg Part Number, Commodity) at row 16 and Cost #N (Conv.) / Price (Original) #N columns, so quote_win_processing.py's signature check accepts it. UNVERIFIED that its values reconcile with the Nexteer BOM.
Fixes found by the run (committed, RED first): workflow failed-status (run ended FAILED instead of completing silently); client status field; router 404 session retry; scrub shim session keyword (61f8c88, 1995eed).
Blocker: standardize_scrub_bom and standardize_quote_win call qwen2.5-coder:7b (hardcoded in 5 baseline modules). The model is not installed; `ollama pull` stalls on this host's network; a background retry loop is still running. Installing it needs either the pull to finish or a decision: approve stopping the stalled ollama processes (denied by the auto-mode classifier as interfering with workloads), or pull the model yourself with `ollama pull qwen2.5-coder:7b`. Substituting another model under the coder name was NOT done, to keep the verification honest.
rfq-memory ingest: 127.0.0.1:8109 unreachable (rfq-memory not in this run). Non-fatal; noted.
Not yet verified: any step's real output; the HITL step; import_bom / scan_local_file.

## Run update 2026-11-02 (RFQ-E2E-3, Standard_BOM_Flow)
Fixed and committed (d74c542): currency_settings missing from the schema fixture (export_reports failed with "relation currency_settings does not exist"; same DDL as the daemon's ensureCurrencySchema, also applied to the running logic_db_2); summary.py merge inverted for a zero-volume revision block (proto-only with include_proto=False) ("3 must be greater than 4"); guard added, same pattern as revision_history.py. Also a costing_sheet/erp table pair was created in input_db via migrations.ensure_costing_and_erp_tables (display_order backfill in migrations.py still reports "did not produce a clean 1..N sequence" across the shared table; it is not run; record as open).
Latest run: COMPLETED (status 2). Only centum_reporting__export_reports ran in that run (skill index resumed past earlier steps); export wrote a 21-sheet workbook. Earlier runs had reached the scrub HITL (approved by a test operator signal) and the resolve_final_selection HITL; the release of the resolve gate is NOT verified from the history.
Tests: 175 passed, 4 skipped (same as baseline).
Still open: the 8-step run has not been verified end to end from a clean state; import_bom / scan_local_file still not run; the display_order migration check.

## Final verification 2026-11-02 (clean 8-step run, real HITL endpoints)
Status: COMPLETED with the caveats listed below. Branch feat/spec-015-tool-servers (chain from feat/spec-015-cutover).
- D1 (routing from DB) and D2 (string steps): fixed in 6877526; covered by testing/test_shadow_run_parity.py (routing endpoint with db stubbed) and testing/test_temporal_workflow.py (string steps). Caveat: the fix and its test landed in one commit, so the failing-first step is not visible in git history.
- New defect found by the live run, RED first: hitl_router loads fastapi-router/config.py, then temporal_worker/client.py's bare `import config` returned that module, so every HITL signal failed with "module 'config' has no attribute 'TEMPORAL_HOST'" (HTTP 502). Test: testing/test_hitl_temporal_config.py. Fix: client.py loads its own config.py by path. Latent: activities.py has the same bare `import config`; it is not on the HITL path, so it is not changed here.
- New defect found by the live run, RED first: the zero-conflict confirm of resolve_final_selection advanced rfq_process_stage and returned without signalling the workflow, so the run stayed parked at the gate. Test: testing/test_hitl_resolve_confirm_signal.py. Fix: shared helper _signal_resolve_approved() in hitl_router.py, used by both the empty and non-empty branches.
- Full suite after both fixes: 177 passed, 4 skipped (baseline 175 + 2 new tests).
- Clean run RFQ-E2E-6 (seeded from the same two staged inputs, stage 0): Temporal status COMPLETED. All 8 activities returned status success: standardize_scrub_bom (HITL gate, approved via POST /api/rfq/{id}/hitl/decision, signal delivered), standardize_quote_win, standardize_costing_sheet (skipped by design: no costing sheet uploaded), cbom (897 rows), enrich_costing_sheet (rows_matched_costing 0), resolve_final_selection (HITL gate, confirmed via POST /api/rfq/{id}/final-selection with empty resolutions, signal_delivered true), generate_reports, export_reports (21 worksheets). Final rfq_process_stage 8, hitl_required false, no TOOL FAILED lines for RFQ-E2E-6.
- Dify call sites: upload_server.py runs the Dify HTTP path only when USE_TEMPORAL is false (compose default true). Flag satisfied; the Dify code is kept behind the flag.
- Temporal persistence: Postgres (compose: postgres:18 with the auto-setup DB postgres12 driver). Decision recorded; verified live in this stack.
- Not verified: upload_server starting the workflow end to end from an HTTP upload (covered offline by testing/test_upload_temporal_trigger.py only; the e2e runs started workflows via the client). Intake import_bom and scan_local_file were not run. The costing branch with a real costing sheet was not run.
- Note: the earlier RFQ-E2E-3/4/5 runs used the Temporal signal directly (send_hitl_approve), bypassing the router confirm, so their stage numbers are not evidence. E2E-5 was finished through the endpoint after the fix.

## Verification 2026-11-03 (branch feat/cam34-verification, off feat/spec-017-bug-hunt; the spec branches are unchanged)
Step 1, reporting rebuild: the running container had 0 matches for `_with_blank_mpn` in templates/excel_mappings.py; after `docker compose -p cam-e2e ... up -d --build --no-deps reporting-mcp-server` it has 6 (the source has 6); the other 9 containers were not touched; router `tools/list` through manifest routing returns the 7 reporting tools.
Step 2, intake scan_local_file + import_bom (test RFQ RFQ-INTAKE-1: BOM "102478_BOM_Harness ... UBR" + VOLUME "110401_VOLUME_UBR-Vol", PENDING telemetry rows, called through the router's own manifest routing into the real intake container; NOT through /tool/execute, because intake is in no profile's routing_sequence in this fixture and the gate would return {"skipped": true}). Four defects found by running them, RED first (testing/test_intake_tools.py, 8 tests), all fixed in 684183b:
- scan_local_file ran the Windows path C:\Program Files\ClamAV\clamscan.exe: both files FAILED ("[Errno 2] No such file ... clamscan.exe"). Now CLAMSCAN_PATH (default unchanged, pinned by a test); the intake image installs ClamAV 1.4.3 (INSTALL_CLAMAV build arg; freshclam bakes the signatures in, so a long-lived deployment must refresh them).
- Its telemetry write used `INSERT ... ON CONFLICT (rfq_id)`; rfq_process_tracking has PK (rfq_id, version) + a partial unique index, so Postgres raised "there is no unique or exclusion constraint matching the ON CONFLICT specification", the error was swallowed and scan_status stayed PENDING. Now a plain UPDATE of hitl_required; the tool no longer sets rfq_process_stage (fastapi_router owns it; a second advance would skip a step on resume). In 3.3 against the versioned table this write failed the same way (inferred; the live DB is not here).
- import_bom wrote to input_db.duckdb, which has no processed_bom_items table: `Catalog Error: Table with name processed_bom_items does not exist!`. 3.3's intake, distributor-pricing and gerber-integration shared ONE bom_storage.duckdb (Reference mcp-tools/shared/db_config.py: C:\SRIM-DB-SETUP\Databases\bom_storage.duckdb; tables processed_bom_items, update_alternatives, gerber_*). The REPORTING_INPUT_DB default for those three servers was a wrong guess made in SPEC-015's tool-server port (and repeated in the instruction that drove it). Now BOM_STORAGE_DB (default /app/database/bom_storage.duckdb) in all three configs; compose sets it; processed_bom_items is created on first use with the 3.3 columns (taken from the Reference seed database/Bom_storage.zip, schema only, no data copied).
- Results after the fixes: scan CLEAN x2 (file_type from libmagic), persisted (scan_status CLEAN, processed_at set, execution_logs); tracking row stage 0, hitl_required false. Negative control with the standard AV test string: INFECTED ("Eicar-Test-Signature FOUND"), hitl_required true, persisted. import_bom: {"status": "success", "hitl": 0, "rows_after_consolidation": 105}; processed_bom_items 105 rows, bom_structure_items 308 rows for the RFQ in bom_storage.duckdb; input_db.duckdb unchanged.
- Open (not fixed, recorded): (a) fastapi_router checks only `hitl` in a tool result; scan_local_file returns `hitl_required`, so on an INFECTED/FAILED scan the router still advances the stage and clears the flag, while the Temporal workflow (which checks both) waits for a signal and hitl_router then advances the stage again. Inferred from code, not run. (b) process_bom_to_database returns {"status": "failed", "error": "RFQ ID ... already exists"} when the RFQ was already imported and import_bom ignores it and still reports success (3.3 behaviour; a re-upload as a new version would keep the old rows). (c) fastapi-router duck_db_api.py and hitl_router.py hardcode BOM_STORAGE_DB_PATH = C:\SRIM-DB-SETUP\Databases\bom_storage.duckdb, unreachable in a container, so the RFQ_Flow HITL endpoints that read it do not work in compose. (d) distributor-pricing and gerber-integration now point at bom_storage.duckdb but were not run end to end. (e) The e2e fixture has no RFQ_Flow profile: 3.3's RFQ_Flow rows are named in Bifrost style (`intake-scan_local_file`, per docs/MCP/bifrost.md) while manifests and the router use the `centum_intake__scan_local_file` style, so moving RFQ_Flow to 3.4 needs its registry/profile rows renamed (live rows not available here; unverified). (f) the Docker build context has no .dockerignore (images are ~5.5 GB).
Step 5, worktrees: the 12 leftover worktrees under the old scratchpad (clean/SPEC-012..017, wt/SPEC-012..017) were removed with `git worktree remove --force` + `git worktree prune`; none had uncommitted changes; `git worktree list` now shows only the main checkout.
- OPEN DECISION for Harish (not changed, because the answer is not in the repo): which routing profile does an upload start? In 3.4, upload_server -> temporal_worker/client.py start_rfq_workflow(rfq_id) uses the default profile "Standard_BOM_Flow", the one verified end to end. In 3.3 the choice was made inside Dify: the export Reference dify-orchestration/Dify_DMR_RFQ_Flow.yml is "duplicated from Dify_DMR (6).yml with only the routing-sequence lookup's hardcoded profile name changed from Standard_BOM_Flow to RFQ_Flow" (its URL ends /pipeline/routing-sequence/{rfq_id}/RFQ_Flow), and which app was live depended on the DIFY_API_KEY in the environment (not in the repo). POST /api/rfq/upload takes RFQ_Flow inputs (BOM + VOLUME + optional Gerber); docs/MCP/bifrost.md calls RFQ_Flow "the platform's currently fully-operational routing profile" (2026-09-28). So RFQ_Flow does NOT run in 3.4 yet: it needs (1) the profile choice above (env var or per upload type), (2) an RFQ_Flow profile + registry rows named in the manifest style (3.3's are Bifrost-style, e.g. intake-scan_local_file; live rows not available here), (3) the data plane: bom_storage.duckdb schema for distributor/gerber, and the hardcoded Windows bom_storage path in duck_db_api.py / hitl_router.py, (4) distributor-pricing and gerber-integration run end to end (not done), (5) the hitl_required handling noted above. Default left: Standard_BOM_Flow.
- Step 3, upload HTTP trigger (RFQ-UPLOAD-1, profile Standard_BOM_Flow, compose service upload-server newly started: it was in docker-compose.yml but not in the running stack). Needed one compose change, in 684183b: upload_server records the ABSOLUTE path of each upload (/app/fastapi-router/staged/inbox/...) and the tool containers must read that same path, but each container had its own filesystem, so every upload would have been invisible to scrub-intake/intake. Now one named volume `inbox` at that path for all Python services (proved below: the files saved by upload-server are listed from inside the scrub container). Driver (not in the repo): POST /api/rfq/upload (SCRUB BOM + volume) -> HTTP 200 {"telemetry": {"dify_pipeline_status": "TRIGGERED"}}; upload-server log `[TEMPORAL SUCCESS]: Workflow 'rfq-RFQ-UPLOAD-1' started` (started by upload_server itself, not by the Temporal client); at the scrub gate POST /api/rfq/upload/quotewin -> 200, then POST /api/rfq/{id}/hitl/decision -> 200; at resolve_final_selection POST /api/rfq/{id}/final-selection (empty resolutions) -> 200 signal_delivered true. Result: workflow COMPLETED (history length 67), steps_executed 8, all `success` (standardize_costing_sheet `skipped` by design: no costing sheet); 2 WorkflowExecutionSignaled events; final rfq_process_stage 8, hitl_required false; 0 `TOOL FAILED` lines for the RFQ in the router log; cbom 897 rows (same as RFQ-E2E-6, so no regression from the NULL-MPN rebuild); export_reports wrote a 21-worksheet workbook. Telemetry rows hold /app/fastapi-router/staged/inbox/... paths. Non-fatal noise: rfq-memory ingest trigger refused (rfq-memory not in this stack). The e2e JWT secret is a 17-byte placeholder (PyJWT InsecureKeyLengthWarning); the real secret must be longer.
- Commit 684183b's message says the upload run is "in the next commit"; no further code change was needed, so this record is the evidence.
