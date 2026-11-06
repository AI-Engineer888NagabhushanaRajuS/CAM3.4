# SPEC-014 — Parity harness (Temporal call-trace vs the recorded Dify contract)

**Status:** completed (offline harness; live parity opt-in). **Branch:** feat/spec-014-parity-harness (from feat/spec-013-manifest-pipeline). **Depends on:** SPEC-013.

## Context
HANDOFF §3.6 step 10 and §7 migration step 4: prove Temporal before cut-over. HANDOFF §5: Dify is RETIRED, not installed, not run. No live services exist in this session (no Docker, no Postgres, no router on :5100).

Reference: `Dify_DMR_RFQ_Flow.yml` from the reference copy at commit `a8c0cbd` (3.3 baseline). Used as a frozen record of call order only:
- Code 1 slices `routing[skill_index:]`.
- Iteration posts `/tool/execute` with body `{tool_name, arguments:{rfq_id}}`.
- Code 4 reads `hitl`; IF/ELSE true posts `trigger-hitl`, then HALT ON HITL.

## Scope
- Offline call-trace parity (always runs): real `RFQWorkflow` in the time-skipping env with recording activities, fed string routing (the real shape). Calls must match the recorded order up to the HITL gate; the workflow must be RUNNING (parked) at HITL.
- Live parity tests moved behind explicit `CAM_PARITY_LIVE=1` (no import-time HTTP probe).
- Stage test corrected: compares the endpoint's `postgres_stage` with `get_active_version` (see D3).

## Acceptance
- Full pytest from CAM-Source: all green, skips only the 3 live tests, xfails only the defects below.

## Tests
- `test_offline_trace_parity_dify_vs_temporal` — was strict xfail for **D2**; the xfail was removed in SPEC-015 once D2 was fixed (the test now passes). Before the fix it failed by the 30 s timeout: Temporal retries the failed workflow task.
- `test_routing_sequence_reads_db_not_gateway` — was strict xfail for **D1**; removed in SPEC-015 (now passes).
- 3 live tests — skipped unless `CAM_PARITY_LIVE=1`.

## Decisions / conflicts (recorded, not silently resolved)
- **Routing fixture:** tool names are copied from `manifests/*.json`. No seed dump of `quote_routing_profiles` exists in the repo, so this is a FIXTURE, not production data.
- **Profile conflict:** the Dify YAML requests profile `RFQ_Flow`; the live test and the Temporal client default use `Standard_BOM_Flow`. Not resolved here; SPEC-015 must pick one (open question for Harish).
- **D3 (new, for SPEC-015):** `/rfq/{id}/status` returns `postgres_stage`, but the value is `get_active_version()` (a version number). Field name is wrong.
- **Expected post-HITL divergence (by design, SPEC-005):** Dify halts; Temporal waits for the `human_decision` signal.
- **Not run:** `/code-review` (HANDOFF §8 rule 5) was not run on this diff. Recorded as skipped; run before merge.

## Out of scope
Live Dify/Temporal comparison (Dify retired). `trigger-hitl` in the Temporal path (unverified whether a UI notification is still needed; OPEN, for SPEC-015).

## Verification
```
pytest -q -rxs --tb=short -p no:cacheprovider   (from CAM-Source)
123 passed, 3 skipped, 2 xfailed in 44.99s
```
