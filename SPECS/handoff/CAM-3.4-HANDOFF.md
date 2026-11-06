# CAM 3.4 HANDOFF (text-only; the CLI cannot see images)

> **UPDATE 2026-11-03: read `HANDOFF-2026-11-03.md` (same folder) FIRST for current status, rules and next steps.**
> This file's sections 5-7 (status, defects D1-D9) are STALE: most are fixed. Its section 3 (diagram transcription) is still valid.
> Also: Harish's rule is **3.4 ONLY**. Any mention of Jungle/Dify/Bifrost here is history, not work to do.

> Written 2026-11-02. Read this FIRST every session and after every compact, then GOAL_PROMPT.md.
> Sections 3-4 are a text transcription of the 8 diagrams in `Eng_Diagram [ Must follow ]\`.
> Section 5-7 are VERIFIED facts about the code (opened/ran this session) unless marked "unverified".
> If this file and a diagram disagree, the diagram wins; log the conflict in the SPEC.

## 1. Mission and locked decisions

- **CAM 3.3 is the live system. We build ONLY the 3.4 delta.** "3.4" is not defined in any code or doc; it is the migration plan in the diagrams.
- **Locked by Harish (2026-11-02):**
  1. **No CAM 4.x work.** BAM (Next.js/Keycloak/Temporal build platform, Jinja2+AST codegen, CubeSandbox, Context Engine, FDE mode) and the removal of `accomplish-ui` are the 4.0/4.1 architecture shift. Do not read, build or copy it.
  2. **No codegen in 3.4** (no Jinja2/AST generation, no LLM slot filling). Manifests in 3.4 DESCRIBE hand-written FastMCP servers (code -> JSON). The BAM manifests are the reverse (JSON -> code) and are 4.x.
  3. **No further architecture change for 3.4.** Keep what is already built (Temporal swap, manifest-driven direct tool routing, chat pane). Remaining work = make it actually run, prove parity, finish the cut-over, audit the UI, hunt bugs.
  4. Gateway: **direct FastMCP calls routed by manifests** stays as built (interpreted from "no more changes"; ask Harish only if Jungle must come back). Jungle registration exists only as a dry-run command.
- Do NOT: install/build `accomplish-ui` beyond what exists; touch BAM/Triode/other projects; delete data; force-push; write outside `C:\CAM[3.4]-RFQ_centum`.

## 2. Diagram legend (chips on every box)
SOURCE = exists in inspected code. STUB (registered) = registered but body is a stub. DOC = documented only. REPORTED = told, not verified. PROPOSAL = the 3.4 plan, not built. OPEN = undecided (only OPEN items may be defaulted, and every default is written to the SPEC and memory). MISSING = does not exist. UNCHANGED / CHANGED / NEW / REMOVED = delta vs 3.3.
Line styles: solid = wired call, dotted blue = documented, dashed orange = proposed, dotted red = missing bridge.

## 3. The diagrams as text

### 3.1 System design (diagram 1)
**CAM 3.3 runtime (Centum-side host)** - SOURCE unless noted:
| Component | Port / detail |
|---|---|
| web_frontend (Accomplish-fork UI, Vite) | :5180 |
| upload_server | :3000 in diagram (code: 3100). POST /api/rfq/upload*, GET /api/dify/start/{rfq} |
| hitl_router | :5002 in diagram (code: 5102). final-selection saves, resume |
| fastapi_router | :5000 in diagram (code: 5100). /tool/execute, /pipeline/routing-sequence |
| accomplish daemon | :9234. SSE skill-progress, hitl:request, internal trigger-hitl |
| Dify workflow "DMR" (Docker) | :80 /v1. Orchestrator: routing sequence, iteration, HITL halt |
| MCP Jungle | :8080/mcp. Gateway, tools named like `centum_reporting__cbom` |
| scrub_mcp_server | :8004. FastMCP scrub/intake |
| reporting_mcp_server | :8005 in diagram (code: 8105). FastMCP, 6 reporting tools |
| bom_qa_lookup_server | :8006. FastMCP BOM QA |
| python_bridge | :3010. DuckDB HTTP bridge |
| DuckDB | 4 input tables per rfq_id + 16 report tables |
| Postgres logic_db | :5432. routing profiles, skills registry, HITL state |
| Ollama | :11434. LLM header mapping on upload/standardize only |
| Apache Superset | :8088. reporting UI |
| PostHog cloud | project 577674. product analytics |
| Hardcoded secrets in source | OPEN (Dify key, DB passwords; SPEC-007/012 moved them to env) |

**BAM build-time platform (OUT OF SCOPE, 4.x):** Caddy, Keycloak :8080, sbam-web :3000, tusd :1080, ClamAV, sbam-api :8000, PostgreSQL 16, Temporal :7233 (+UI :8233), 6 workers, Cognee + OKF, Bifrost :8081 (LLM gateway), codegen modules (STUB), gates/tests/certify (STUB), Langfuse/ClickHouse/Grafana LGTM, CubeSandbox on KVM host, backup host. Do not touch.

**4.0 target / 3.4 plan zone:** manifest importer + skill registry loader (MISSING), Temporal as runtime orchestrator (PROPOSAL = 3.4), Bifrost-or-Jungle at runtime (OPEN), assistant chat API + pane (PROPOSAL = 3.4), FDE/Project mode, Context Engine + Pydantic AI harness (DOC, 4.x), "16 reports fixed in place" (PROPOSAL = 3.4).

### 3.2 Architecture by layer x generation (diagram 2)
| Layer | CAM 3.3 runtime (SOURCE) | 3.4 plan (PROPOSAL) | 4.0 target (DOC, ignore) |
|---|---|---|---|
| Experience | Accomplish-fork UI :5180 + daemon :9234, SSE progress + HITL | Add assistant chat pane (chat API did not exist) | FDE/Project mode |
| Orchestration | Dify DMR workflow: start, routing-sequence, iterate tools, IF/ELSE, HITL halt | Dify -> Temporal swap, rebuilt from the Dify YAML (3 calls + loop); run both on one test RFQ | Temporal runs frozen manifests |
| Gateway / tool plane | fastapi_router :5000 + MCP Jungle :8080 (routing gate, version key, progress notify, MCP 2025-11-25) | Keep POST /tool/execute; Jungle vs Bifrost OPEN | Bifrost + FastMCP |
| Tool implementation | FastMCP servers :8004 :8005 :8006 + DuckDB bridge :3010 (6 reporting tools, standardize_*, BOM QA) | Fix 16 reports in place; align 10 manifests to code; settle "one tool one manifest" vs six tools | manifest -> Jinja2+AST codegen |
| LLM + context | Ollama (header mapping); no gateway; LLM only in upload/standardize | Unchanged | Pydantic AI + Cognee/OKF |
| Data | Postgres logic_db + DuckDB | Pin the 3.3 baseline from real git history (OPEN) | PostgreSQL 18.6 + context graph |
| Observability + ops | PostHog cloud + Superset :8088 | Per-tab report checks + PostHog failure alerts | Promptfoo, NetBird |

### 3.3 Workflow manifest -> tool (diagram 3) - BAM side, OUT OF SCOPE
Documented FDE four-stage flow (Ingestion, Context, Workbench, Validation), BAM build chain (build_manifest -> check_libraries -> render_skeleton -> generate_bodies -> assemble -> ast_gate -> static_gate -> generate_tests -> build_promptfoo_suite -> run_sandbox_tests -> certify; correction loop; WAIT_RETRY). Bottom row, the BRIDGE from a certified manifest to a callable CAM tool, is entirely MISSING: importer -> deploy FastMCP server -> register in Jungle -> skills registry + routing profile (OPEN) -> Dify/Temporal picks it up. Today the manual path is: developer writes the code, manifest is written afterwards. **3.4 decision: manual path stays.**

### 3.4 Internal calling for ONE RFQ (diagram 4) - the 3.3 call graph (SOURCE)
1. UI uploads BOM / QuoteWin / costing (multipart POST). 2. upload_server `POST /api/rfq/upload*` saves files, writes DuckDB/Postgres. 3. `trigger_dify_workflow_internal` (dedupes recent trigger) POSTs Dify `/v1/workflows/run`. 4. Dify Start (rfq_id). 5. Dify HTTP Request: GET routing-sequence. 6. Router `GET /pipeline/routing-sequence/{rfq}/{profile}`. 7. Jungle initialize + notifications/initialized (Mcp-Session-Id; tool postgres_logic__execute_sql). 8. `SELECT routing_sequence FROM quote_routing_profiles`. 9. Dify Code then Iteration "DMR": one pass per tool in the sequence. 10. Dify HTTP Request 2: `POST /tool/execute {tool_name, arguments{rfq_id}}`. 11. Router /tool/execute (plain def, threadpool, sync up to 300 s per tool). 12. Routing gate: `get_all_live_tool_names`, skip disabled tools, `increment_skill_index`, clear HITL. 13. `versioned_key(rfq, active_version)`. 14. `notify_skill_progress` POSTs daemon `:9234/api/internal/emit-skill-progress`, SSE to UI. 15. `tools/call` over MCP. 16. FastMCP tool runs (cbom, generate_reports, export_reports...). 17. DuckDB queries + writes. 18. Result envelope; `resolve_final_selection` may need a human. 19. Dify Code 4 + IF/ELSE on `hitl_required`. 20. Dify HTTP Request 3: POST daemon `/api/internal/trigger-hitl`. 21. SSE `hitl:request` to UI. 22. **HALT ON HITL: the Dify run ends, no durable wait.** 23. UI `POST /api/rfq/{id}/final-selection` (hitl_router saves decision). 24. `GET /api/dify/start/{rfq}` starts a NEW Dify run (resume). 25. Dify End: Output.

**Proposed Temporal path (replaces ONLY the Dify column):** workflow start(rfq_id) from upload_server; activity `get_routing_sequence` (same GET, or read Postgres directly: OPEN); loop = one activity per tool calling the same `POST /tool/execute` with Temporal RetryPolicy; HITL = workflow waits for a signal sent by hitl_router on the user's decision (no restart); progress = same emit-skill-progress; complete = record to Postgres, audit via workflow history; parity test = run Dify and Temporal on one RFQ; gateway decision = OPEN.

### 3.5 CAM 3.3 vs 3.4 side by side (diagram 5): ten layers, delta
| Layer | 3.3 (SOURCE) | Delta | 3.4 target (PROPOSAL) |
|---|---|---|---|
| Experience | UI :5180 + daemon :9234 SSE | CHANGED + NEW | same UI + chat pane; chat API new |
| Entry | upload_server: upload endpoints, GET /api/dify/start, header mapping via Ollama, dedupes Dify triggers | CHANGED | starts a Temporal workflow instead of a Dify run; credential literals removed, read from env |
| Orchestration | Dify "DMR": Start > GET routing > Iteration > POST /tool/execute > IF/ELSE > trigger-hitl > HALT (only 3 HTTP calls + loop + branch) | REMOVED Dify / NEW Temporal | Temporal workflow, same 3 calls + loop + branch |
| Router + gate | fastapi_router POST /tool/execute (routing gate fails open, versioned_key, notify, call_tool), GET /pipeline/routing-sequence | UNCHANGED | contract preserved; workflow calls it exactly as Dify did |
| Tool gateway | MCP Jungle :8080/mcp | UNCHANGED (decision OPEN) | Jungle stays; Jungle vs Bifrost OPEN |
| Tool servers | FastMCP :8004 scrub, :8005 reporting (cbom, enrich_erp, enrich_costing_sheet, resolve_final_selection, generate_reports, export_reports), :8006 bom_qa, bridge :3010; fastmcp>=3.4.2 | CHANGED | fix 16 reports in place + per-tab checks; align manifests to code |
| Data | DuckDB (cbom.duckdb > reports.duckdb, 16 report tables) + Postgres logic_db | NEW (Temporal store) | same stores + Temporal persistence (location OPEN) |
| Human loop | hitl_router :5002 + Dify HALT; resume = fresh run | CHANGED | workflow waits for a signal; hitl_router needs a Temporal client |
| Analytics + ops | PostHog + Superset | UNCHANGED + NEW | continue; Temporal history adds an audit trail |
| Version + baseline | "3.3" REPORTED, repo = one squashed commit, no tag | OPEN | pin the 3.3 baseline from real history |
Outside CAM scope: BAM manifest shape reused by the CAM manifests (relationship only, no importer).

### 3.6 Call flow 3.3 vs 3.4 (diagram 6) - same RFQ, step by step
| Step | 3.3 | 3.4 | Delta |
|---|---|---|---|
| 1 Start | upload_server POSTs Dify /v1/workflows/run | upload_server starts a Temporal workflow with rfq_id | CHANGED |
| 2 Routing sequence | Dify GET :5000/pipeline/routing-sequence/{rfq}/{profile} | activity calls the same GET (or reads Postgres directly: OPEN) | UNCHANGED |
| 3 Loop | Dify Iteration "DMR" | workflow loop; Temporal RetryPolicy replaces ad-hoc retries | CHANGED |
| 4 Execute tool | Dify HTTP Request 2: POST :5000/tool/execute | activity calls the same POST | UNCHANGED |
| 5 Gate + dispatch | router: gate, version key, notify, MCP tools/call, FastMCP, DuckDB/Postgres | identical | UNCHANGED |
| 6 Branch | Dify Code 4 + IF/ELSE on hitl_required | workflow code branch | CHANGED |
| 7 Ask a human | Dify HTTP Request 3 POST daemon trigger-hitl, then HALT | activity calls trigger-hitl, workflow awaits a signal | CHANGED |
| 8 Human decides | hitl_router saves; resume = GET /api/dify/start (new run) | hitl_router signals the waiting workflow | NEW |
| 9 Finish | Dify End: Output, no durable history | workflow completes, history stored by Temporal | NEW |
| 10 Prove it | no parity harness found (OPEN) | run Dify and Temporal on the same RFQ, compare outputs before cut-over | NEW |

### 3.7 Migration path (diagram 7) - six steps, each with exit check and open question
1. **Pin the 3.3 baseline.** Exit: a tag + file list of what 3.3 contains. Open: who holds the real git history (repo is one squashed commit).
2. **Fix the 16 reports in place.** Per-tab check for each of the 16 reports; keep code in reporting_module, no codegen. Exit: each report tab has a pass/fail check against tracker cases. Open: Tracker Dashboard says 43 issues/13 fixed, Report tab says 14 reported/12 solved - they disagree.
3. **Align manifests with code.** Exit: one manifest per real tool. Open: docs say "one tool one manifest", code has 6 reporting tools and 6 manifests.
4. **Swap Dify for Temporal.** Rebuild the 3-call-plus-loop flow from the Dify YAML; keep POST /tool/execute and Jungle. Exit: Dify and Temporal produce identical output on one test RFQ (parity test). Open: Temporal hosting, persistence, hitl_router signal client.
5. **Cut over and retire Dify.** upload_server at Temporal; HITL by signal; remove the halt/resume route. Exit: HITL works with no restart; Dify no longer called. Open: Jungle vs Bifrost.
6. **Add the assistant chat.** Chat API + pane; reads RFQ status and progress. Exit: chat answers from live RFQ state. Open: scope and permissions.
**NOT part of 3.4:** Jinja2 + AST codegen from manifests (4.0 track).

### 3.8 Architecture with the manifest pipeline (diagram 8)
**Lane 1 - JSON-to-tool pipeline (BAM build side).** Boxes: 1 manifest JSON family (a) [DOC]; 2 adapter + 1.5 validator [MISSING]; 3 importer service [MISSING]; 4 build_manifest + params [SOURCE, in BAM]; 5 Jinja2 render, 6 LLM fills 4 slots, 7 AST + static gate, 8 test + certify [all STUB]; 9 package + deploy FastMCP server [MISSING]. **Bridge into the runtime [all MISSING]:** registry writer (one transaction, INSERT system_skills_registry row + append tool to quote_routing_profiles.routing_sequence, idempotent, keep old value for rollback), gateway registration (Jungle in 3.3; Jungle vs Bifrost OPEN), parity test in staging. "Registry is read fresh on every call" [SOURCE].
**3.4 decision:** Lane 1 boxes 5-9 are 4.x. 3.4 builds only the importer + bridge (SPEC-013, done).
**Lane 2 - CAM 3.4 runtime:** UI + chat pane (PROPOSAL); upload_server starts a Temporal workflow, credentials source -> env (PROPOSAL); Temporal workflow (PROPOSAL); fastapi_router :5000 POST /tool/execute kept (SOURCE); tool gateway (OPEN); hand-written FastMCP servers (SOURCE); generated FastMCP servers (PROPOSAL, 4.x); Temporal store (OPEN); per-skill gate (PROPOSAL); hitl_router sends a Temporal signal, needs a client (PROPOSAL); quote_routing_profiles (SOURCE); system_skills_registry (read by db.py, writer MISSING); Postgres + DuckDB (SOURCE); PostHog + Superset (SOURCE).

## 4. What is replaced with what (3.3 -> 3.4) and where it lives now
| 3.3 piece | 3.4 replacement | Where (verified in repo) | State |
|---|---|---|---|
| Dify DMR workflow | Temporal `RFQWorkflow` | temporal_worker/workflow.py, worker.py, client.py, config.py; task queue `cam-rfq-pipeline` | built; **broken on real data (D1, D2)** |
| Dify HTTP Request 1 (routing) | activity `get_routing_sequence` | temporal_worker/activities.py | **D1** |
| Dify Iteration | workflow `for` loop + RetryPolicy | workflow.py | **D2** |
| Dify HTTP Request 2 | activity `execute_tool` -> same POST /tool/execute | activities.py | ok (contract unchanged) |
| Dify Code 4 + IF/ELSE | workflow branch on `hitl_required`/`hitl==1` | workflow.py | built |
| trigger-hitl + HALT + resume GET | `workflow.wait_condition` + `human_decision` signal | workflow.py, hitl_router.py (sends signal, 2 places), temporal_worker/client.py | built, only "approve" sent; not run live |
| upload_server -> Dify | `temporal_client.start_rfq_workflow`, Dify behind `CAM_USE_TEMPORAL` (default true) | fastapi-router/upload_server.py | built; docstring says default false (wrong) |
| Hardcoded keys/passwords | env vars + `.env.example` | SPEC-007, SPEC-012 | done |
| MCP Jungle / Bifrost gateway | direct FastMCP HTTP, tool -> URL from manifests | fastapi-router/config.py, tool_calling.py | built; **D6 in Docker** |
| Hardcoded DUCKDB_SCOPED_TOOLS/SCRUB_TOOLS | manifest-driven sets | fastapi_router.py `_load_tool_routing_sets` | done |
| Docs-only manifests | 6 manifests, validator, importer, registry writer | manifests/, scripts/validate_manifests.py, scripts/import_manifest.py | done (SPEC-013) |
| Dify run history | Temporal workflow history | compose: Temporal on Postgres | decision = Postgres (default), record in SPEC-015 |
| (none) chat | chat pane + chat API via rfq-memory | SPEC-006/008/010 | built; UI not audited |
| (none) per-tab report checks | validators + PostHog failure events | SPEC-002, SPEC-009 | built |
**Stays as is:** fastapi_router POST /tool/execute, routing gate, versioned_key, notify_skill_progress, the FastMCP servers, DuckDB/Postgres, accomplish daemon + SSE, PostHog, Superset, Ollama.

## 5. Install and setup (VERIFIED from files; nothing below was run end to end - unverified)
**Machine facts seen this session:** Windows 11, Python 3.12, Docker Desktop installed (docker.exe present; not verified running), PostgreSQL 17 and 18 binaries under `C:\Program Files\PostgreSQL`. Path contains `[3.4]`: never use `glob.glob` on it (matches nothing); use `os.listdir`/`pathlib`.
**Python deps:** from `CAM-Source`: `pip install -r requirements.txt -r requirements-test.txt` (fastapi 0.137, uvicorn 0.49, fastmcp 3.4.2, duckdb 1.5.3, psycopg2-binary 2.9.12, temporalio>=1.7, cognee==1.4.2 PINNED, ollama, pandas, openpyxl, PyJWT).
**Env (copy `.env.example` to `.env`, never commit):** `POSTGRES_PASSWORD`, `JWT_SECRET`, `OPENROUTER_API_KEY` (rfq-memory), `CAM_USE_TEMPORAL` (default true). Native Postgres bootstrap `setup_postgres.ps1` needs `CAM_PG_APP_USER`, `CAM_PG_APP_PASSWORD`, `CAM_PG_SUPERUSER_PASSWORD`. Local services read `fastapi-router/.env` (`LOGIC_DB_URL`, `FILE_METADATA_DB_URL`). Real passwords are NOT recorded anywhere; ask Harish.
**docker-compose.yml services (container port -> host port):** postgres 18 (5432 -> 15432); temporal `temporalio/auto-setup:1.24` on Postgres (7233, 8233); temporal-ui 2.26 (8080); upload-server (3100 -> 13100); fastapi-router (5100 -> 15100); hitl-router (5102 -> 15102); temporal-worker (worker.py); reporting-mcp (8105 -> 18105); intake-mcp (8002 -> 18002); distributor-pricing-mcp (8003 -> 18003); gerber-integration-mcp (8007 -> 18007); scrub-intake-mcp (8004 -> 18004); rfq-memory (8108/8109 -> 18108/18109). **Not in compose:** Dify, MCP Jungle, Bifrost, Ollama (:11434), accomplish daemon (:9234), web frontend (:5180), Superset (:8088), python_bridge (:3010). Those run bare-metal via `fastapi-router/manage_backend.py` or externally.
**Run Temporal worker bare-metal:** `python temporal_worker/worker.py` (needs a Temporal server on `CAM_TEMPORAL_HOST`, default localhost:7233, and the router reachable at `CAM_FASTAPI_ROUTER_URL`).
**Do not install/build:** `accomplish-ui` (pnpm monorepo, node_modules already present), BAM, Dify (retiring).
**Tests:** from `CAM-Source` run `python -m pytest -q -p no:cacheprovider`. Last verified: **123 passed, 3 skipped** (skips = 3 shadow-run parity tests that need live services). Registry-writer tests start a throwaway Postgres (initdb/pg_ctl, temp dir, trust auth, loopback). Windows gotcha: never `capture_output` around `pg_ctl start` (hangs); use DEVNULL. Never kill the user's real PostgreSQL service; only the temp cluster.
**CLI tools:** `python scripts/validate_manifests.py`; `python scripts/import_manifest.py <manifest> [--register TOOL..] [--profile P] [--db-env VAR] [--apply]` (dry-run unless `--apply`; do NOT `--apply` against a real DB without Harish).

## 6. Where we are (verified 2026-11-02, branch feat/spec-013-manifest-pipeline)
Done and tested: SPEC-001..013 (baseline tag v3.3-baseline -> 4c090da; 16 reports + per-tab validators; 6 manifests matching code by AST; Temporal workflow + HITL signals code; chat pane; PostHog tab alerts; SQL/credential hardening; manifest importer + registry writer + manifest-owned routing).
Rough progress vs the 6 migration steps: 1 tag done / history OPEN; 2 built / tracker numbers unresolved; 3 done; **4 built but not working (D1, D2)**; **5 not done**; 6 pane built, UI unaudited. **About half. Green tests are not proof of a working flow: tests mock the wrong shapes.**

## 7. Verified defects and open decisions (fix in the SPEC named; failing test FIRST)
| ID | Defect (evidence) | Owner |
|---|---|---|
| D1 | `/pipeline/routing-sequence` calls `call_tool("Production_Logic_DB-execute_sql")`; `get_mcp_url` finds no manifest tool by that name -> ValueError -> endpoint returns `{"error":...}`. Fix: read `db.get_routing_sequence()` + `db.get_current_skill_index()` directly (diagram step 2 allows "reads Postgres directly"). | SPEC-015 |
| D2 | `workflow.py` does `step["tool_name"]` but `routing_sequence` is a jsonb array of STRINGS; `test_temporal_workflow` mocks dict steps and hides it. | SPEC-015 |
| D5 | `temporal_worker/config.py` default `FASTAPI_ROUTER_URL=http://localhost:5000`; the router listens on 5100 (baseline too). Bare-metal worker calls nothing. (Diagram ports 5000/3000/5002/8005 differ from code 5100/3100/5102/8105: code is truth.) | SPEC-015 |
| D6 | Compose never sets `CAM_MCP_HOST`; config.py builds `http://{one host}:{manifest port}/mcp` (default NetBird IP 100.121.36.255) but each MCP server is its own container with different published ports. Router cannot reach tools in compose. Needs per-manifest host/URL override (env or manifest field). | SPEC-015 |
| D7 | `centum_rfq_memory` manifest says port 8008 but the service is FastAPI on 8108/8109 (not MCP; `tools: []` + `planned_tools` by design). | SPEC-015 |
| D8 | `manage_backend.py` still health-checks `bifrost_gateway` at :8010 although 3.4 does not use Bifrost. Whether it gates startup: unverified. | SPEC-015/017 |
| D9 | upload_server docstring says Dify default; code default is Temporal (comment only). | SPEC-015 |
| D3, D4 | rescan on manifest change; scrub tools misrouted to :8002 | FIXED in SPEC-013 |

**Open decisions for Harish (defaults chosen, change on request):**
- Appending a 9th tool to Standard_BOM_Flow needs `skill_index` 9, held by inactive ERP skill (live data: skills 1-8 = the live sequence; inactive ERP at 9, 10). Default: writer refuses; operator supplies the index (renumber ERP skills, or index 11 with index != position).
- Registry DDL comes from Reference docs `docs/Database/logic-database.md` (past live introspection), not re-verified live: `skill_code` PK, `skill_index` UNIQUE, `macro_category_name` NOT NULL.
- Real git history for the 3.3 baseline; tracker numbers 43/13 vs 14/12; Postgres/Bifrost/Temporal password (`CENTUM@digibull.ai` given in chat, recorded nowhere; confirm username `solutions@digibull.ai`); rotate the old passwords that sat in plain text.
- Temporal persistence: default Postgres (as compose does); record in SPEC-015.

## 8. Rules for the CLI
1. Never state a port/table/endpoint/env var exists unless opened this session; otherwise write "unverified".
2. "Done" needs pasted passing pytest output. Never mark a spec done from intent.
3. One spec = one branch = one commit (+ review fixes), branch from the previous spec, trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Update the SPEC file, `SPECS/progress.json` (valid JSON, forward slashes) and memory after each commit.
4. Test with real shapes (strings in routing_sequence), a real DB where SQL matters, and guard against vacuous passes (assert the list you loop over is non-empty).
5. Run `/code-review` on each spec diff; fix confirmed findings in the same spec; re-report outcomes.
6. Ask Harish ONCE with a concrete default for anything not in repo/docs. Do not fabricate. No credentials in files or chat.
7. Order of work: SPEC-014 parity harness -> SPEC-015 cut-over (start with D1, D2, D5, D6, D7) -> SPEC-016 UI (impeccable audit + real browser run) -> SPEC-017 bug hunt. Details in GOAL_PROMPT.md.
