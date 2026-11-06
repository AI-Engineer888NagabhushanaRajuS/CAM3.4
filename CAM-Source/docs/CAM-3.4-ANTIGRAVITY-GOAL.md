# Antigravity `/goal`: Finish CAM 3.4 with Proof

Paste this entire document into Antigravity `/goal`. Work only in `C:\CAM[3.4]-RFQ_centum\CAM-Source`. The architecture/file map is `docs/CAM-3.4-MEGA-GUIDE.md`; read it at startup. The workspace parent also contains `HANDOFF-2026-11-03.md`, the CAM running-stack note, `SPECS/`, and root instructions; use them as described below.

## Mission

Finish the remaining CAM 3.4 work end to end, including a real user-driven browser run from RFQ creation through final exported results. Continue working autonomously until every acceptance item is proven or a specific external blocker is reached. Fix visible or functional problems encountered in the flow, retest the owning slice, and rerun the complete UI flow. Do not claim completion based on code intent, API-only checks, HTTP 200, mocked tests, screenshots without interaction, or old session notes.

**Mandatory final UI proof:** one uninterrupted screen recording of the entire real browser session, from before the first interaction through all final results visible in the right/output pane and an exported workbook opened/checked. The user explicitly requires human-like browser interaction, a full-duration recording regardless of runtime, and automatic UI repair if anything looks wrong. Never substitute stitched clips or stop recording during waits/HITL.

## Hard boundaries

- CAM 3.4 / Centum RFQ only. Do not inspect or modify BAM, Triode, SRIM, LightRAG, other workspaces, or `Reference[KT]`; do not build CAM 4 features (code generation, Jinja/AST tool generation, CubeSandbox, FDE platform, Context Engine).
- Preserve existing data, volumes, user changes, and credentials. Never use `docker compose down -v`, delete/migrate a live database, truncate/reset real RFQs, change Keycloak passwords, or print secrets.
- Current 3.4 runtime is Temporal plus direct manifest-based FastMCP routing. Do not reintroduce Bifrost/Jungle/Dify as runtime requirements because of stale names/comments. Keep legacy APIs only when current callers require them.
- Do not guess missing API keys. If distributor vendors or RFQ-memory need unavailable vendor/provider keys, exercise to the boundary, record exact evidence, and proceed with other acceptance work.
- No push, force-push, or history rewrite. Make local commits only after tests/review. Do not checkout a different branch with uncommitted changes.
- The current source may have uncommitted changes from earlier agents. Inspect/review and preserve them; don't reset or overwrite them.

## Boot and truthful state

1. Read `docs/CAM-3.4-MEGA-GUIDE.md`, `SPECS/handoff/HANDOFF-2026-11-03.md` (repository root), `SPECS/TODO-3.4.md`, `SPECS/progress.json`, and the active SPEC for the next task. When docs conflict, prefer current code + diagrams and record the conflict. Do not re-read long material already summarized in the state below unless new evidence contradicts it.
2. Inspect `git status --short`, branch, recent commits, Compose project labels, live listeners, and ignored-file rules. Do not expose `.env` values. Before any service restart/build, identify the already-running Compose project and exact override files; don't accidentally create a second project or use another project's ports/volumes.
3. Run a focused baseline test and then the full suite before final commit: `python -m pytest -q -p no:cacheprovider` from `CAM-Source`. Record fresh output; repair pre-existing failures only if in current scope.
4. Maintain this file's **Current State** section below as the single persistent goal ledger. Update only after a milestone has evidence or a blocker is proved. Each update records status, evidence path/command, next action, and retry budget remaining. Don't append speculative progress or rewrite the acceptance rules. At startup and after context loss, reread this section and continue at the first incomplete gate.
5. Keep `SPECS/progress.json`, the relevant SPEC, and the ledger consistent; never mark complete from intent. Preserve commits already on the branch. The local `master` branch is established and checked out, synchronized with `feat/cam34-verification` at the source/docs commits recorded in Current State. Continue on the current branch; do not recreate or switch branches with a dirty worktree. Future commits are local only; do not push or rewrite history.

## Work order

### Gate A: Reconcile changes and repair backend correctness

- Review every modified/untracked file and its diff. Determine which are intended CAM changes. Keep `.env`, secrets, recordings and generated outputs out of Git.
- Re-run intake duplicate-import and workflow resume regressions; inspect each test against real payload shapes. Use non-empty result assertions.
- Run focused tests for the changed code, then full backend pytest. Fix currency refresh, manifest macro-category mapping, resume guard, UI workflow-stage/progress behavior only if the current diff/tests establish a defect.
- Resolve the live `system_skills_registry` error with read-only schema inspection first: determine which DB the UI/router connects to, whether the table exists, and whether it has expected rows. Compare seed SQL, registry importer, routing profile, and manifest tool names. Do not apply a schema/registry write to a live DB without a safe isolated path and verified plan.
- Check that Compose frontend endpoint overrides target host-published ports, daemon callbacks target the reachable host, shared inbox/database/export paths are consistent, and Temporal worker can reach the router. Rebuild only the active CAM project with its real overrides and `--no-deps` for targeted services; verify image IDs/timestamps afterward.
- Prove exact routing profile, real tool sequence, direct manifest resolution, and FastMCP response. Do not mix Standard_BOM_Flow and RFQ_Flow assumptions; confirm which profile this deployment uses and ensure upload-selected profile is honored. If RFQ_Flow behavior is required by the handoff but missing, implement with tests and document the default.

### Gate B: Close remaining flow gaps

- Profile selection per upload, correct honoring of `hitl_required`, environment-based BOM storage paths, QuoteWin/costing upload availability only at the real wait gate, correct resume signaling, no duplicate workflows, final-selection UI mapping, stage status freshness, and real export/download all need source tests plus live behavior evidence.
- Verify chat separately. If RFQ-memory/OpenRouter is unavailable, the UI must show a clear non-fatal unavailable state; do not fake a successful AI answer. Identify and fix any wrong relative URL/auth/proxy path only after tracing the current daemon/client route.
- Exercise distributor pricing to its live API boundary. Do not fabricate vendor success if DigiKey/Mouser/Element14 credentials or access are missing.
- Do not start dynamic recalculation blindly. Treat SPEC-018 as a separate guarded track. First build a golden parity harness comparing a LibreOffice-recalculated oracle with generated workbook cells. Review license and formula coverage. Keep the engine behind a feature flag/separate branch or implementation boundary until parity and full-flow regression pass. If this cannot be safely completed overnight, record the precise designed/proven status and do not call it done.

### Gate C: Real UI recording and repair loop

1. Identify a genuine desktop/browser recorder that can record continuously for the full run. Verify target, audio/display choice, output path and available disk space. Do a short recorder probe **before** the acceptance take if possible, and keep it outside source control. If no recorder is available, mark this gate blocked; screenshots are supplementary only.
2. Verify backend health and frontend/daemon endpoints before starting a fresh RFQ. Start evidence capture before opening the acceptance page/first interaction. Recording must remain continuous while files upload, Temporal waits, the user acts at HITL, and reports render.
3. Use a fresh unique RFQ and interact with the real UI as a human would: login, create RFQ, select profile if offered, choose BOM and volume files, upload, watch progress, wait for the in-app intake gate, upload QuoteWin/costing, click Continue, wait for final-selection review, make a selection, complete remaining stages, view all results in right pane, export/download, open/check workbook. Do not call HITL/upload APIs directly to simulate user actions.
4. Capture milestone screenshots and browser console/network evidence alongside the continuous video. Save test RFQ ID, Temporal workflow ID, start/end UTC time, Vite/daemon versions, active Compose project, recorder filename/duration, and the final export path. Redact tokens/cookies and private BOM fields from separate logs; never edit the continuous master recording to hide a failure.
5. If any control, stage, modal, progress event, or result pane looks wrong, stop acceptance, preserve the recording as a failed attempt, identify the owning file, make the smallest fix, run its focused test, and start a **new complete take with a new RFQ**. Never splice old and new segments.

## Anti-loop and stop rules

- Maximum **2 targeted repair cycles per distinct defect**, and maximum **3 complete E2E attempts total**. A retry must change a specific hypothesis and have a discriminating check; repeating the same command/fix does not count as progress.
- Before any retry, write the defect, evidence, hypothesis, change, test, and remaining attempt count to Current State. After the test, update it immediately.
- After the second failed focused repair or third failed end-to-end attempt, stop. Do not spin another `/goal` cycle. Preserve logs/recordings, state the root-cause evidence, what is proven, and one concrete next action.
- Stop before any destructive DB/volume action, credential reset, secret disclosure, unapproved third-party upload, or cross-project change. Use isolated test data and confirmed authorization.
- Never wait indefinitely for external services or agent reports. Use bounded health checks/timeouts; if a required credential/approval/tool is absent, mark that item blocked and continue independent work.

## Completion gates

Mark the overall goal complete only when all applicable items are evidence-backed:

- Current reviewed source tree passes full Python suite, UI-specific tests/typecheck, and relevant Temporal workflow tests. All skips/xfails are explained.
- Active runtime has healthy Postgres, Temporal, worker, router, upload, HITL, bridge, and needed MCP services. Manifest route and selected DB/profile are proven against the actual running container config.
- Real UI run completes every user-visible step through final exports. HITL is initiated and resolved in the UI, and the same durable workflow resumes.
- Right/output pane displays every expected stage result and final artifacts; downloaded workbook opens and has expected sheets/data.
- One uninterrupted full-duration screen recording proves the entire acceptance run. Screenshots, console/network evidence, IDs, timestamps, and export are saved in a dated evidence folder excluded from Git.
- Any visible issue found was fixed and fully rerun within the attempt budget. No unresolved console/network error is hidden.
- Specs, `SPECS/progress.json`, this ledger, and commits agree. A final code review was performed. No credentials/data artifacts were committed.
- SPEC-018 is either safely complete behind its gate with golden parity proof, or explicitly marked blocked/deferred with design and evidence; never mislabel it as complete.

## Current State (mutable evidence ledger)

Last updated: 2026-11-03 after local commits and master setup.

| Work item | Status | Evidence / known state | Next action |
|---|---|---|---|
| Source audit/docs | Committed | `docs/CAM-3.4-MEGA-GUIDE.md` and this prompt; commits `60c80e5` and `522eafd` | continue to remaining flow work |
| Existing source changes | Tests partly passed | backend `200 passed, 4 skipped`; web typecheck passed; web unit `371 passed`; web integration `57 failed, 96 passed` with missing daemon callback mock and stale brand assertions | isolate/fix integration failures relevant to current CAM UI, then rerun affected tests |
| Live DB registry | Blocked/unverified | earlier browser console reported `system_skills_registry` missing; cause/DB target not yet proven | inspect live schema read-only and profile rows |
| Full browser E2E | Not passed | earlier session proved login/reachability, not full UI flow; earlier handoff reports partial run to final-selection gate | run complete flow using fresh RFQ |
| Continuous recording | Not done | no full recording evidence found | check recorder capability and disk before acceptance |
| RFQ memory/chat | Blocked | prior runtime note says service/key unavailable; no successful chat proof | verify env presence without printing value; otherwise record provider boundary |
| NetBird management | Degraded/reported | management container had empty URL validator error; local mesh IP worked from same machine | inspect only if needed for access; do not touch unrelated platform config |
| SPEC-018 recalculation | Proposed | formula parity/oracle must come first; see guide and SPEC-018 | keep isolated; design + parity first |
| Branch/commit | Complete for this handoff | `master` is checked out; `master` and `feat/cam34-verification` point to the same committed source/docs tip; worktree was clean after branch creation; no push performed | continue the CAM goal on current branch |

At every checkpoint, replace only the relevant row with current dated evidence and add newly discovered blockers. When resuming after compaction, read the guide and this table, inspect git status, then continue with the first incomplete item. Do not restart completed stages unless new evidence invalidates them.

## Final report format

Keep the final report concise but complete: overall pass/blocked; test command and exact totals; browser flow checkpoints; recording filename, duration and evidence directory; workflow/RFQ IDs; unresolved blockers and credential boundary; commits/branch; any claims not verified. Do not say “complete” if any mandatory acceptance item is missing.