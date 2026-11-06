# SPEC-017 — Bug hunt (partial)

**Status:** PARTIAL. Sweep done for `temporal_worker/` only. `fastapi-router/` and `mcp-tools/reporting/` NOT swept yet. **Branch:** feat/spec-017-bug-hunt (from feat/spec-016-ui). **Depends on:** SPEC-016.

## Method
Read the code; each finding gets a failing test first, then the fix (GOAL §3). No panel run: the bug-hunt panel would send code to an external MCP, which was not confirmed as wanted; the sweep was done by reading.

## Findings
| # | Where | Finding | Test (RED first) | Fix |
|---|---|---|---|---|
| 1 | temporal_worker/client.py `start_rfq_workflow` | Docstring says idempotent, but a second start of a running RFQ raised `WorkflowAlreadyStartedError` (verified RED). | testing/test_temporal_workflow.py::test_start_rfq_workflow_is_idempotent_for_running_rfq | Catch the error; return the existing id. Added optional `client` param for the time-skipping test. |
| 2 | temporal_worker/activities.py `get_routing_sequence` | Router error body (HTTP 200 + `{"error"}`) passed through as an empty successful run. Found in SPEC-015 review. | testing/test_temporal_workflow.py::test_routing_sequence_error_body_raises_not_empty_success | Raise `RuntimeError`. |

## Still to sweep
- fastapi-router/: e.g. upload_server dedupe, hitl_router signal path, duck_db_api.
- mcp-tools/reporting/: superset queries (many `rfq_lit` sites, escaped via `sql_quote`; SPEC-012 decision).
- Open from HANDOFF/SPEC-013: `scrub`/`intake` routing and `manage_backend` behaviour.

## Verified
`pytest -q -rxs --tb=short -p no:cacheprovider` from CAM-Source: `131 passed, 3 skipped` (skips = live parity tests).

## More findings (sweep 2, fastapi-router + reporting)
| # | Where | Finding | Test (RED first) | Fix |
|---|---|---|---|---|
| 3 | fastapi-router/upload_server.py `start_dify_workflow`, `upload_rfq_file` | Async handlers ran the sync trigger on the event loop; its Temporal branch calls `asyncio.run()`, which raises inside a running loop. Result: CONNECTION_REFUSED, so **no workflow started from the upload endpoints**. (verified RED: "asyncio.run() cannot be called from a running event loop") | testing/test_upload_temporal_trigger.py | `asyncio.to_thread` at both call sites. Covers the GET endpoint; the upload endpoint uses the same call but has no separate test. |
| 4 | temporal_worker/client.py `start_rfq_workflow` | Review: swallowing `WorkflowAlreadyStartedError` reported a new upload version as triggered while the old run continued (workflow ID is per RFQ). | testing/test_temporal_workflow.py::test_start_rfq_workflow_refuses_to_mask_a_running_run | Raise instead. |
| 5 | upload_server.py schema check | Concurrent triggers ran check-then-ALTER on the guard schema. | none (lock) | threading.Lock around `ensure_processing_guard_schema`. |

## Reporting sweep (sweep 2)
Pattern scan only (bare/broad excepts, eval, shell=True) over mcp-tools/reporting, fastapi-router, temporal_worker. The broad excepts in reporting_pipeline re-raise after rollback; `fastapi_router.py:230` falls back on purpose. **No bug confirmed there.** A full read of the ~70 `rfq_lit` sites was NOT done.

## Still open
- Full read of mcp-tools/reporting/superset (queries, exporter) and the rest of fastapi-router (hitl_router, duck_db_api).
- Commits 0e3e8c2, 2284308, 442588b, 4a19dfa, e8a8ae9 are on feat/spec-017-bug-hunt but carry SPEC-012/014/016 fixes (reviewed on this branch; cherry-pick to the original branches not done).

## Sweep 3 (hitl_router, duck_db_api, reporting entry points)
| # | Where | Finding | Test | Fix |
|---|---|---|---|---|
| 6 | fastapi-router/hitl_router.py `hitl_decision` | A failed Temporal signal was logged and the endpoint answered `{"status": "ok"}`. The decision was lost; the workflow stayed parked; the UI showed success. RED verified (returned 200). | testing/test_hitl_decision_signal.py | Returns 502 with the reason. Commit e9a306c. |

Checked, no bug confirmed:
- duck_db_api.py `batch_update_bom` (line ~284): column names come from the `EDITABLE_FIELDS` allowlist; values are bound parameters.
- reporting exporter: output filename uses `helpers.slugify(rfq_id)`.
- reporting SQL sites use `sql_quote` (escaped) per SPEC-012.

Open (not changed; needs a decision):
- hitl_router `submit_resolutions` (~line 357) and `submit_alternates` (~line 608) log a failed approve signal as non-fatal, because `rfq_process_stage` already advanced in the DB. If the signal fails, the DB says the gate passed while the workflow stays parked. Default to record: return `signal_delivered: false` in the response. Not changed here.
- reporting MCP tools (`mcp-tools/reporting/superset/mcp_server.py`, six tools) take `rfq_id` without the entry validation the other MCP servers have. SQL is still escaped; low risk. Not changed.
- NOT read in full: mcp-tools/reporting/superset/queries.py (1,023 lines), reporting_pipeline.py, validator.py, final_selection.py, schema.py. SPEC-017 is therefore NOT complete.

## Sweep 4 (reporting, read in full where marked)
Read in full: `queries.py` (1,023 lines), `final_selection.py` (247), `validator.py` (318), `exporter.py` (lines 80-310 plus its filename path), `reporting_pipeline.py` (PostHog emitter, validate, cbom, resolve, pipeline).
Read at DDL/structure level: `schema.py` (DDL only, nothing executed at import).

| # | Where | Finding | Test (RED first) | Fix |
|---|---|---|---|---|
| 7 | reporting/superset/queries.py `_normalize_mpn_sql` | All-digit MPN longer than BIGINT (19+ digits) normalized to NULL (verified in DuckDB), so the join dropped the row silently. | testing/test_mpn_normalize.py (7 cases) | Regex strip of leading zeros (no cast). Commit 339ff35. |
| 8 | reporting/superset/final_selection.py `resolve_final_selection` | Re-run re-inserted conflicts a human had already resolved (the conflict query does not check final_*), inflating pending_conflicts. | testing/test_final_selection_resolved.py (2 cases) | `build_pending_conflicts` skips resolved cbom items. Commit 92cd0eb. |
| 9 | reporting/superset/exporter.py `export_reports` | Hard-coded `cbom_bounds_by_sheet["7.0 CBOM VL-1"]` raised KeyError for prototype-only or VL-2+ RFQs. | testing/test_exporter_reference_sheet.py (3 cases) | `_reference_cbom_sheet()`. Commit c65fe81. |

Open (decisions, not changed):
- validator.py `_safe`: a check that raises is recorded as `passed=True` ("skipped"). A check that cannot run is therefore counted as a pass in the overall result. Default: keep the documented behaviour; a decision is needed on whether skipped should fail.
- reporting `run_validate_reports` sends `rfq_id` to PostHog cloud when POSTHOG_API_KEY is set (product analytics, by design). Recorded as a data-egress point.
- The costing enrichment joins case-insensitively on part number only. Two source rows differing only by case would match one cbom row arbitrarily.

NOT read (SPEC-017 is NOT complete): reports/*.py (about 7,000 lines), templates/excel_mappings.py (1,477), migrations.py, database.py, currency.py, scrap_factor.py, helpers.py, enrichment.py, cbom_generator.py, report_generator.py, mcp_server.py (structure only), batch_validate_all_tests.py. Total about 10,000 lines.

## Sweep 5 (remaining reporting modules, pattern scan)
Scanned (grep-level, not line-by-line): templates/excel_mappings.py, reports/*.py, migrations.py, database.py, currency.py, scrap_factor.py, helpers.py, enrichment.py, cbom_generator.py, report_generator.py, mcp_server.py.
Checked and guarded: division sites (summary.py package uses max(1.0,...); aclass_parts guarded; summary ext_part_vol_price_conv guarded), float() on NULL-able fields (mech_em/pcb skip NULL nre_charge; summary uses _is_numeric), .iloc[0] on non-empty groupby results.

Open decision (single ask for Harish, with default):
- currency.convert_currency returns the RAW amount, unconverted, when a currency is missing from the rate table (e.g. 100 EUR reported as 100 USD). Pinned by mcp-tools/reporting/superset/test_currency.py (XYZ -> 100). The SQL twin (build_rate_case_sql) returns NULL for the same case, so the two layers disagree. Default I'd recommend: raise (or NULL), so unknown currency never produces a silent wrong amount. Not changed: 8 call sites and a pinned test. Needs your call.

Still NOT read line by line: reports/*.py, templates/excel_mappings.py (1,477), migrations.py, database.py, currency.py, scrap_factor.py, enrichment.py, mcp_server.py.

## Defaults applied to open decisions (SPEC-017, this round)
- **convert_currency unknown currency:** CHANGED to raise ValueError (no silent wrong amount). Commit 183e55f. test_currency.py updated.
- **validator.py `_safe` (skipped counts as pass):** DEFAULT KEPT. Documented behaviour; a skipped check is labelled "skipped" in its detail. Revisit if you want skips to fail closed.
- **Profile conflict (RFQ_Flow vs Standard_BOM_Flow):** DEFAULT KEPT. Caller passes the profile; hitl_router's `_advance_past_resolve_final_selection` still uses Standard_BOM_Flow (unchanged).
- **rfq-memory manifest port 8108 vs 8109:** DEFAULT KEPT at 8108 (chat listener). tools is empty, so nothing calls it yet.
- **HITL divergence (signal_delivered):** DEFAULT KEPT (report, do not change the stage write). Commit 43c355d.

## Real bugs fixed this round (SPEC-017)
- reporting/rfq-memory modules imported `db` from a `fastmcp-router/` folder that does not exist here (db.py is in fastapi-router/). ModuleNotFoundError on import, so the reporting MCP server could not start. Commit 6f9abe7 (its path was then corrected by 27cf287, which also fixed a `config` name clash that 6f9abe7 introduced; 6f9abe7 alone left 4 test_posthog_events failures in history).
- database.py `_rebuild_table_with_new_ddl` was not atomic: a failure stranded rows in `<table>__pre_proto_migration` (verified RED on real DuckDB). Commit 0a89a38.

## Verified NOT a bug
- DuckDB keeps running statements after an error inside a transaction, so generate_reports' "one report failing does not stop the others" holds.
- scrap_factor.py: SQL tier walk and Python classify_price agree for contiguous tiers; negative prices return NULL in both.

## Subagent review findings (read-only reviewers, 4 reports) -- status
FIXED (RED first, committed c17c6e4): price_control int("proto") crash; sum_and_count Proto coverage counted any volume.
FIXED earlier: batchwise empty-section reversed SUM range (test_batchwise_empty_section.py) -- uncommitted at time of writing, see git log.

OPEN, VERIFIED by reproduction in a reviewer's scratch run, NOT fixed (each needs a decision or a larger rework):
- summary.py:171/210/214 rfq_by_cpn_vol keyed cpn|vol with no revision: revision 0 reads revision 1's price. HIGH.
- summary.py:446-453 assembly rows read by position across revisions: wrong FG numbers on non-last revisions. HIGH.
- revision_history.py:162-172 max_volume = count of volumes, not max key: volume-2-only CPNs drop V2. HIGH (a naive fix was attempted and its test was vacuous -- redo with a real assertion on the header/cell).
- bom_matrix.py:331-332 fg_price_cols[(fi,0)] KeyError for an FG with no volume entries (proto-only BOM). HIGH crash.
- price_control.py:113 CNP bucketed as Centum in JSON, but the sheet's CNP row sums CNP+CUSTOMER. HIGH wrong numbers; DECISION needed (which is the reference).
- sum_and_count.py:43 vs sum_and_count_detailed.py: Quantity None counted in one, skipped in the other; repeated CPN in an assembly sums differently. MEDIUM.
- aclass_parts.py:81-84 total over repeated CPNs (shares not 100%); :119-133 vs sheet :339 MOQ turns use part_qty in JSON and vol qty in sheet. MEDIUM; intent UNVERIFIED.
- aclass_parts.py:136 float(lead_times) on "4-6 weeks" crash. MEDIUM.
- ex_inv_vl.py:94-98 volume match with no type coercion: "1" vs 1 gives an empty sheet silently. MEDIUM.
- excel_mappings.py:485/501 lead-time payload keeps only volume "proto"/"1": volume-2-start RFQs get a blank lead-time section. HIGH for those RFQs.
- excel_mappings.py:1036 vs :1158 cbom tree skips dual-role CPNs that the BOM matrix counts: E and G totals disagree on the same sheet. MEDIUM-HIGH.
- excel_mappings.py:913-915 groupby drops NULL mpn: part qty 0 everywhere. UNVERIFIED that mpn can be NULL in the schema.
- excel_mappings.py:250 apply(axis=1) on empty frame then groupby KeyError (bom matrix, only-root-row RFQ). MEDIUM crash; same pattern at :623, :444, not run.
- cbom_vl.py:454-510 currency table overwritten by validation block from the 8th currency. LATENT; production currency count UNVERIFIED.
- missing_notes.py:382-388 BOM status takes precedence over RFQ status (elif). Intent inferred from headings.
- summary.py:158-159 int(revision_no) crash on "R1". Only if rows are shared with revision_history.
- summary.py:636-637 bare except hides a KeyError in formula injection (silent).
- ex_inv_vl.py:280-284 volume-2 delta formulas reference 'Ex Inv VL-1' even when it does not exist.
- part_num_vs_mfg_num.py:71-73 "In Scrub BOM" is always true for a matched CPN (the RFQ's own MPN is in the payload but not compared). Business rule to confirm against the PHP reference before changing.

REJECTED after checking: lead_time sorted by volume_no string (payload volumes are ints/0 for proto); lead-time None volume (payload never None); pcb nre "N/A" (DB column is DOUBLE); batchwise_cashflow rest.

## Round 6 (subagent findings, verified then fixed, RED first)
FIXED and committed: bom_matrix KeyError on FG with no volumes (1 test); aclass lead time "4-6 weeks" crash; excel_mappings lead-time payload hard-coded volume 1 (volume-2-start RFQs blank); summary price lookup ignored revision (89.8 became 979.8); summary assembly rows matched by position across revisions; revision_history volume-2-only dropped (count instead of max; hard-coded reference volume; absent-volume formulas referencing missing sheets); ex_inv_vl volume "1" vs 1 silent empty sheet; bom_matrix to_bom_matrix_payload apply(axis=1) KeyError on root-only rows; price_control CNP bucket (DEFAULT: JSON follows the sheet); price_control proto crash; sum_and_count proto coverage.

DEFAULTS KEPT (decision recorded, not changed):
- summary.py bare `except Exception: pass` around formula injection hides a KeyError (silent). Default: keep; the Summary sheet has no live formulas today.
- part_num_vs_mfg_num "In Scrub BOM" always true for a matched CPN. Default: keep; needs the PHP reference (the RFQ MPN is in the payload if the rule is "quoted MPN is in scrub BOM").

OPEN, VERIFIED by reproduction, NOT fixed (need a reference or a design change):
- sum_and_count.py vs sum_and_count_detailed.py: Quantity None counted in the detailed sheet and skipped in the summary; a repeated CPN under one assembly is summed in one and taken once in the other. MEDIUM.
- aclass_parts.py: total_ext_price over repeated CPNs (shares not 100%); MOQ turns use total part qty in JSON but volume qty in the sheet. MEDIUM; intent unverified.
- excel_mappings.py to_cbom_tree_payload uses the raw structural set, not _effective_structural_fg_cpns(); a dual-role CPN is in the matrix but not the tree totals (E and G disagree). MEDIUM-HIGH; needs a design decision.
- excel_mappings.py groupby drops NULL mpn (part qty 0). UNVERIFIED that scrub mpn can be NULL in the schema.
- cbom_vl.py currency table overwritten by validation labels from the 8th currency. LATENT; production currency count unverified.
- missing_notes.py BOM status takes precedence over RFQ status. Intent inferred.
- summary.py int(revision_no) crash on "R1" (only if the same rows are shared with revision_history).
- ex_inv_vl.py delta formulas reference 'Ex Inv VL-1' for volume 2 even when VL-1 does not exist.
- missing_notes.py seen_ids dedupes rows with id None into one. LOW.
- Not run / out of reach: SPEC-015 D6 (Docker) and SPEC-016 browser run (daemon + router).

## Round 7 (open items given defaults, then fixed or recorded)
FIXED (commit 0ddad9d, RED first): cbom tree uses the effective structural set; Sum & Count detail matches summary (null skipped, repeats summed); aclass total counts each CPN once; aclass MOQ turns = Ext Vol / MOQ (sheet's formula); Ex Inv VL delta formulas skipped when the previous volume sheet is absent (exporter passes previous_sheet_exists).

DEFAULT KEPT (no change, reason recorded):
- In Scrub BOM always "true" for a matched CPN. Needs the PHP reference: if the rule is "quoted MPN is in scrub BOM", change the membership test to the RFQ's MPN (already in the payload).
- summary.py bare except around formula injection: keep; Summary has no live formulas today.
- missing_notes BOM-before-RFQ status precedence: keep; intent inferred from headings only.
- summary int(revision_no) on "R1": only when the same rows are shared with revision_history; keep.
- missing_notes seen_ids dedupes None ids: LOW, keep.

NOT FIXED (needs a layout decision):
- cbom_vl.py currency table (J2:K) is overwritten by the Validation block from the 8th currency. Latent: code comments say only USD/INR/EUR are defined. Fix = move the Validation block to other columns; deferred because it moves cells on a shipped sheet.

ENVIRONMENT-BLOCKED (cannot run here):
- SPEC-015 D6 (compose network) needs Docker.
- SPEC-016 browser run needs the daemon and router.
- Parity live tests need the router on :5100 (CAM_PARITY_LIVE=1).

## Round 8 close-out 2026-11-02 (remaining OPEN items: fixed or defaulted, per GOAL §5)
FIXED (RED first, testing/test_null_mpn_quantity.py, 2 tests):
- scrub_bom.mpn is nullable, but the FG and per-assembly quantity sums dropped rows with no MPN (part qty 0). Measured RED: totals 1 instead of 5. Fix: _with_blank_mpn() keys a missing MPN as "" in fg_part_qty_sums, fg_assembly_part_qty_sums and both representative-MPN helpers. (The first attempt, dropna=False, did not fix the FG path: first() returns NaN, which a dict lookup cannot match.)
DEFAULTS (decision recorded, not changed):
- sum_and_count vs detailed (None quantity, repeated CPN): default kept, skip null qty and sum repeats (matches the summary decision).
- aclass total over repeated CPNs and MOQ turns: default kept, each CPN counted once; MOQ turns = Ext Vol / MOQ. Intent UNVERIFIED against the PHP reference; flagged.
- ex_inv_vl volume-2 delta formulas reference 'Ex Inv VL-1': default kept. The formula is wrapped in IFERROR (test_ex_inv_previous_sheet.py asserts the wrapper), so a missing VL-1 yields blank, not a wrong number.
- excel_mappings dual-role CPN in the cbom tree: already fixed (test_cbom_tree_dual_role.py).
- summary bare except, missing_notes precedence, summary R1 revision crash, missing_notes None ids, In Scrub BOM rule, validator skipped=pass, currency raise: defaults kept as listed above (decisions unchanged).
DEFERRED (layout change, not a logic error):
- cbom_vl.py currency table (J2:K) overwritten by the Validation block from the 8th currency. Latent: only USD/INR/EUR defined today. Fix = move the Validation block to other columns. Deferred: it moves cells on a shipped sheet. Revisit when a sheet needs 8+ currencies.
Result: suite 179 passed, 4 skipped (includes the 2 new tests).
Not verified: the reporting container used by the e2e stack was not rebuilt after this change; the e2e stack still runs the previous build.

## aclass check 2026-11-03 (resolves the "PHP reference" item)
- The reference folder has NO PHP files (0 .php under Reference[KT]). The check uses the domain docs instead: Domain 4 line 57 ("MOQ turns = Ext Vol / MOQ; X = % of total spend") and Domain 3 item 14 (A CLASS = top ~80% of spend).
- MOQ turns: matches the documented formula (aclass_parts.py:139-141).
- ABC Classification (A/B/C, the 80% cut): NOT computed in Python. aclass_parts.py:171 writes "-" and a live sheet formula reads it from CBOM VL-1. No test covers the 80% rule, so it stays UNVERIFIED.
- "Count each CPN once" for the total: kept as the default; the docs do not state it either way.

## A/B/C conflict logged 2026-11-03 (OPEN decision, default recorded)
- Measured in a real workbook (RFQ-E2E-6 export): the A CLASS PARTS "ABC Classification" column (P) is a live lookup into '7.0 CBOM VL-1' column AJ, which takes the CBOM "ABC Classification" from the hidden "Scrap Factor" sheet. That sheet is a UNIT-PRICE TIER table: A = price >= 1.25, B = price >= 0.25, C = below (Min INCLUSIVE, Max EXCLUSIVE). Source: mcp-tools/reporting/superset/scrap_factor.py (states this as "confirmed" business rule).
- Domain 4 (line 58) and Domain 3 item 14 define A CLASS as "top ~80% of spend" (cumulative cost share). That is a different rule.
- DOC vs CODE CONFLICT. Per GOAL §5, logged here. DEFAULT: keep the implemented unit-price tier rule (explicitly confirmed in code). Needs Harish's decision: which definition the workbook should carry.
