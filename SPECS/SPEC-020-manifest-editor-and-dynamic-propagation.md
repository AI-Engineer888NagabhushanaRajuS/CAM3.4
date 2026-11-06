# SPEC-020: Manifest editor (Monaco) and dynamic propagation of edits

Status: implemented and proven live 2026-11-05 (manifest editor, lint + codegen preview, edit-and-regenerate with cell diffs, assistant edit/open-manifest, live changes panel); see handoff/HANDOFF-2026-11-05.md section 9.13 for evidence, what is NOT verified and the known limits. Written in ISATVON. Source of the decisions: `Reference[KT]\Full Details\CAM 3.4 - Complete Documentation (WORKING DRAFT).md` sections 1.1-1.3, 7.5-7.7 and the package `CAM_3.4_documentation_package_2026-11-05_WORKING_DRAFT.zip` (extracted: 1 agent manifest, 10 skill manifests, the 16-report Centum manifest, 10 as-built v1.4.0 manifests). Harish: "decide and build, do not ask things only he could answer".

## I - Instructions
1. A Monaco JSON editor inside the app so the ISATVON manifests can be viewed and edited in place, with the agent > skill > sub-skill hierarchy as an expandable tree, live validation, safe save (hash, version, history, conflict check).
2. Dynamic propagation: when one value changes, the change is mirrored across every sheet and workbook that depends on it, shown in realtime, both before output (in the app) and after output has been given.
3. The assistant (middle pane) can drive both: open a manifest, and make an edit that regenerates the reports, always behind a confirmation card.
Hard rules: no invented facts; every write confirmed or audited; nothing outside 3.4 (no Jungle/Dify/Bifrost containers touched); manifest files are DATA (never executed); JSON from the package is untrusted until validated.

## S - Source
Documentation 1.1 (agent/skill JSON layer), 1.2 (what exists vs what must be added: importer/loader, registry writer, edit loop with validation and computed hashes), 1.3 (propagation semantics and the proposal "database as truth, regenerate affected sheets/workbooks, stream status and artifacts over the existing server-side-event channel"), 7.5 (assistant calls the same router, no second execution path), 7.6 (Monaco edit loop), 7.7 (propagation). Existing code: `PUT /api/bom/batch-update/{rfq_id}` (`fastapi-router/duck_db_api.py` ~244, nine `final_*` fields + `recompute_derived_columns`), export endpoints (~435-520), `export_reports` (`mcp-tools/reporting/superset/mcp_server.py`), RFQ versioning (`versioned_key`), SSE `rfq:skill-progress` (`notify_skill_progress` in `fastapi_router.py` -> daemon `/api/internal/emit-skill-progress` -> `sendToRfq`).

## A - Automation (decisions, recorded; these answer the documentation's open semantics)
- (a) Source of truth for a value change: the APPLICATION STATE (the costed-BOM tables in cbom.duckdb that the existing edit path writes). Workbooks are generated outputs and are never patched.
- (b) Pre-output editing: the editable fields are the nine `final_*` fields the existing batch-update endpoint already accepts (the endpoint's own allow-list is the list). An edit re-runs only the report builder (`export_reports`), not the upstream skills.
- (c) Post-output: the same edit regenerates and RE-ISSUES the workbook as a NEW versioned artifact; the previous version stays downloadable. A downloaded Excel file is never patched live (not an Excel-native capability).
- (d) What streams over SSE to the right pane: `rfq:value-changed`, `rfq:reports-regenerating`, `rfq:reports-ready` (new filename, number of changed cells and sheets), `rfq:reports-failed`, next to the existing `rfq:skill-progress`.
- Cell-level proof of propagation: after regeneration the new workbook is compared with the previous one (stored cell values, openpyxl `data_only`), producing per-sheet changed-cell counts with before/after examples; the diff is saved next to the export and shown in the UI.
- Manifests: stored in `CAM-Source/manifests/` (agent, skills, reporting, repo-approved), loaded by the daemon, validated (JSON Schema per kind, served to Monaco for live validation and completion), saved with a computed `governance.deterministic_hash` (sha256 of the canonical JSON with the hash field blanked; replaces `COMPUTED_ON_SAVE`), patch-version bump, previous copy kept in `manifests/.history/`, optimistic conflict check (`baseHash`), audit line. Editing a manifest does NOT change runtime behaviour yet (honest label in the UI: "design input, not wired to execution"), because the importer that makes a manifest drive a tool is the 4.x build chain (doc 7.8); what this delivers is the editor, validation, versioning and the hierarchy the left pane will be built from.
- The repo's `manifests/` top level already holds the six RUNTIME tool manifests (`centum_*.json`, SPEC-013: `fastapi-router/config.py` globs `manifests/*.json` NON-recursively at startup; `scripts/import_manifest.py` + `validate_manifests.py` own them). The editor lists them READ-ONLY ("live routing manifest: change it with scripts/import_manifest.py"). The design manifests from the package live in subfolders (`manifests/agent|skills|reporting|repo-approved`), which the router ignores, and are the editable ones. Never write a design manifest at the top level.
- 6 reports vs 1 manifest ("six tools vs one") stays as the doc's recommendation: reports remain hand-written Python, the manifest describes them.

## T - Tech stack
Allowed: daemon (TypeScript, `ajv` for JSON Schema if present), web (`@monaco-editor/react` + `monaco-editor`, bundled locally by Vite, no CDN), bridge (FastAPI, openpyxl), existing SSE channel, existing reporting MCP export path via the router/tool execute. Forbidden: executing manifest content, a second execution path for reports, patching delivered workbooks, touching `docker-*`/`mcpjungle-server`.

## V - Variables
- Manifest save: max 512 KB; admin-only if the session exposes a role (else any signed-in user, audited); conflict -> 409.
- Edit request: up to 200 rows per call; `final_*` allow-list only; regeneration timeout 300 s; edits are reverted if regeneration fails (nothing half-applied).
- Diff output: top 20 changed cells per sheet as examples, full counts per sheet.

## O - Outcome (done means each works in the REAL UI, proven by DOM/network, not by script)
1. `#/manifests`: tree agent > 10 skills > 40 sub-skills (+ reporting manifest + 10 approved manifests), selecting one loads it in Monaco with schema validation.
2. Editing a draft manifest and saving: version bumps, a real sha256 replaces COMPUTED_ON_SAVE, a history copy exists, an invalid edit shows a marker and is refused, a stale save returns 409.
3. Edit one `final_*` value of a test RFQ: events stream to the UI, a new versioned workbook appears, the diff shows changed cells across several sheets (cell-level numbers), the old version stays; reverting the edit regenerates again.
4. The assistant: "open the Input Standardization manifest" gives a button; "set <field> of <part> to <value> for RFQ-x" gives a confirmation card with the current and new value, and Confirm triggers the same path as (3).
5. Tests: daemon (validation, hash, history, conflict, routes), web (tree, Monaco wiring, save/refusal), bridge (edit allow-list, revert on failure, diff), assistant (intent, card, confirm).

## N - Notification (assumptions, confidence, open)
- Assumption: "editable fields" = the nine `final_*` fields of the existing endpoint; extending to other fields (e.g. business-rule variables in the Centum manifest `v_variables`) is a later step because changing those changes report logic, not data. Confidence medium-high.
- Assumption: re-issue as a new version, never patch (doc 1.3 c). Confidence high.
- Known gap by design: a manifest edit is stored and versioned but does not yet change what a tool does (importer = 4.x chain). The UI says so.
- Open for Harish only if he disagrees: admin-only manifest edits; whether `v_variables` edits should later drive the report builder.

## Codegen (BAM port)
Harish: "put the JSON in and the output follows (JSON + ISATVON + Jinja2 + AST)". Built in `CAM-Source/fastapi-router/manifest_codegen.py` + `templates/skill_tool.py.j2`, routes `POST /api/manifests/lint` and `POST /api/manifests/codegen` (preview only: nothing is executed or written). Key finding: in the BAM download (`BAM-full-ui--main`) the Jinja2 template and the AST check are stand-ins in `Frontend/src/api/mock.ts` (and the Temporal activities A-D are a mock), so the real implementation is written here in Python, porting BAM's RULES.

Ported:
- `mock.ts` `validateField` (per ISATVON field) -> `lint_manifest`, mapped to our keys: instructions >= 15 chars (`i_instructions`); source required (`s_source.required_inputs`); automation non-empty (`a_automation.*`); tech stack non-empty + `REGISTRY` check, unknown = warning (`t_tech_stack`); variables well-formed (`v_variables`: max_iterations positive int, warning above 10, budget_limit duration, success_gate); outcome schema present (`o_outcome.json_schema`); notifications (`n_next` / `n_notification`).
- `mock.ts` `REGISTRY` -> `REGISTRY` plus what this repo really uses (posthog, paddleocr, uppy, tusd, mcp jungle, dify...).
- `tests/test_isatvon_edge_cases.py` `PLACEHOLDER_PATTERN` (TBD/TODO/TBC/lorem/xxx/to be decided|confirmed/n/a/??) -> warning with the JSON path.
- `mock.ts` `renderSkill` shape (constants, VARIABLES, Outcome model, run function) -> the real Jinja2 template (`SandboxedEnvironment`, `StrictUndefined`, every manifest string through `pystr`), extended to the documentation 7.8 shape: one FastMCP server per sub-skill with the bounded do/check/hand-off loop and marked TODO business-logic slots (the skeleton returns "not done" until they are filled).
- `mock.ts` `astErrors` stand-in -> a real `ast.parse` gate (import allow-list; eval/exec/compile/__import__/subprocess/socket/os.system and getattr-style escapes refused).
- `mock.ts` activity D self-heal -> an unquoted `=formula` value that causes a SyntaxError is quoted and retried once, recorded in `repairs`.
- `mock.ts` sha256 of the code -> `bundle_sha256` over sorted path + content (deterministic).

Not ported: SOW generation/synthesis, the Laya judge and eval, the Temporal workflow (a mock in the source), CubeSandbox/Promptfoo execution, LLM body generation (`generate_bodies`: the TODO slots stay human work), Black formatting, the deterministic tar, and writing a certified manifest into a runtime registry (4.x track, doc 7.8).

Caveats: lint/codegen auth uses `verify_token_any_project` (any valid 60 s token; these routes have no rfq/project to scope to). `jinja2` is not pinned in `requirements.txt`; it reaches the image through cognee/litellm.
