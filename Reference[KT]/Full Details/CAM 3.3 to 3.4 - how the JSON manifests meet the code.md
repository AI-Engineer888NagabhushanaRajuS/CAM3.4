# CAM 3.3 to 3.4: how the JSON manifests meet the code, and what to do

*Private working note, polished. It is a read of source and documents; nothing was run.*

**Labels used throughout**

| Label | Meaning |
|---|---|
| SOURCE | read in code |
| DOC | stated in a document |
| REPORTED | said in chat or by the team |
| PROPOSAL | a suggestion |
| OPEN | not found in what was inspected ("not found" means only in the files opened) |

## 1. Short answers

| Question | Answer |
|---|---|
| Is the current system CAM 3.3? | **DOC / REPORTED: yes.** Srinath's note (17 Oct) says "CAM 3.2/3.3 is already built via Python scripts outside ISATVON/BAM", and one code comment reads "CAM 3.3 report-only change" (SOURCE: `backend/reporting_module/exporter.py`, line 98). No version constant or tag was found in the repository, and it is one squashed commit, so no commit can be shown as "3.3". **OPEN:** ask for the real git history. |
| What is 3.4? | No definition of "3.4" exists in any source read (the only "3.4" in the code is the unrelated fastmcp 3.4.2 library version). So 3.4 is the team's plan: fix the 16 reports, add the assistant chat in the middle of the UI, replace Dify with Temporal. The BAM draft document is titled "CAM 4.0 RFQ automation in BAM" and is a different, bigger target. Keep **3.4** (changes to today's system) and **4.0** (the BAM build flow) apart. |
| Can Jinja2 + AST turn JSON manifests into working tools? | **Yes in design, and BAM has real code for it.** The direction is manifest in, Python code out (not code to JSON). The generated code is a fixed skeleton plus four pieces an LLM writes at build time, so "works without an LLM" is true when the tool *runs*, not when it is *built*. |
| Will it work today if a manifest is added? | **No.** In BAM the registered build workflow still calls placeholder stages for the middle and end of the chain, and no code anywhere loads a manifest into CAM's runtime. Today the CAM manifests describe code that already exists; they are not inputs that build it. |
| Should the 16 reports be generated from a manifest? | **No.** They already exist as working code. Put the manifest around that code and fix the code in place (section 4). |

### In plain words: the Jinja2 + AST idea

1. A JSON manifest (ISATVON) describes the tool: inputs, logic slots, output.
2. Jinja2 renders that manifest into actual Python source.
3. Python's own `ast` module parses the generated code, which proves it is valid, safe Python and lets it be inspected or transformed before anything runs.
4. The validated code is registered as a FastMCP tool that the runtime can call.

That is the "JSON in, working tool out" pipeline. No LLM is needed at run time; an LLM, if used, only fills the body slots at build time. The catch, verified in the repositories: BAM has the real code-generation modules, but its registered build workflow still imports stub stages, so today putting a JSON in does nothing. The bridge between "manifest created" and "tool runs" is not wired, and wiring it is the actual 3.4 work, not a new invention.

## 2. What CAM 3.3 is, from the source (SOURCE unless marked)

**Repository.** `solutionsDigibull/CAM`, commit `0d54fd90`, one squashed commit. The copy read was an API harvest of 64 files. Not read: `backend/reporting_module/reports/*`, the templates and the frontend subtrees (listed as pending in the harvest note), so no individual report tab can be described from code.

**How a request moves today**

1. **Dify** (an external service; flow file `Dify_DMR_RFQ_Flow.yml` in `solutionsDigibull/BuLLMQuote_SRIM`, folder `dify-orchestration`, commit `5409180`, 574 lines) starts with the RFQ id.
2. Dify calls `GET /pipeline/routing-sequence/{rfq_id}/RFQ_Flow` on the CAM FastAPI service (`backend/fastapi_router.py`) and gets the list of skills and the current skill index.
3. Dify loops. For each skill it calls `POST /tool/execute` (`fastapi_router.py`, line 223). The router checks the routing profile (skills can be toggled off), calls the tool through the MCP gateway (`tool_calling.py`, `call_tool`, blocking, up to 300 s), updates the skill index and posts progress to the UI (`notify_skill_progress`, `emit-skill-progress`).
4. An if-else node decides whether to continue. A final HTTP node triggers the human-in-the-loop step (port 9234, `trigger-hitl`).

**Tools.** FastMCP servers. The reporting one is `backend/reporting_module/mcp_server.py` with six tools: `cbom`, `enrich_erp`, `enrich_costing_sheet`, `resolve_final_selection` (the human gate), `generate_reports`, `export_reports`. The intake tools are separate (`scrub_mcp_server.py` and the quote-win, ERP and costing-sheet processors).

**Data.** DuckDB for the CBOM and report tables; Postgres for routing and the `system_skills_registry` table.

**The 16 reports.** `constants.py` (`SHEET_NAMES`) lists the CBOM plus 16 report sheets: BOM Matrix, Part Number vs MFG Number, PCB NRE and FAI Charge, Mechanical EM NRE, Missing Notes, Lead Time FG, Lead Time Consolidated, Sum and Count, Sum and Count Detailed, Revision History, A-Class Parts, Price Control, Summary, Batchwise Cashflow, CBOM VL, Ex Inv VL. `generate_reports` writes the 16 report tables; `export_reports` builds one workbook by calling a fixed sequence of `build_*_sheet` functions (`exporter.py`, 387 lines; DOC from the 1.4.0 manifest text).

**Not found.** Any Temporal code in CAM or in BuLLMQuote_SRIM. Dify itself has no code in the repository (its README says it is only an external API integration; the flow file is the only artefact).

## 3. The manifest-to-tool pipeline, end to end

### 3a. The target pipeline (DOC and SOURCE in BAM)

BAM source: repository `solutionsDigibull/BAM` at `9e6749d` (`server/workers/sbam_workers/...`). The intended chain for one Sub-Skill:

| Stage | What it does | Status |
|---|---|---|
| `build_manifest` (`build/manifest.py`) | Makes the manifest. Hardcodes the runtime block to Dify, MCP Jungle and SRIM UI Canvas (an ADR default, O-19) | SOURCE: real |
| `check_libraries` | Confirms the allowed libraries | |
| `render_skeleton` (`build/codegen/params.py`, `render.py`) | Maps the manifest to parameters, validates them and renders six Python files with Jinja2 in a sandboxed environment from `templates/fastmcp-loopy/1.0.0` (`template.yaml` plus six `.j2` files) | SOURCE: real modules |
| `generate_bodies` (`build/codegen/bodies.py`) | An LLM (alias `sbam-codegen`) fills only four slots: helpers, `action_body`, `check_body`, `state_queries`. An AST pre-check rejects bad imports and patterns (forbidden modules, `while` loops, raw-SQL rules) | SOURCE: real module |
| `assemble` (`build/codegen/bundle.py`) | Splices the bodies between `LLM_BODY` markers, formats with Black, parses with `ast`, hashes the bundle (`bundle_sha256`) and writes a deterministic tar | SOURCE: real module |
| `correct` (`correction.py`) | A loop that feeds gate findings back to the LLM | SOURCE: real module |
| `ast_gate`, `static_gate`, `generate_tests`, `build_promptfoo_suite`, `run_sandbox_tests`, `certify` | The registered workflow (`pipeline/sub_skill_build.py`) imports these from `build/stubs.py`, `test/stubs.py` and `certify/stubs.py`, whose docstrings say STUBS | SOURCE: that is what the imports show. A review of `main` at `9e6749d` reached the same conclusion: the registered stages are stubs and the real codegen modules exist unwired |

**What the template produces.** One FastMCP server per Sub-Skill with a separate action tool and a fixed check tool, a read-only fresh-state reader and an append-only state-handoff writer (`models.py`, `state.py`, `state_handoff.py`, `action_tool.py`, `check_tool.py`, `server.py`). It is built for the ISATVON loop (do, check, hand off), not for assembling a 16-sheet workbook. `openpyxl` does not appear in the templates; in BAM it appears only in the ingest loader.

### 3b. What is missing between "manifest made" and "tool running" (OPEN, not guesses)

- The registered build workflow does not call the real codegen yet (above).
- **Build-to-runtime handover.** ADR 0010 says the generated manifest "is what SRIM will use" (future tense). No importer or loader for that was found in BAM, CAM or BuLLMQuote_SRIM. CAM reads `system_skills_registry` (`backend/db.py`, lines 635 and 681), but no code in the inspected files writes to it, and none loads `backend/docs/*.json`. **Who fills that table is OPEN.**
- Three different registries exist and must not be mixed: workflow registration (BAM `registry.py`, `workflow_for`), the dependency library registry, and CAM's runtime `system_skills_registry`.
- BAM's runtime block (Dify, Jungle) names the old runtime. A Temporal runtime for generated tools is not defined in what was read.

### 3c. The ten CAM manifests that already exist (SOURCE)

`backend/docs` holds ten JSON manifests: four for intake (scrub BOM, quote win, ERP, costing sheet) and six for reporting (`cbom`, `enrich_erp`, `enrich_costing_sheet`, `resolve_final_selection`, `generate_reports`, `export_reports`).

- They already use the BAM contract shape: `skill_metadata`, `isatvon_definition` (I, S, A, T, V, O, N), `srim_runtime_definition`, `contracts`, `governance` (this matches ADR 0010, C-49). Version 1.4.0, status APPROVED.
- Their text describes the current Dify flow ("Triggered by the Dify DMR's POST /tool/execute ... FastMCP port 8005"), and the governance hash says `TO_BE_COMPUTED_ON_SAVE`. So they were **written after the code, to describe it**.
- Two separate notes say the 16 reports are "one manifest and one tool" (DOC, Srinath), but in the code and in these files they are **six tools and six manifests**. This mismatch is worth settling with Harish.
- **Not checked:** whether these ten pass BAM's strict manifest validator (`sbam_contracts/manifest.py`); no code was run. **PROPOSAL:** have the team run it.

## 4. Feasibility by part

### 4a. Fix the 16 reports

Feasible, and it is normal code work, not a generation problem. SOURCE: the pipeline, a validator (`validator.py`), a batch checker (`batch_validate_all_tests.py`) and two written defect notes already exist in the repository:

- `backend/Test_fixes/BOM_MATRIX_QTY_ROLLUP_BUG.md`: BOM Matrix quantity ignores the parent sub-assembly quantity (proven from output data; the generator was not available when it was written).
- `EXCEL_LOAD_PERFORMANCE.md`: slow Excel open; structural analysis, never timed.

The gap is the per-tab contract: for each of the 16 tabs, no written spec of formulas, layout and expected values, and no test per tab, was found in the files read. The 1.4.0 manifest only describes the whole workbook (one input `rfq_id`, one output with sheet names). **OPEN:** where the reference production workbook and gold files live.

### 4b. Assistant chat in the middle of the UI

Target only. SOURCE: CAM's frontend is a fork of Accomplish (an open-source desktop AI assistant; the harvest note calls it a v3.2 fork, which is not runtime evidence). REPORTED by the team: the middle chat comes from the Refine and AG Grid drafts (not re-inspected for this note). The backend already pushes progress to the UI (`notify_skill_progress` to `emit-skill-progress`, with a hardcoded internal IP in the source, `192.168.1.18:9234`). A chat needs a stable event and message API and a decision on which tools the chat may call. **OPEN:** that API does not exist in what was read.

### 4c. Dify to Temporal

Feasible, and smaller than it sounds, because the control logic mostly lives in CAM's FastAPI router, not in Dify. Dify's job is three calls and a loop (section 2). A Temporal workflow can do the same: one activity for the routing sequence, a loop of an execute-tool activity (with timeouts and retries, replacing the blocking 300 s call), and a signal or wait for the human gate (`resolve_final_selection`). Keep `POST /tool/execute` unchanged at first, so tools and routing stay as they are.

What changes: the Dify code nodes (only the first, which parses the routing response, was read; the other two were not), the if-else on status, the hardcoded hosts (`host.docker.internal`, `192.168.1.18`), which become settings, and the manifests' `srim_runtime_definition` text (router "Dify_Dynamic_Master_Router"), which needs a new value.

**Keep apart.** BAM contains real Temporal code (workflows and tests under `server/workers` and `server/tests/temporal`), but it is the build-time engine of a different system. SOURCE says it exists in BAM; it says nothing about CAM runtime operations. It is not the CAM replacement; reusing its patterns is a design choice, not a fact.

### 4d. Jinja2 + AST for new skills

Feasible only for the shape the template supports (action tool, check tool, state handoff), with LLM-written bodies and an AST gate. For existing report code it would mean rewriting working, tested logic with an LLM, which is not recommended. For new small skills (for example the assistant's tools) it is the intended use once the BAM stubs are replaced.

## 5. What to do, in order (PROPOSAL unless marked)

1. **Pin the baseline.** Ask Srinath for the real CAM git history and which commit is 3.3 (the document says git can be shared). Tag it. Everything below is a diff from that tag.
2. **Fix the 16 reports in place.** Start with the BOM Matrix defect (the note is already written). Write one expected-output check per tab against the production reference workbook, using the existing `batch_validate_all_tests.py` as the base. Keep the tool names and inputs unchanged. Read the `reports/` folder first (it was not in the copy).
3. **Make the manifests match the code.** Decide with Harish: six reporting tools with six manifests (as built), or one reporting tool (as the draft says). Compute the real governance hashes. Check the ten files against BAM's validator. This is a document fix, not generation.
4. **Swap Dify for Temporal behind the same API.** Build the workflow from the Dify flow file, run both on one test RFQ and compare the skill index, status and HITL behaviour. Move hosts and IPs to configuration. Only then retire Dify. Update the manifests' runtime block.
5. **Add the assistant chat after step 4.** Define the event and message API first, then the UI panel. The chat calls the same router.
6. **Treat Jinja2 + AST as the 4.0 track.** The BAM team replaces the build stubs in order, defines how a certified manifest reaches the runtime registry (the missing importer) and picks a first small new skill as the pilot. Do not use the 16 reports as the pilot.

> **Where this stands now (added in the polish, 2026-11-06).** Steps 1 to 5 have since been worked on in `CAM-Source`: the baseline is tagged `v3.3-baseline`; the reports and their per-tab validation are SPEC-002; manifest alignment SPEC-003 and the manifest pipeline SPEC-013; Temporal and HITL signals SPEC-004 and SPEC-005; the assistant chat SPEC-006, SPEC-010 and SPEC-019. See [`SPECS/README.md`](../../SPECS/README.md). Step 6 remains the 4.0 track.

*This note replaces the rough file `json ,. .. other topics.txt`; the verbatim original is kept in `SPECS/handoff/original-notes/`.*
