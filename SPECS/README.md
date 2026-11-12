# SPECS: the work orders

CAM 3.4 is built with **agile, spec-driven development**: one specification is one work order, written before the code, with its context, scope, acceptance criteria and tests. Where a specification is written in the ISATVON form it carries I (instructions), S (source), A (automation), T (tech stack), V (variables), O (outcome) and N (notification, assumptions and open items).

The machine-readable state is [`progress.json`](progress.json). This page is the human index.

## The specifications

| SPEC | Title | State | Notes |
|---|---|---|---|
| [001](SPEC-001-baseline-and-test-infra.md) | Baseline pin and test infrastructure | completed | tag `v3.3-baseline` |
| [002](SPEC-002-report-validation-layer.md) | Fix the 16 reports, add a per-tab validation layer | completed | |
| [003](SPEC-003-manifest-alignment.md) | Manifest and code alignment (one manifest per FastMCP tool) | completed | |
| [004](SPEC-004-temporal-workflow-engine.md) | Temporal workflow engine (replaces the Dify router) | completed | |
| [005](SPEC-005-hitl-temporal-signals.md) | Human-in-the-loop through Temporal signals | completed | |
| [006](SPEC-006-assistant-chat-pane.md) | RFQ assistant chat API and UI pane | completed | |
| [007](SPEC-007-security-temporal-default.md) | Security fixes, Temporal as the default | completed | |
| [008](SPEC-008-chat-memory-shadowrun.md) | Chat through rfq-memory, shadow-run parity | completed | |
| [009](SPEC-009-posthog-tab-alerts.md) | PostHog per-tab failure alerts | completed | |
| [010](SPEC-010-assistant-ui-chat.md) | assistant-ui runtime and a domain-aware chat pane | completed | |
| [011](SPEC-011-baseline-repair.md) | Baseline repair: green test suite, honest status | completed | |
| [012](SPEC-012-security-sql-and-credentials.md) | SQL hardening, credentials moved to environment variables | completed | test logs in `test-logs/` |
| [013](SPEC-013-manifest-pipeline.md) | Manifest pipeline: importer, registry writer, manifest-owned routing | completed | |
| [014](SPEC-014-parity-harness.md) | Parity harness (Temporal call trace against the recorded Dify contract) | completed | offline harness; live parity is opt-in |
| [015](SPEC-015-cutover.md) | Cut-over completeness: defects D1 to D9, HITL by signal end to end | completed | the upload HTTP trigger was proven offline only |
| [016](SPEC-016-ui-chat-audit.md) | Chat pane audit and fixes | completed | the first browser run was not done then; later specs proved the UI live |
| [017](SPEC-017-bug-hunt.md) | Bug hunt | completed | `cbom_vl` layout deferred (latent) |
| 018 | Dynamic recalculation: a changed value recalculates every dependent file | partial | no separate file; the proposal is in [`TODO-3.4.md`](TODO-3.4.md); the value-edit with regeneration was built under SPEC-020 |
| [019](SPEC-019-conversational-assistant.md) | Conversational assistant: normal chat, RFQ picker, All context, file upload, create an RFQ | implemented, proven live | OpenRouter / Local switch included |
| [020](SPEC-020-manifest-editor-and-dynamic-propagation.md) | Manifest editor (Monaco) and dynamic propagation of edits | implemented, proven live | |
| [021](SPEC-021-run-history-and-failure-explanations.md) | Run history in the right pane, plain-words failure explanations, tracking by user | implemented, proven live | |
| [022](SPEC-022-intake-dashboard-and-manifest-diff.md) | Intake dashboard (Uppy, auto-sorted file roles, animated scan) and the manifest change view | implemented, proven live | |
| [023](SPEC-023-input-preflight-and-chat-files.md) | Input pre-flight, fix in place, files in the chat, manifest-driven left pane | implemented, proven live | report auto-download now proven live (SPEC-025 section 6) |
| [024](SPEC-024-repository-rearrangement-and-publication.md) | Repository rearrangement, duplicate merge, document polish, publication | done | log of every moved and merged file: [`SPEC-024-rearrangement-log.csv`](SPEC-024-rearrangement-log.csv) |
| [025](SPEC-025-manifests-drive-the-pipeline.md) | Manifests drive the pipeline (`enabled` switches the routing table), the pane order (`sequence`) and its buttons (`ui_actions`) | implemented, proven live | skills with no tool in the registry (02, 03, 04, 05) only change the pane; all tests green; not committed |

[`TODO-3.4.md`](TODO-3.4.md) is the running list of what is still open.

## Other folders here

| Folder | What it holds |
|---|---|
| [`handoff/`](handoff) | **Session history.** The handoff notes of the agent sessions (newest first in the table below), the running-stack and login notes, the memory transfer, recipes for creating an RFQ and for the Playwright MCP, the old session log, and `original-notes/` with the verbatim rough notes that were rewritten for publication |
| [`spec019-scout/`](spec019-scout) | Notes written while scouting SPEC-019 |
| [`test-logs/`](test-logs) | Full pytest logs of SPEC-012 to SPEC-017 |

### The handoff notes

| File | Read it for |
|---|---|
| [`HANDOFF-2026-11-05.md`](handoff/HANDOFF-2026-11-05.md) | The newest and fullest state: rules from Harish, what was built and proven, gotchas. **Read section 9 first** |
| [`HANDOFF-2026-11-03.md`](handoff/HANDOFF-2026-11-03.md) | The earlier state and the original to-do list (its status parts are superseded by the 2026-11-05 file) |
| [`CAM-3.4-HANDOFF.md`](handoff/CAM-3.4-HANDOFF.md) | The architecture diagrams transcribed as text, what replaced what, install notes, the verified defects D1 to D9 |
| [`CAM-3.4-RUNNING-STACK.md`](handoff/CAM-3.4-RUNNING-STACK.md) | Every URL and port, how to start and stop everything, login notes |
| [`MEMORY-TRANSFER-2026-11-05.md`](handoff/MEMORY-TRANSFER-2026-11-05.md) | What the agent's memory held at the end of that session |
| [`create-rfq-recipe.md`](handoff/create-rfq-recipe.md), [`playwright-mcp.md`](handoff/playwright-mcp.md) | Step-by-step recipes |
