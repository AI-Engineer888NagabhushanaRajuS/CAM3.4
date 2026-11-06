# CAM 3.4 complete memory transfer, 2026-11-05 (written because the session hit its limit)

Text only. Read in this order: (1) this file, (2) `HANDOFF-2026-11-05.md` (state, do-next list, gotchas), (3) `SPECS/SPEC-019-conversational-assistant.md` (his newest requirement in ISATVON). Full raw conversation: `C:\Users\ADMIN\.claude\projects\C--CAM-3-4--RFQ-centum\106fb1c7-c5f6-41c9-91e2-9f566e0bacb6.jsonl`. Repo: `C:\CAM[3.4]-RFQ_centum\CAM-Source` (`[3.4]` is a wildcard in PowerShell and Python glob).
Status words: DONE = built and checked; PARTIAL = built, not fully proven or not finished; NOT DONE = nothing built; OPEN = decision or data missing.

## A. Every prompt from Harish, in order, with what happened

Earlier part of this session (from my compaction summary; exact words in the raw transcript):
1. "so there r 50,000 Formulas in the Disguise of the Python scripts [ CORRECT ? ] ..." plus: run the browser, dynamic recalculation, "waiting for ur fix on the cam3.4 in total".
   - Question answered (DONE): a real export has 27,664 to 34,095 formula cells but only about 316 distinct column formulas, 57% cross-sheet. 
   - Dynamic recalculation (SPEC-018): NOT DONE (design workflow `wf_20c4b7d6-79a` was stopped with no results; only the parity harness `testing/formula_parity_oracle.py` exists).
   - Full end-to-end browser run (upload, every button, evidence): NOT DONE (only the assistant pane was driven in the browser this session).
2. "3.3's Dify_DMR_RFQ_Flow.yml hardcodes RFQ_Flow ... i hav 3.3 running in other system !! ... FUCK & RUN ONLY 3.4 no 3.3": DONE as a rule (memory `feedback-run-only-3-4`). Followed all session.
3. "ok stop & giv handoff": DONE (HANDOFF-2026-11-03.md, then this one).
4. "ya build the fucking 3.4 & run it man !!": PARTIAL. `scripts/run-cam34.ps1` built (status works; the full `-Build` failed once on container DNS, DNS works again, `-Build` NOT re-run). Stack is running. The script's host launch uses `Start-Process -WorkingDirectory` which fails on the `[3.4]` path: NOT fixed.
5. "OK ITS COMPLETELY FUCKED NOW U TAKE RESPONSIBLITY" with the other CLI's report (exports without cached values; Batchwise Cashflow 16 #VALUE!; SPEC-018 engine not built; "continue on ur work"):
   - Exports store values: DONE (commit 6159cf8; 34,095 of 34,095 on a fresh real export today).
   - Batchwise Cashflow `#VALUE!`: NOT reproduced (0 error cells on takes 23, 24 and today's export), not fixed, OPEN.
   - SPEC-018 engine: NOT DONE.
6. "ALSO SEE THE FUCKING MIDLE PANE ITS SUPPOSED TO BE ASSISTANT UI WITH ALL ASTHETIC ... JUST BY ONE PROMPT THE THING IS LITERALLY CLOSING CHAT ... THIS AI MUST BE HAVING ACCESS TO ALL THE RESULTS ... WITHOUT HALUSINATIONS": PARTIAL. Built: persistent polished assistant pane, grounded answers (evidence first, verifier, citations, refusals), 397 web tests + 46 daemon chat tests + 24 evidence tests pass. Live in the real UI the composer stayed after the answer, but the only live answer was the evidence-only fallback (local model timed out at 120 s). A verified model answer has NOT been seen live yet. Also this prompt's wish for access to "all results" is only served for one RFQ at a time today.
7. The RUNNING-STACK.md prompt ("Y DID U REMOVE ALL ... ADD IT BACK", credentials, links, bugs, file paths, commands; the "Known boundaries" objection; "I TOLD TO ADD OPENROUTER API IN SETTINGS"): DONE (file restored in full + Update 2026-11-05 sections; wrong claim removed; the assistant reads the OpenRouter key from Settings on every question, local qwen3:8b is the fallback). PARTIAL: its status section still needs the final refresh (4.9 of the handoff).
8. "USE ADVISOR OR CREATE A OPUS 5.5 SUB AGENT & ASK IT FOR GUIDANCE": DONE (advisor twice, Opus planning agent; this context two more Opus sub-agents).
Messages in this context (after the compaction):
9. Two pasted HTML blocks (the "HIIII" task messages and the home composer with the "+" menu and "Auto" chip) + "THE FOLLOWING FUCKOFF JUST AFTER 1ST MSG" (the composer vanishes after the first message): DONE in the middle pane: the assistant is now persistent and uses the same `TaskInputBar` composer. The old one-shot task launcher is no longer rendered (files kept). The Execution page itself (task detail) was not changed.
10. Same message: "ALSO ADD THESE FOR ME https://github.com/AI-Engineer888NagabhushanaRajuS/BAM-full-ui- ... POPUP TO SELECT & REJECT THE FILES && ... CONTINUE OF THE 2 SECURITY ENGINES & ALSO COGNEE ... FOR THE MEMORY & CONTEXT ... DONT USE THAT UI ... SKIP SOW GENERATION":
    - Repo cloned and read: DONE. 
    - Select/reject popup (`AttachFilesDialog`): PARTIAL (built, 7 unit tests; NOT driven with real files in the real UI).
    - Two security engines (BuLL*Sav = real ClamAV, Repel Shield = real heuristics, fail-closed): DONE at API level by sub-agent B with live proof (EICAR quarantined, injected csv and macro xlsx quarantined, clean files released, engine-down held); NOT driven through the UI. The pipeline's own "Scan for virus" step is still ClamAV only (decision open).
    - Cognee in the assistant backend: PARTIAL. rfq-memory-server runs; daemon wired (memory retrieve, remember turn, `RFQ_MEMORY_CHAT_URL=http://localhost:18108`); attachment ingest hook exists. Sub-agent A (id a24d0960604ec6351) has NOT reported; end-to-end ingest then retrieve with real numbers is unconfirmed.
    - The screenshot in that message showed his RFQ-00001 failing at SCRUB: `Missing optional dependency xlrd` for his `.xls` BOM: PARTIAL. xlrd pinned and installed by A, scrub image rebuilt; A's real `.xls` proof and how to retry his RFQ-00001: not received. RFQ-00001 itself was NOT retried.
11. "BULLMQUOTE ?? THATS IS COMPANY ORIGINAL WELL CAM IS FOR CENTUM SO MAKE IT CAM3.4": DONE (tab title and every BuLLMQuote logo replaced by a text mark "CAM 3.4"; tab verified "CAM 3.4").
12. The pasted MCP page "THIS IS MY MCP CONNECT TO IT & DO THE DEVELOPMENT": PARTIAL. Connected (`nagabhushana-personas`), used `run_agent_panel(design-review)` and the personas Kyojuro and Corvex, split sub-agent work with disjoint file ownership (his multi-agent-handoff method). NOT run: panels bug-hunt, code-review, explain-codebase, full-council; recipes ui-review, code-fix, portfolio-evidence. The closing code-review panel I planned was not done.
13. Org instruction (always): "build advanced app, best UI in the world, research competitors, then clone repos": PARTIAL. BAM repo cloned; no explicit competitor research for the assistant UI this session.
14. Newest prompt: "PUTTING THIS LAME HARDCODED METHODOLOGY IS BULLSHIT SO NORMAL CHAT ... FETCH THE RFQ ID'S & OPEN POPUP ... ALL CONTEXT BUTTON ... CONFLICT ... CHOOSE ANY ONE OR ASK TO EXPLAIN ... UPLOAD A FILE & ask it self to use the app & create rfq ! ... strong play right & mcp" (screenshot: "HAI HOW TO USE THIS TOOL ?" answered "No relevant context found for this RFQ."). That screenshot was taken at 3:24 PM, before the daemon restart at 3:26 PM, so it shows the OLD daemon; his complaint about canned answers still stands for any question without an RFQ. All of it is NOT DONE:
    - normal conversational chat, how-to answers: NOT DONE
    - RFQ id popup with "All context" button, multi-RFQ context: NOT DONE
    - conflict and confusion prompts (choose one / explain): NOT DONE
    - upload a file then the assistant creates the RFQ itself (with confirmation): NOT DONE
    - Playwright and MCP: NOT DONE (not even researched)
15. Same prompt: "convert this prompt into isatvon format & do the code fix example": the ISATVON conversion is DONE (`SPECS/SPEC-019-conversational-assistant.md`). The code fix (the build) is NOT DONE. https://app.isatvon.ai/ was not used (optional).
16. Same prompt: "whatever ur doing + this + anything in ur memory put them in handoff now ur hitting session limit": DONE (`HANDOFF-2026-11-05.md`, SPEC-019, `progress.json`, memory files).
17. This prompt: "some prompts u didnt even process ++ some process u stopped in middle so type all those !! complete share the memory & all complete mem transfer": this file and the chat reply.

## B. Processes I started and did not finish (or that are still running)
1. SPEC-019 build Workflow (phases: scout, build, verify, fix, close): designed, contract file written (`accomplish-ui/apps/daemon/src/rfq-chat/rfq-chat-contract.ts`), NOT launched. Owners planned: daemon routing/guide/scope, web picker/confirmation/chips, actions (create-RFQ + audit), latency fix, Playwright MCP scout.
2. Sub-agent A (Cognee memory + xlrd), id `a24d0960604ec6351`: launched, no report received. Transcript: `C:\Users\ADMIN\AppData\Local\Temp\claude\7486ebe725f7dd84\106fb1c7-c5f6-41c9-91e2-9f566e0bacb6\tasks\a24d0960604ec6351.output` (large JSONL: read only the tail).
3. Ollama latency probe, background task `b01nemf9v` (script `...\scratchpad\ollama_probe.py`): no output yet when last read. It compares evidence 9000 chars / ctx 12288 against 4500 / 8192 and 4500 / 6144 on the real prompt.
4. A verified (non-fallback) live answer in the real UI: not achieved; first live question timed out at 120 s (qwen3:8b on a Quadro M4000 8 GB).
5. Attach flow in the real UI with real files (clean xlsx, docx/pdf, EICAR, injected csv): not done.
6. Commit: NOTHING from this session's chat, UI, scan, Cognee or rebrand work is committed (master HEAD 6159cf8, local; about 24 modified + 26 untracked entries). `database/cognee_data/` needs a `.gitignore` entry.
7. python-bridge image rebuild from final source (the running container has a hand-copied newer `chat_evidence.py`).
8. `scripts/run-cam34.ps1`: Start-Process wildcard fix, rfq-memory-server in the core list (A may have done the latter).
9. `MessageCitation['sourceType']` in `accomplish-ui/packages/agent-core/src/common/types/task.ts` lacks `'attachment'`.
10. Clean test data: Cognee datasets RFQ-SCANTEST (and RFQ-MEMTEST) via `POST http://localhost:18109/internal/memory/reset`; attachment folders in the inbox volume.
11. `CAM-3.4-RUNNING-STACK.md` final refresh (bugs 12-15 statuses, assistant, attachments, secrets).
12. Memory graph update: done in this transfer (entity "CAM 3.4 session 2026-11-05").
13. Re-export old RFQs so their workbooks store values: only RFQ-CENTUM-PROOF-24 was re-exported (new file `CBOM_Report_RFQ_CENTUM_PROOF_24_20261105_095516_07d4b828.xlsx`).
14. Unused legacy modules `rfq-chat-prompt.ts`, `rfq-chat-heuristic.ts` (kept with tests; delete only when he agrees).
15. Failing tests not caused by this work: daemon `cli.test.ts` (2, Windows paths), `task-service-parity.test.ts` (5, expect the OpenCode agent path that `startTask` never reaches at HEAD).
16. Impeccable audit: done and fixed; left standing: gradient text on the login heading (`pages/auth-shared.tsx` 174-176), shell not mobile-friendly at 390 px, `/impeccable init` (PRODUCT.md) not created.
17. Old open items: Batchwise Cashflow `#VALUE!`; `system_skills_registry` console error; `/auth/token` unauthenticated; `import_bom` ignores "already exists"; distributor and gerber end to end; Superset analytics (credentials); RFQ_Flow profile; New Supp rule.
18. The daemon was restarted by me at 15:26: everyone must press "Sign in as Tester" again. This is done, not pending, but his open Chrome tab needs a reload.

## C. Live state snapshot (2026-11-05 about 15:50 IST)
- Host: daemon :9334 (new build, `.run\daemon.log`), Vite :5181, Ollama :11434 (qwen3:8b), no OpenRouter key saved, no model selected.
- Docker `cam-e2e`: postgres, temporal, temporal-worker, fastapi-router, hitl-router, upload-server, python-bridge (ClamAV, attachments, evidence), reporting (LibreOffice), intake, scrub-intake, gerber, distributor, rfq-memory-server (:18108 chat, 127.0.0.1:18109 internal).
- `CAM-Source\.env` secrets were placeholders that did not match the running stack; fixed (placeholders in `.run\env.placeholder.bak`). Rule: never print the secret, compare md5 prefixes.
- Where the dev logins and credentials are: `CAM-3.4-RUNNING-STACK.md` (restored in full) and `SECRETS.md`; the daemon `.env`.

## D. Memory dump, verbatim

### D1. Claude auto-memory folder `C:\Users\ADMIN\.claude\projects\C--CAM-3-4--RFQ-centum\memory\`
MEMORY.md (index):
- [CAM 3.4 handoff 2026-11-05](project_cam34_handoff_2026-11-05.md) — CURRENT state, secrets fix, next steps, SPEC-019; full file HANDOFF-2026-11-05.md
- [CAM 3.4 handoff 2026-11-03](project_cam34_handoff_2026-11-03.md) — older state (superseded by the 11-05 one); rules and wiring still valid
- [Run only 3.4](feedback_run_only_3_4.md) — never test/register/discuss 3.3; it runs on another system; decide and build
- [Show real proof](feedback_show_real_proof.md) — run the real UI in the browser pane; he suspects fake checks; one short report
- [Brand is CAM 3.4](feedback_brand_cam34.md) — UI says CAM 3.4 for Centum; BuLLMQuote/SRIM are Digibull originals, never show them
- [Owner MCP + BAM repo](reference_owner_mcp_and_bam_repo.md) — personas MCP to use while developing; BAM repo = ideas for dual-engine scan, select/reject popup, Cognee

feedback_run_only_3_4.md:
Build, run and verify ONLY CAM 3.4. The 3.3 source (`Reference[KT]`) is raw material to build 3.4 from, not something to check. Never start, register, health-check or write about 3.3 components (MCP Jungle, Dify, Bifrost). Frame every gap as 3.4 work to fix, not as a 3.3 comparison.
Why: On 2026-11-03 Harish exploded ("FUCK & RUN ONLY 3.4 no 3.3") after my report said "3.3's Dify export hardcodes RFQ_Flow" and after I started Jungle's db container and registered tools on it. 3.3 is live on a different machine; the data was given only so 3.4 could be built.
How to apply: Treat `Reference[KT]` as read-only. If a 3.3 file shows what 3.4 needs, say what 3.4 must do and do it. Do not ask him questions he cannot answer: decide, build, record the decision in the SPEC.

feedback_show_real_proof.md:
Prove things by running the real UI in the browser pane and showing screenshots, console and network, not by scripts that call backend endpoints directly. Give one short final report; do not repeat status lists or loop on a goal hook.
Why: On 2026-11-03 he asked to see an end-to-end browser run, every button checked in real time, "so I can see if it really works or it's fake". Earlier e2e runs approved gates by posting to hitl_router from a script, which skipped the UI path where four real defects were then found.
How to apply: For any "does it work" claim about the product, drive the actual UI (Browser pane tools `mcp__Claude_Browser__*`; test login is in apps/daemon/src/test-login.ts). Say plainly when a check used a different path than the user's.

feedback_brand_cam34.md:
The UI brand is CAM 3.4 (client: Centum). "BuLLMQuote" is Digibull's original company product and "SRIM" its engine name; neither is the product name here.
Why: On 2026-11-05 Harish saw the browser tab title "BuLLMQuote" and said it is the company original, while CAM is for Centum, so make it CAM 3.4.
How to apply: Tab title, login page, sidebars, settings header and taglines say "CAM 3.4" / "BOM automation for Centum" (the `BrandMark` component in `apps/web/src/client/components/BrandMark.tsx`). Internal folder and package names (BuLLMQuote-SRIM) stay as they are; only user-visible text changes.

reference_owner_mcp_and_bam_repo.md:
- Owner's MCP: `https://www.mr-nagabhushanaraju-s.engineer/api/mcp`, connected as server `nagabhushana-personas` (tools `run_agent_panel`, `get_avatar_persona`, `list_avatars`, `list_agent_panels`). He said "connect to it and do the development" (2026-11-05): use its methods while building. Panels: design-review, bug-hunt, code-review, explain-codebase, full-council. Recipes: ui-review (Giyu, Mr. Bean, Owlbert), code-fix (Debug Duck, Corvex, Blue-Eyes), multi-agent-handoff (Kyojuro, Corvex, Clawd: disjoint file ownership per agent). They are methods, not extra agents.
- BAM reference repo: `https://github.com/AI-Engineer888NagabhushanaRajuS/BAM-full-ui-` (his README is the explanation). Port ideas only, never its UI (it targets BAM, not CAM): (1) intake popup to select or reject files, then (2) dual-engine perimeter BuLL*Sav (ClamAV) + Repel Shield, fail-closed twin verdict, (3) Cognee for memory and context. Skip SOW generation, ISATVON, Laya judge. BAM's own backend only simulates the scan verdicts, so CAM must scan for real.

project_cam34_handoff_2026-11-03.md:
Full state, next steps and gotchas: `C:\CAM[3.4]-RFQ_centum\HANDOFF-2026-11-03.md`. Summary: branch `feat/cam34-verification` (2 commits); UNCOMMITTED fixes for the real UI path (daemon push, resume of a parked run, supersede on re-upload) with 2 tests in `testing/test_hitl_signals.py` failing until they wait for `hitl_state.awaiting` before signalling; Docker images for router/upload/worker/hitl are stale; no run through the real UI has happened yet; Python Bridge missing from compose. New client requirement (SPEC-018, proposed): change a value and every dependent file/entity recalculates in real time. Measured: one export has 27,664 formula cells but only 316 distinct formula shapes; design panel was stopped before returning. (Later superseded: the branch is now `master`, the UI-path fixes and the Python Bridge are in.)

project_cam34_handoff_2026-11-05.md:
Read `C:\CAM[3.4]-RFQ_centum\HANDOFF-2026-11-05.md` first. State: master @ 6159cf8, local only; chat, UI, scan, Cognee and rebrand work UNCOMMITTED. Daemon :9334 runs the new build; Vite :5181; Docker project `cam-e2e` incl. rfq-memory-server. Root `.env` secrets fixed to match the running stack. Top next steps: (1) sub-agent A's report, (2) local-model latency, (3) build SPEC-019, (4) rebuild images, run all suites, commit locally.

### D2. Knowledge graph (`C:/Users/ADMIN/.claude/memory-mcp/memory.jsonl`, MCP server `memory`), entities as read on 2026-11-05
Entity "CAM 3.4 tooling" (setup):
- MCP servers memory, context7, serena, nagabhushana-personas registered at USER scope in ~/.claude.json on 2026-10-30 (they were wrongly in settings.json before and never loaded). Memory graph file: C:/Users/ADMIN/.claude/memory-mcp/memory.jsonl (MEMORY_FILE_PATH).
- Plaintext creds exist in setup_postgres.ps1 and SECRETS.md - move to env before shipping.
- Credential locations (values deliberately NOT stored here): Harish says postgres, Bifrost and Temporal use one password, with app user solutions@digibull.ai (URL-encoded solutions%40digibull.ai). fastapi-router/.env (git-ignored) holds a different value for the app user in LOGIC_DB_URL and FILE_METADATA_DB_URL, to be confirmed with Harish. docker-compose.yml uses postgres user 'centum', not solutions@digibull.ai.
- SECRETS.md and setup_postgres.ps1 now read credentials from env vars (CAM_PG_APP_USER, CAM_PG_APP_PASSWORD, CAM_PG_SUPERUSER_PASSWORD); the old literal values were removed by SPEC-012.
Entity "CAM 3.4 verified baseline 2026-10-30" (status), the observations in order:
- Run tests from CAM-Source/testing (cd testing; python -m pytest .); deps: pip install -r requirements-test.txt. (Later: pytest.ini at repo root, run `pytest` from CAM-Source root.)
- Result on branch feat/spec-010: 14 failed, 66 passed, 10 skipped; failing groups test_hitl_signals (4), test_posthog_events (4), test_routing (3), test_temporal_workflow (2), test_report_validators (1). Plan: SPEC-011 fix these + tag v3.3-baseline; SPEC-012+ manifest pipeline Lane 1.
- SPEC-012 committed 7791fe1 (feat/spec-012-security): 90 passed, 3 skipped. SQL cannot be parameterized through the remote metadata tool; validators at entry are the guard. Credentials moved out of setup_postgres.ps1 and SECRETS.md; rotation recommended.
- Verified defects 2026-10-30: D1 /pipeline/routing-sequence called a tool that config.get_mcp_url could not route (fixed in SPEC-015 by reading Postgres directly); D2 workflow.py did step['tool_name'] but routing_sequence is an array of strings (fixed in SPEC-015); D4 config.get_mcp_url routed the 4 scrub tools to Intake :8002 instead of scrub :8004 (fixed in SPEC-013 with a tool-to-URL map from manifests).
- Gateway facts: v3.3-baseline used Bifrost for RFQ_Flow and Jungle for Standard_BOM_Flow; this branch replaced both by direct FastMCP calls (SPEC-003). skill_index = integer position in routing_sequence; registry.skill_index cross-references it.
- Local logic_db_2 initially had only currency tables; the registry DDL IS documented in Reference[KT] docs/Database/logic-database.md (system_skills_registry: skill_code PK, skill_index UNIQUE NOT NULL, macro_category_name NOT NULL, ...; quote_routing_profiles: profile_id uuid PK, profile_name UNIQUE). Live data: skills 1-8 = Standard_BOM_Flow, inactive ERP skills at 9, 10.
- SPEC-013 committed fa08813: 118 passed, 3 skipped; scripts/import_manifest.py (check_shape/canonical_hash/store_manifest/register_tools/rollback_receipt/verify_registration/jungle_register_argv), dry-run by default. Test pitfalls: `[3.4]` makes glob match nothing (use os.listdir); `subprocess.run(capture_output)` around `pg_ctl start` hangs on Windows (use DEVNULL); scratch PG fixture with initdb/pg_ctl works with PG 17/18.
- SPEC-013 defaults: no skill_09 adapter (BAM out of scope), no Temporal wrapper, jungle registration = dry-run command only, macro_category NULL. Open decision: appending a 9th tool to Standard_BOM_Flow needs skill_index 9 which the inactive ERP skill holds (renumber or accept index != position).
- 2026-11-02 Harish LOCKED: no CAM 4.x/BAM work, no codegen (Jinja2/AST) in 3.4, no further architecture change; gateway stays direct manifest routing. CAM-3.4-HANDOFF.md holds a text transcription of the 8 diagrams (the CLI cannot see images).
- New verified defects: D5 temporal_worker default router URL localhost:5000 but router listens 5100; D6 compose never sets CAM_MCP_HOST; D7 rfq_memory manifest port 8008 vs service 8108/8109; D8 manage_backend.py health-checks bifrost :8010; D9 upload_server docstring says Dify default but code default is Temporal.
- 2026-11-02: SPEC-015 completed (b21d7d0): clean 8-step run RFQ-E2E-6, stage 8; suite 177 passed, 4 skipped. hitl_router and temporal_worker/client.py bare `import config` collided with fastapi-router/config.py (HTTP 502 on every HITL signal): fixed by loading the temporal config by path. Zero-conflict resolve_final_selection did not signal the workflow: fixed with _signal_resolve_approved(). Test approvals must go through POST /api/rfq/{id}/hitl/decision and POST /api/rfq/{id}/final-selection.
- 2026-11-02: SPEC-016 closed (06db640): chip/badge text switched to text-foreground/80 (contrast 4.35 to 5.4:1). SPEC-017 closed (febef03): scrub mpn nullable; quantity sums dropped NULL-MPN parts: fixed with _with_blank_mpn(); suite 179 passed, 4 skipped; key missing MPN as blank string instead of dropna=False.
- 2026-11-03 (branch feat/cam34-verification): reporting container rebuilt after the NULL-MPN fix. Compose project is cam-e2e; the stack needs POSTGRES_PASSWORD/JWT_SECRET/OPENROUTER_API_KEY exported and `up -d --build --no-deps <service>` so Postgres/Temporal are not recreated. (2026-11-05: root `.env` now holds the working secret values.)
- 2026-11-03 CORRECTION: the Jungle build here has no --transport flag; import_manifest.py jungle_register_argv fixed (2af237e). Do NOT register intake :8002 under centum_intake. (3.3 pieces are off limits now: see feedback-run-only-3-4.)
- 2026-11-03 intake (RFQ_Flow) fixes in 684183b with RED tests: scan_local_file used a hardcoded Windows ClamAV path (now CLAMSCAN_PATH, ClamAV 1.4.3 in the intake image via INSTALL_CLAMAV); its INSERT ... ON CONFLICT could not match the versioned rfq_process_tracking (now UPDATE hitl_required only); import_bom needs bom_storage.duckdb (BOM_STORAGE_DB env), not input_db.duckdb. Verified on RFQ-INTAKE-1: scan CLEAN x2, EICAR INFECTED, import_bom 105 rows.
- 2026-11-03 still open for RFQ_Flow: router checks `hitl` while scan_local_file returns `hitl_required`; import_bom ignores 'already exists'; duck_db_api.py/hitl_router.py hardcode the Windows bom_storage path; distributor/gerber not run e2e; no RFQ_Flow profile in the fixture; no .dockerignore (5.5 GB images).
- 2026-11-03 upload HTTP trigger VERIFIED (RFQ-UPLOAD-1, Standard_BOM_Flow): workflow 8/8, stage 8, export 21 worksheets; needed a shared named volume `inbox` at /app/fastapi-router/staged/inbox. A 200 from /api/rfq/upload alone proves nothing: check dify_pipeline_status TRIGGERED and the log line. OPEN: which routing profile an upload starts (default Standard_BOM_Flow unchanged).
- 2026-11-03 found by reading the UI code: the real UI path was broken although the HTTP e2e was green: no hitl:request push to the daemon, GET /api/dify/start tried to start a 2nd workflow, progress posted to a hard-coded mesh IP, no Python Bridge in compose. Fixes (router CAM_DAEMON_URL + notify_hitl_required, workflow hitl_state query + stale-decision clear, client resume_rfq_workflow + supersede via TERMINATE_EXISTING, upload_server resume flag) with tests test_daemon_push.py and test_temporal_resume.py. (Since committed on master.)
- 2026-11-03 formulas: one 23-sheet export = 27,664 formula cells, 316 distinct shapes, 57% cross-sheet (hub = 7.0 CBOM sheets); SPEC-018 (dynamic recalculation, proposed) in SPECS/progress.json; design workflow wf_20c4b7d6-79a stopped with no agent results.
Entity "SPEC-011 done 2026-10-30" (status): branch feat/spec-011-baseline-repair; commits 8ac819a (old WIP) + 0b57095; 87 passed, 3 skipped; tag v3.3-baseline -> 4c090da. Root causes: flat config.py collisions (fixed by conftest _isolate_source_dir), mock activities needed @activity.defn, fastmcp 3.4.2 has no _tool_manager (use await mcp.list_tools()). Follow-ups: parameterize rfq_id SQL in bom_qa_lookup_server.py:137; move plaintext creds; progress.json was invalid JSON (fixed).
Relations: "CAM 3.4 tooling" supports "CAM 3.4"; "CAM 3.4 verified baseline 2026-10-30" and "SPEC-011 done 2026-10-30" are status_of "CAM 3.4"; "CAM 3.4 scope decisions 2026-10-30" is decision_for "CAM 3.4" (that entity is referenced but was not returned).
Added in this transfer: entity "CAM 3.4 session 2026-11-05" with the facts of sections A to C.

### D3. Project and user instruction files in force (not memory, but they steer behaviour)
- Organization instruction (always): build advanced apps, best UI in the world, research competitors and copy/trace the best, research latest tools and OSS, clone repos without asking, just build.
- `C:\Users\ADMIN\.claude\CLAUDE.md` (global): at session start call memory MCP `search_nodes` with the project name and read the project CLAUDE.md; call context7 before library/framework code; use serena in large unfamiliar codebases; use the personas MCP panels (explain-codebase, bug-hunt, code-review, full-council; persona Mr. Bean = smallest solution); Impeccable hooks fire on UI edits and `/impeccable audit` must be run before reporting UI work done; write architectural decisions to the memory MCP; ponytail mode (YAGNI, stdlib first, shortest diff); production-grade UI.
- `C:\CAM[3.4]-RFQ_centum\.claude\CLAUDE.md` (project): CAM = Claude Automation Module for Centum, version 3.4 is an incremental upgrade of 3.3; do NOT build CAM 4; read `Eng_Diagram\` first (source of truth), `Reference[KT]\Full Details\`; stack: Electron `accomplish-ui`, React+TS, `packages/agent-core`, Dify orchestration (3.3 only), FastMCP router, MCP servers (calendar, gmail, whatsapp, gerber-integration, bom-processing, distributor-pricing, rfq-memory, reporting), Postgres, Docker + Kubernetes; no generic AI UI; memory MCP for decisions; no abstractions not needed by 3.4.
- `accomplish-ui\CLAUDE.md`: pnpm workspaces; no `electron` imports in the daemon; `.js` extensions in agent-core and daemon; braces on every if/for; no nested ternaries; new files under 200 lines; reuse `components/ui`; tests are workspace-scoped (`pnpm -F @accomplish/web test:unit`, `-F @accomplish/daemon test`); never remove features.
- Harness commit rule: end commit messages with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`; commit only when asked or when already authorised (earlier local commits were accepted); never push.
