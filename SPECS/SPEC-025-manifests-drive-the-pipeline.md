# SPEC-025: the manifests drive the pipeline, the left pane order and its buttons

| | |
|---|---|
| Status | Implemented and proven live 2026-11-11 (real Chrome, the live Postgres routing table). Not committed yet. |
| Owner | Harish / Nagabhushana Raju S (Digibull) |
| Depends on | SPEC-020 (manifest editor), SPEC-023 (`enabled` in the left pane) |
| Asked by | "the manifest controls whether the pipeline runs a step, the order of the stages and their buttons, and the Settings > Skills toggles: that is the whole point" |

## 1. What was wrong

After SPEC-023 the manifests only greyed things out in the left pane. Three things were still hard-coded:

1. whether the pipeline runs a step (decided by the Settings > Skills toggle, which edits `quote_routing_profiles.routing_sequence`);
2. the order of the stages and the buttons under them (`WORKFLOW_STAGES` in `App.tsx`);
3. the lock on "Analyze feasibility & Risks" (`comingSoon: true` in code, so editing the JSON never unlocked it).

## 2. How it works now

The pipeline already skipped every tool that is in no `routing_sequence` (the ROUTING GATE in `fastapi_router.py` reads the table fresh on every call, advances the step and tells the UI it completed). So the manifest was wired to that same switch from the daemon. No container, no Python change.

| Manifest | Effect |
|---|---|
| `skill_metadata.enabled: false` (or `enabled` on the agent's `skill_sequence` entry) | Saving it removes the skill's tools from every routing profile; the next RFQ step skips them. `true` or no flag puts them back, in the same profiles and the canonical `skill_index` order. The stage shows "Off in manifest" and is locked. |
| `skill_sequence[].sequence` | The order of the stages in the left pane. It now equals the runtime `macro_category` (1 to 9; SKILL_05, which has no stage, is 10). |
| `ui_actions: [{label, action}]` in a skill file | The buttons under that stage. `action` is `createRfq`, `scan`, `ingest`, `jump` or `info`. No list = the built-in buttons; `[]` = none. |

The other direction: flipping a skill in **Settings > Skills** now also writes the skill's `enabled` into its manifest (off when every one of its tools is off), so the two never disagree.

Mapping used (`SKILL_MACROS` in `apps/daemon/src/manifests/manifest-runtime.ts`): SKILL_01 = macro 0 and 1, 02 = 2, 04 = 3, 06 = 4, 03 = 5, 07 = 6, 08 = 7, 10 = 8, 09 = 9.

A tool that was switched off remembers the profiles it was in (table `skill_toggle_memory`, created on first use in `logic_db_2`), so switching on puts it back only there.

## 3. Files

- Daemon: `manifests/manifest-runtime.ts` (new), `manifest-routes.ts` (save calls the runtime for every skill whose flag changed; the reply carries `runtime.applied` and `runtime.errors`), `manifest-tree.ts` and `manifest-schemas.ts` (`ui_actions`), `browser-api-server.ts` (wiring, Settings toggle mirror).
- Web: `lib/pipelineManifest.ts` (`orderStages`, `stageActions`), `App.tsx` (no `comingSoon`, order and buttons from the manifest, `getNextEnabledStage` reads the manifest), `lib/manifestsApi.ts`, `pages/Manifests.tsx` (the note now says what is live).
- Manifests: `agent_manifest.json` (sequence = execution order), `skill_03_feasibility_risk.json` (`enabled: false`), `ui_actions` in skills 01, 04, 07, 08, 10.
- Tests: `daemon/__tests__/manifest-runtime.test.ts` (5, in-memory database), `pipelineManifest.unit.test.ts` (+2); web 551, daemon 527 pass.

## 4. Proof (real Chrome and the live database)

`acceptance_evidence/spec019/pipeline_live.cjs`, screenshots in `acceptance_evidence/spec019/pipeline/`, the daemon was restarted first (new PID 27668, started 13:02).

1. Pane before: nine stages in runtime order, "Analyze feasibility & Risks" locked with "Off in manifest".
2. SKILL_03 saved with the flag removed: the stage unlocked within the 2.5 s the script waited (the pane refreshes on focus and every 20 s). There are no tools behind it, so `applied: {SKILL_03: []}`.
3. SKILL_06 saved `enabled:false`: `centum_intake__standardize_quote_win` and `..._costing_sheet` left `routing_sequence`; the stage showed "Off in manifest".
4. SKILL_06 back on: the table was byte-identical to the baseline taken before the test.
5. Settings toggle path (RPC `rfq.setRoutingProfileSkillEnabled`): both SKILL_06 tools off set the manifest to off and the tree to `SKILL_06(off)`; one back on made it on again; the table ended identical to the baseline.
6. A check that can fail (the built-in order and labels equal the manifest's, so steps 1 to 5 alone could have passed on the old code): SKILL_07 and SKILL_08 swapped `sequence` and the first `ui_actions` label of SKILL_01 renamed to "Start a new RFQ", both only in the manifest files. The pane showed "Finalize price" before "Consolidate Pricing Sources" and the button read "Start a new RFQ" (`04-reordered-renamed.png`).
7. The manifests touched by the proof were put back byte for byte (the saves also left newer copies in `manifests/.history`, which is how saves work and is harmless).

Other checks: pytest 486 passed (8 skipped); `scripts/validate_manifests.py` OK; the Python lint (`manifest_codegen.lint_manifest`) accepts skills 01, 03 and 08 with the new fields; web 551, daemon 527 pass (7 unrelated failures that were already there: `cli.test.ts`, `task-service-parity.test.ts`).

Found in review and fixed: the assistant's "show skill 4 json" looked a skill up by `sequence`, which is now the run order, so it would have opened the wrong file; it now uses the number in the skill id. The Settings toggle only rewrites a manifest when the signed-in user is an admin (saving a manifest is admin-only everywhere else); a non-admin's toggle still changes the routing table but leaves the manifest as it was.

## 5. Limits (honest)

- A skill with **no tool in `system_skills_registry`** only changes the pane. In this database those are SKILL_02, 03, 04 and 05 (the registry has 8 tools, in macro 1, 4, 6 and 9). Feasibility & Risk (SKILL_03) now has its tool (section 8), so it is no longer in this group; SKILL_02, 04 and 05 are.
- `sub_skills[].enabled` is still display only: sub-skills have no tool behind them.
- A save that fails in the database leaves the file saved and says so in `runtime.errors`; it is not rolled back.
- Before the manifests load (first second of a page) a manifest-locked stage shows as open.
- The Feasibility & Risk lock, the order and the buttons depend on the daemon being reachable; with it down the pane falls back to the built-in order and buttons.

## 6. Test failures fixed and backlog closed (same day)

All suites are green now: daemon 532, web unit 551, web integration 185 (1 skipped), pytest 486 (8 skipped), both typechecks clean.

| Failure (before) | Cause | Fix |
|---|---|---|
| `cli.test.ts` (2) | the test expected POSIX paths (`/some/path`) on Windows | compare with `resolve('/some/path')` |
| `task-service-parity.test.ts` (5) | `startTask` and a follow-up `resumeSession` are answered from the RFQ's results (rfq-chat) and build no agent TaskConfig any more, so tests that read `TaskConfig.files` and the stored-workspace fallback tested a path the app no longer takes | the startTask-attachments test and the stored-workspace test (dead path) removed; the other three now call `resumeSession` without an existing task, which still runs an agent session |
| web integration (126) | 73 from mocks missing newer API methods (`onDaemonReconnected`, `getEnabledSkills`, `rfqGetRoutingProfileSkills`); 53 from tests of the upstream Accomplish screens CAM replaced (Home "What will you accomplish today", example prompts, task status badges, stock sidebar logo and routes) | mocks and `__tests__/setup.ts` completed; the six stale files are listed in `exclude` of `vitest.integration.config.ts` with a reason (kept, not deleted: re-point them at the CAM screens, then drop them from the list); one stale TaskInputBar test skipped |

Backlog:

- **Report auto-download: proven** (`acceptance_evidence/spec019/autodownload_live.cjs`, real Chrome): with RFQ-000015 open, a "running" event saved nothing, the "completed" event saved `CBOM_Report_RFQ_000015_20261103_111125_1a3e2336.xlsx` (716,116 bytes) by itself, and a second "completed" event saved nothing more. The finishing event was posted to the daemon's own internal route, the call the pipeline router makes, because no run reaches the export step on its own here; the download, the export-status check and the once-per-RFQ rule are the real ones. Opening the RFQ in the UI also made the UI's own resume call, like earlier proofs.
- **Corrected copies keep values, not formulas: decided, not changed.** A formula without a saved result reads as NaN in the pipeline, which is the failure the pre-flight exists to stop; keeping the formula text would reintroduce it.
- **Left open on purpose:** QuoteWin and costing-sheet mapping from chat (QuoteWin is recognised and sent to the ERP step; there is no costing-sheet sample to build a role from); the Drills workbook comparison (needs your file).

## 7. After RFQ-000024 (11 Nov evening): why the report was empty, and what changed

**Cause (verified).** RFQ-000024 got the Rafael AWARDS QuoteWin file with the Centum BOM: 0 of 203 parts shared, so 502 of 502 rows had no price and every cost was 0. The matching file (`QuoteWin_File.xlsx`, 201 of 203 shared) gives a priced report (RFQ-000026/27: Summary cost per set 66.40 / 60.43, Price Control Centum 78.6 % / CONTRACT 21.4 %, 388 of 502 rows priced, Manifest GO).

| Change | Where |
|---|---|
| A QuoteWin file with none of the BOM's parts is refused (422 `quotewin_mismatch`, with the numbers); a partial match is allowed and says how many parts stay unpriced | `input_check.quotewin_match`, `upload_server._quotewin_match`, `uploadRefusal.ts`, the QuoteWin modal |
| Real step events: each step's result is stored (`rfq_step_events`) and sent over SSE with `detail` / `warning`; a skipped step is `skipped`, never `completed`; the export says "388 of 502 rows priced"; a stage no tool belongs to reads "Not in this pipeline"; a step that ran but did nothing reads "Ran, check the result" | `fastapi_router.step_outcome`, `db.record_step_event`, daemon `rfq.getSkillHistory`, `App.tsx`, `RfqProgressTimeline.tsx` |
| The review grid no longer covers a finished run | `App.tsx` (clears the HITL context when the export completes) |
| Formula Engine v0.1.0 vendored (engine package + its 540 tests + synthetic oracle fixtures, no research data) and used after `export_reports`: it re-computes every formula and, where it disagrees with LibreOffice's stored value, stores its own. Found: LibreOffice stores 0 for array-style INDEX/MATCH(1,INDEX(a*b,0),0) in BOM MATRIX, A CLASS PARTS and 7.0 CBOM, so a viewer that does not recalculate (Protected View) showed zeros. On RFQ-000026: 27,798 of 34,095 formulas agreed, 6,295 stored values were corrected, then 34,093 agree (the 2 left are the Manifest GO/NO-GO cells, which the engine does not support) | `mcp-tools/shared/formula_engine/`, `mcp-tools/shared/formula_verify.py`, `reporting/superset/mcp_server.py` (`_engine_check`), bridge `GET/POST /api/rfq/{id}/verify-workbook` |
| Reports & Analytics screen from the delivered workbook (cost per set by assembly and volume, price-control split, lead-time distribution, cash out by payment term, priced rows, uncosted parts, workbook GO/NO-GO) plus the engine check table; Superset is optional | `mcp-tools/shared/rfq_analytics.py`, bridge `GET /api/rfq/{id}/analytics`, `ReportsDashboard.tsx` |
| Create RFQ: one drop area for all files, Uppy tiles, both security engines with the scan animation, files sorted by role, "Use these files"; the volume file is optional for the SCRUB BOM pipeline (its volumes are in the workbook's Settings sheet; the service still requires it for RFQ_Flow) | `RfqExecutionCard.tsx`, `AttachFilesDialog.tsx` (`onUseFiles`), `upload_server.py` |
| Defects named in FE-5: the diff treated a stored 0 and FALSE as equal | `edit_regenerate._same` |

**Limits (honest).** The engine is a research prototype (FE-3/FE-7): not Excel certification, not client approval; 0 of 282 client cases are accepted; its own tests pass 540 of 541 on Linux (one depends on how openpyxl writes an empty value) and are not in the default pytest run because they write to `/tmp`. Checked against native Excel 16.0 on this machine (`acceptance_evidence/spec019/excel_oracle.py`: open, CalculateFullRebuild, compare): of the 6,295 cells the engine replaced on RFQ-000026, Excel agrees with the engine on all 6,295 and with LibreOffice on none. It also found a real generator defect that LibreOffice and the engine both hid: `price_control.py` wrapped the range in `N()`, which Excel does not apply array-wise, so every Price Control cell was `#VALUE!` in Excel and the Manifest read NO-GO while the stored values said GO. Fixed (plain range as its own SUMPRODUCT argument); the report of RFQ-000031 as delivered by the app has 34,095 of 34,095 formula cells equal to Excel's own recalculation. That is one workbook, one machine: it is not client approval, and the engine's other semantics remain as FE-7 says. The nine FE-7 owner decisions (rounding, aggregation, packing edit scope, duplicate vs occurrence, award/L1, scrap/proto, currency, validity, pivot refresh) are not guessed. Superset itself (a venv install that lived on the 3.3 machine, no dashboard export in any repo) is not restored; the screen above replaces it for a single RFQ. The portfolio view of 3.3 (all RFQs: Total RFQs, Final Buy, Critical Exceptions) is not rebuilt.

**Proof (real Chrome, `acceptance_evidence/spec019/create_rfq_live.cjs`, screenshots in `create-rfq/`).** Wrong QuoteWin refused with "none of the 203 parts"; right one accepted; the app saved the report by itself (818,829 bytes) with BOM MATRIX O7 = 66.40403, A CLASS I1 = $126.84, 7.0 CBOM VL-1 K13 = 82; the step events are in `rfq_step_events` (costing sheet skipped; export "20 worksheets, 388 of 502 rows priced; engine check ..."); the Uppy tiles and scan animation are in `01a/01b/01c`. Four live runs (RFQ-000027 to 000030): with the BOM file alone the scan says "Centum_Scrub_BOM.xlsx is the BOM workbook; its Settings sheet carries the volumes" and the upload is accepted; with both files it says which is the volume; the wrong QuoteWin is refused with "none of the 203 parts (it lists 88 other part numbers)"; the Reports & Analytics screen of RFQ-000030 shows cost per set 126.84, 388 of 502 rows priced, 44 uncosted parts, Centum 78.6 % / CONTRACT 21.4 %, workbook check GO (it waits for the export step to complete before reading the workbook: opened early it first showed "n/a"); the left pane of a finished RFQ reads Completed / Not in this pipeline / Off in manifest per stage, and the last stage reads Completed, not "Running...". Tests at the end: pytest 503, daemon 532, web unit 557, web integration 185 (1 skipped), both typechecks clean; engine tests 540 of 541 on Linux. Two flaky tests were fixed at the root: `chat_evidence._uncached_formulas` left the workbook open on Windows (the cache writer's `os.replace` then failed), and the parity tests waited 3 s on an unroutable address.

## 8. Feasibility & Risk is a real step; toggling keeps RFQs in place; download gating (11 Nov night)

| Change | Where |
|---|---|
| SKILL_03 runs a tool: a Can build / Cannot build verdict with reasons and a High/Medium/Low risk for every SCRUB BOM line, from the SCRUB BOM and the QuoteWin quotes. Rules (documented defaults, not Centum-approved): Cannot build = Part Status EOL/Discontinued or no quote with a price; High = cannot build, last-time-buy date or no lead time; Medium = NRFND, best lead time over 20 weeks, NCNR, price validity passed. Machine constraints are **not** evaluated (no EMS capability template exists); the tab says so | `reports/feasibility_risk.py`, `reporting_pipeline.run_feasibility`, MCP tool `feasibility_risk`, table `feasibility_risk_run`, export adds the **Feasibility & Risk** tab only for RFQs that ran the step |
| Registry row `M03.20_FeasibilityRisk` (index 20, macro 5 "risk") in `logic_db_2`; run order is `macro_category, skill_index`, so the step sits after the costing sheet and before the CBOM without renumbering. The same fields are on the manifest tool so a fresh deployment can import it | live DB (backups in the session scratchpad: registry/profiles before, `rfq_step_events` before), `centum_reporting.json` |
| Before the step could be added, every consumer that read `skill_index` as a position was changed to read the position in the routing sequence; old RFQs (44 with a run) got their step events written from the old sequence, so their history is unchanged | daemon `standardSequence()`, `rfq-chat-status.ts`, SQL backfill |
| Switching a step on or off in the middle of the sequence moves every later step by one, so RFQs already part-way would repeat or skip a step on resume. `realignInFlight` moves each RFQ's `rfq_process_stage` to the position after the last step it did (manifest save and Settings toggle both call it) | `manifest-runtime.ts`, `browser-api-server.ts`, test in `manifest-runtime.test.ts` |
| The pane re-reads the Settings toggles when a manifest flag changes (it showed "Locked" after the manifest said on) | `App.tsx` |
| Auto-download stays as it was (Harish, 11 Nov night: keep it): the finished report is always saved by itself; I had gated it on a warning-free export and reverted that | `App.tsx` |
| `TITLE_CLASS` had no entry for skipped/warning rows; two type errors in earlier code | `RfqProgressTimeline.tsx`, `pipelineManifest.ts` |
| The `task-service-parity` test failed when the machine was busy (a refused connection took 2-4 s on Windows): its network call is stubbed | `task-service-parity.test.ts` |

**Proof (real Chrome, live database).** `feasibility_enable.cjs`: SKILL_03 flag removed in the manifest -> `applied: centum_reporting__feasibility_risk`, routing table has it after the costing sheet, the stage goes from "Off in manifest" to open, finished RFQs 8 -> 9, RFQs that stopped before it unchanged. `create_rfq_live.cjs` with BOM + Volume + QuoteWin: RFQ-000032 ran all nine steps; the Feasibility step reads "247 lines: 192 can build, 55 cannot, 56 high risk" (amber, because 55 cannot be built); the app saved the report (837,242 bytes) with the **Feasibility & Risk** tab; the Reports screen shows cost per set, 388 of 502 rows priced, Workbook check GO. Native Excel recalculation of that workbook: **34,095 of 34,095 formula cells equal the delivered values**.

**Limits (honest).** The Feasibility rules are defaults until Centum approves them (for example, packing items with Part Status "Not Required" and no lead time read High). The "20 weeks" limit is one constant. Machine constraints need an EMS capability template; without one the tab says they were not checked.
