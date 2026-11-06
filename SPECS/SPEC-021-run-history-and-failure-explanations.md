# SPEC-021: Run history in the right pane, and plain-words failure explanations

Status: implemented and proven live 2026-11-06 (see handoff/HANDOFF-2026-11-05.md section 9.14 for evidence and what is NOT verified: Run again, a run reaching Passed). Added during the build: a "waiting for review" status from the workflow's hitl_state query, and a failed-run notice plus Failed status in the header pill and stage list. Reference pattern only (not code, not brand): the right pane of Harish's PFMEA screenshot has a "Workflow | History" toggle; CAM 3.4 keeps its own name and look.

## I - Instructions
1. The right pane of an opened RFQ gets a Workflow | History toggle. History lists every pipeline run of that RFQ, newest first: who started it, when, passed / failed / running / stopped, how long it took.
2. A failed run says WHY in plain words and what to do: wrong or missing input file ("Invalid input"), a missing setting (currency rate), or a tool error. A wrong file is never offered "Run again" (it would fail the same way); it says what to upload.
3. A run that can sensibly be repeated offers "Run again" (the same resume path the left pane uses, no new write path).

## S - Source
- Facts, from the logs of this stack (2026-11-06): every failed workflow of the last 72 h failed in the first stages because the uploaded file was not what the step needs: `standardize_scrub_bom` needs a sheet named `SCRUB BOM` (uploaded: `BOM`, `Sierra Sample BOM`); `standardize_quote_win` found no QuoteWin file / no header row; `export_reports` had no active INR -> USD rate. One older failure was a missing `xlrd` (already fixed in requirements.txt and the running scrub-intake image).
- Temporal already keeps the facts (workflow id `rfq-<rfq_id>`, every run kept on re-start because the id is reused with TERMINATE_EXISTING): start time, close time, status, and the failure text raised by `workflow.py` ("<tool> failed: <error>").
- The upload service verifies JWTs that carry only `rfq_id` (no user): who ran a workflow is NOT in the token.

## A - Automation (decisions)
- Source of truth: Temporal visibility for `WorkflowId = "rfq-<id>"`. No new table, no new store.
- Who: the start paths record `started_by` in the workflow MEMO. The web sends the signed-in user's display name in an `X-CAM-User` header (self-reported by the app until `/auth/token` carries a real identity, handoff 9.7); the assistant's confirmed start sends "CAM assistant (confirmed in chat)". Runs started before this change show "unknown".
- Statuses shown: running, passed, failed, stopped (rejected at a human gate), replaced (terminated because a new upload started a new run), cancelled.
- Failure classification is a pure function of the failure text (`run_history.classify_failure`): `invalid_input` (missing sheet, no file, no header row), `configuration` (no conversion rate), `tool_error` (everything else). Each yields a title, a one-line cause, and the next step; the raw text stays available in a details line.
- Rerun is offered for `configuration` and `tool_error` only; for `invalid_input` the card says to upload the right file (a new upload starts a new run).
- The pane refreshes every 5 s while a run is running and when History is opened; no new SSE event.

## T - Tech stack
Allowed: upload_server.py route `GET /api/rfq/{rfq_id}/runs` (same JWT as `/api/dify/start`), `temporal_worker/client.py` (memo on start), new `fastapi-router/run_history.py`, web `RunHistory.tsx` + `lib/runHistory.ts`, a toggle in `App.tsx`. Not allowed: a new database table, a new SSE event, changes to the routing manifests, anything in `docker-*` / `mcpjungle-server`.

## V - Variables
- Last 20 runs per RFQ; failure text shown trimmed to 400 characters; poll 5 s while any run is running.
- Duration = close time - start time (running: elapsed so far, shown as "running").

## O - Output
- `GET /api/rfq/{rfq_id}/runs` -> `{rfq_id, runs:[{run_id, status, started_at, closed_at, duration_ms, started_by, failed_step, failure:{kind,title,cause,next_step,raw}|null, can_rerun}]}`.
- History view: one row per run (status badge, started, duration, started by); a failed row expands to the cause and next step, with "Run again" or "Upload the right file".

## N - Non-goals / limits
- Per-stage timings inside a run are not shown (activity-level history is a later step).
- `started_by` is self-reported by the app; it is not an audit identity until the token carries one.
