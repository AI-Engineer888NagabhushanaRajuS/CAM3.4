GOAL: Finish CAM 3.4 end to end, spec by spec, driven ONLY by the diagrams and docs in this repo. Find and fix bugs on the way. Never guess; every claim you make must point to a file, a diagram, or a test output.

## 0. Boot (do first, every session and after every compact, ~5 tool calls max)
0. Read C:\CAM[3.4]-RFQ_centum\SPECS\handoff\CAM-3.4-HANDOFF.md FIRST: text transcription of all diagrams (you cannot see images), what replaced what, install/setup, verified defects D1-D9, locked decisions (no CAM 4, no codegen, no further architecture change).
1. Call memory MCP `search_nodes("CAM 3.4")` (if the tool is missing, read C:/Users/ADMIN/.claude/memory-mcp/memory.jsonl directly).
2. Read C:\CAM[3.4]-RFQ_centum\SPECS\progress.json -> the next unfinished spec is your task.
3. `git -C CAM-Source status --short` and `git log --oneline -5`. Dirty tree = finish or commit it before anything else.
4. Run `pytest` from CAM-Source root. Baseline is 87 passed, 3 skipped, 0 failed. Anything else = fix first.

## 1. Source of truth (priority order, higher wins on conflict)
1. `Eng_Diagram [ Must follow ]\` : 8 images + the interactive HTML ("CAM 3.4 architecture with manifest pipeline"). Read the HTML once (its text, not as an image) and record its component list in memory.
2. `Reference[KT]\DOMAIN KNOWLEDGE\`, `Extras\` (4 Encyclopedias, 2 RE docs), `Full Details\`. Read these before writing domain logic (reports, ABC class, MOQ, price control, ISATVON manifests). Summarise each into memory ONCE; never re-read a file you already summarised.
3. `SPECS\SPEC-0xx-*.md` : your work orders. 4. `CAM-Source\` : the code. 5. `SPECS\handoff\old-session.jsonl` : history only, grep it for a keyword, never read it whole.
Upstream repo hint from Harish: github.com/solutionsDigibull/CAM. Do NOT install or build `accomplish-ui` beyond what already exists. Do NOT build CAM 4 (Jinja2/AST codegen, CubeSandbox, Context Engine, FDE mode are the 4.0 track).

## 1b. Scope + hygiene (hard)
- Scope is ONLY CAM 3.3 -> 3.4 (Centum RFQ). Other projects on this machine (BAM, Triode, AOI, FE-*, LightRAG, RAG...) are out of scope: do not read or touch them.
- `Reference[KT]` is READ-ONLY. NOTE: its BuLLMQuote-SRIM copy was contaminated by the old agent (it has SPEC-001..003 commits, a manifests/ dir and untracked accomplish-ui). Treat it as unreliable for "what 3.3 looked like"; use `git -C CAM-Source show v3.3-baseline:<path>` instead. Never write there.

## 2. What is already true (verified 2026-10-30, do not redo)
- SPEC-001..011 are committed; branch feat/spec-011-baseline-repair; tag v3.3-baseline -> 4c090da. Suite green (run from CAM-Source root).
- Done per the 3.4 migration path: baseline, 16 reports + per-tab validators, 6 manifests in `manifests/`, Temporal workflow + HITL signals, chat pane, PostHog tab alerts.
- Known real defects: (a) fastapi-router/bom_qa_lookup_server.py:137 f-string SQL with raw rfq_id; (b) plaintext creds in setup_postgres.ps1 and SECRETS.md; (c) manifest rule (diagram, migration step 3): ONE manifest per REAL tool, derived from code. The "10 manifests" in the diagrams are BAM-side docs (family b) and are NOT files you must find; the 6 in CAM-Source/manifests are the runtime set. Verify each manifest matches its tool's real name/inputs/outputs in code; (d) 3 shadow-run parity tests are skipped because services are not running.

## 3. Work queue (in this order; one spec = one branch = one commit; branch from the previous spec)
- SPEC-012 Security: parameterize rfq_id SQL everywhere an f-string builds it (grep `rfq_id` inside f-strings in fastapi-router, mcp-tools, temporal_worker); move all credentials to env vars + `.env.example`; make SECRETS.md/setup script read env; add tests with a hostile rfq_id (`CE-1'; DROP TABLE x--`).
- SPEC-013 Manifest pipeline, Lane 1 of the last diagram: adapter + validator (manifest JSON -> strict shape), importer service (validate, hash, store), then the BRIDGE: registry writer (one transaction: INSERT system_skills_registry + append tool to quote_routing_profiles.routing_sequence, idempotent, keep old value for rollback), gateway registration (Jungle; keep Jungle, Jungle-vs-Bifrost is OPEN so default to Jungle and note it), parity test in staging. Manifests = one per real tool, taken from code (not from a list); do not look for or invent a "10 manifests" file.
- SPEC-014 Parity harness: run Dify path and Temporal path on one test RFQ and diff outputs; un-skip test_shadow_run_parity with a docker-compose profile or a recorded-fixture mode that needs no live services.
- SPEC-015 Cut-over completeness: START with defects D1, D2, D5, D6, D7 from HANDOFF section 7 (failing test first), then: HITL by signal end to end, Dify call sites removed or behind a flag, upload_server starts the Temporal workflow, Temporal persistence location decided (default Postgres; record the decision).
- SPEC-016 UI: chat pane + progress; run `/impeccable audit`, fix findings; verify in a real browser run (use the `run` skill), screenshot.
- SPEC-017 Bug hunt: `bug-hunt` panel from nagabhushana-personas on temporal_worker/, fastapi-router/, mcp-tools/reporting/. Every finding needs a failing test first, then the fix.
Before starting each spec: if no SPEC file exists, write it first (Context, Scope, Acceptance, Tests, Out of scope) using the diagram text as the acceptance criteria.

## 4. The loop (repeat per spec; stop the loop only on a Section 7 condition)
PLAN: read only the files the spec touches (use serena `find_symbol` / `find_referencing_symbols`, not grep-walks). For any library API (temporalio, fastmcp, fastapi, duckdb, assistant-ui), call context7 for the INSTALLED version first (fastmcp 3.4.2 removed private `_tool_manager`; trust the installed package over memory).
RED: write the failing test that encodes the diagram's exit check.
GREEN: smallest diff that passes (ponytail rules: reuse > stdlib > installed dep > new code; no speculative abstractions).
VERIFY (all must be pasted as real output, never summarised from memory): full `pytest`; for UI, a browser run; for Temporal, the time-skipping WorkflowEnvironment test.
COMMIT: `feat(SPEC-0xx): ...` + trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`; update SPEC status + progress.json (keep it valid JSON, forward slashes in paths); add 2-4 observations to memory (`add_observations`).
REVIEW: run `/code-review` on the diff at medium; fix confirmed findings in the same spec.

## 5. Anti-hallucination rules (hard)
- Do not state a port, table, endpoint, env var, function, or file exists unless you opened it this session or a tool output shows it. Say "unverified" otherwise.
- "Done" requires pasted passing test output. Never mark a spec complete from intent. The previous agent marked 10 specs complete with 14 failing tests; do not repeat that.
- Diagram labels: SOURCE = exists in code, PROPOSAL/MISSING/OPEN = not built or undecided. Only OPEN items may be defaulted, and each default is written to the SPEC and to memory.
- If the diagrams and a doc disagree, the diagram wins; log the conflict in the SPEC.
- If something needed is not in the repo or docs (credentials, a decision, a missing manifest list), ask Harish once with a concrete default. Do not fabricate.

## 6. Credit discipline
- Never re-read a file you have summarised; never dump whole logs: `| tail -30`, `grep -n`, `--tb=short -q`.
- Run the whole suite once per loop iteration, targeted tests while iterating.
- Parallelise independent reads in one message; use at most 2 subagents (Explore for read-only sweeps), never for a lookup you can do in 3 calls.
- Keep context small: after each spec commit, write state to memory + progress.json so a compact loses nothing. Re-boot per Section 0 after any compact.
- No new dependencies unless a diagram requires them. No refactors outside the spec.

## 7. Stop conditions (then report in 10 lines: done / failing / blocked / next)
- All of SPEC-012..017 committed with green suite; OR a needed decision/credential is missing (ask once); OR the same test fails after 3 distinct fix attempts (stop, report root-cause evidence, do not thrash); OR you are about to delete data, force-push, or touch anything outside C:\CAM[3.4]-RFQ_centum.
Final report must include: pytest summary, commits per spec, remaining OPEN items with chosen defaults, and anything you could not verify.
