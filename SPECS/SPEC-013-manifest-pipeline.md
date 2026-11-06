# SPEC-013 — Manifest pipeline: importer, registry writer, gateway registration

**Status:** completed, commit fa08813 (118 passed, 3 skipped; see progress.json)
**Branch:** feat/spec-013-manifest-pipeline (from feat/spec-012-security)
**Depends on:** SPEC-012

## Context
Diagram "3.4 architecture with the manifest pipeline", Lane 1 + the "Bridge into the runtime"
(registry writer, gateway registration, parity test in staging: all MISSING). Migration path
step 3: "one manifest per real tool, derived from code". Findings from reading code this session:

- `skill_index` is the integer position in `routing_sequence` (DMR: `routing_sequence[skill_index:]`,
  glossary in Reference[KT]). `system_skills_registry.skill_index` cross-references it.
- The registry DDL is not in the local DB (`logic_db_2` holds only currency tables). It IS documented in
  Reference[KT] `docs/Database/logic-database.md` (a past live introspection, not re-verified): `skill_code` PK,
  `skill_index` UNIQUE, `macro_category_name` NOT NULL, `macro_category` nullable, `profile_name` UNIQUE.
  The first cut of the writer ignored this and would have failed on the real table; corrected in a follow-up commit.
- Documented live data: skills 1-8 = Standard_BOM_Flow in order; inactive ERP skills hold indexes 9 and 10. Appending a
  tool at sequence position 9 therefore collides. **DECISION FOR HARISH:** renumber the inactive ERP skills, or give the
  new tool index 11 and accept skill_index != sequence position (affects only progress labels for that tool).
- This branch routes tools directly via `fastapi-router/config.py` (SPEC-003); `v3.3-baseline` used
  Bifrost (RFQ_Flow) + Jungle (Standard_BOM_Flow). Diagram says gateway choice is OPEN.
- **Defect D4 (proven):** `config.get_mcp_url` routes by tool-name prefix, so the 4
  `centum_intake__standardize_*` scrub tools resolve to Intake :8002 instead of manifest
  `centum_scrub_intake` :8004. Root cause is the same rule this spec enforces (a manifest owns its tools).
- **Defect D3:** `MCP_URLS` is built once at import; a manifest imported later needs a restart.

## Scope
1. `fastapi-router/config.py`: tool -> URL map built from `manifests/*.json` `tools[]`; rescan once on a
   miss (no restart after import). Unknown tool raises (no prefix guess).
2. `scripts/import_manifest.py` (reuses `validate_manifests`):
   - strict shape check of a manifest dict (fields, id/version/port/tool-name format, `mcp_server`
     stays inside the repo, tools exist in the server via AST, tool names/ports unique across manifests);
   - canonical sha256, store in `manifests/<id>.json` (created / unchanged / updated);
   - registry writer: ONE transaction, advisory lock, idempotent. Inserts `system_skills_registry` rows
     and appends to `quote_routing_profiles.routing_sequence` only for tools named with `--register`.
     `skill_index` = profile max + 1 (offset-agnostic); refuses on collision. Receipt file written BEFORE commit;
     `rollback_receipt` removes exactly what was added;
   - dry-run by default (same code path, then ROLLBACK); `--apply` to persist;
   - Jungle registration as a command builder (`mcpjungle ... register`), run only with `--apply` + `--jungle-registry`.
3. `verify_registration`: read-back check of registry row + sequence membership.

## Acceptance
- Every tool of every manifest resolves to the port of the manifest that declares it.
- A manifest stored after startup resolves without restart.
- Hostile/malformed manifest dicts rejected with a message; valid ones pass; the 6 shipped manifests pass.
- Registry writer on a real (scratch) Postgres: first apply adds, second apply is a no-op, rollback restores,
  a failure midway leaves nothing, dry-run leaves nothing.
- Full `pytest` green; only the 3 shadow-run skips remain.

## Tests
`testing/test_manifest_pipeline.py` (scratch Postgres 17 cluster via initdb/pg_ctl; skipped if binaries missing).

## Defaults chosen (all recorded; change on request)
- **No skill_09 adapter.** Input format is BAM-side and BAM is out of scope; the strict shape is the
  repo's manifest v1 (README). Add an adapter when a real skill_09 sample is provided.
- **No Temporal activity wrapper / queued build.** Nothing calls the importer from a workflow yet and the
  build queue is the 4.0 codegen track. Library function + CLI instead.
- **Gateway: direct manifest routing is the live path** (config.py). Jungle registration provided as a
  dry-run command (mechanism from the 3.3 infra script `register-centum-servers.sh`); Jungle name = the tool
  prefix (e.g. `centum_intake` for :8004), not the manifest id. Jungle vs Bifrost stays OPEN.
- **Parity test in staging = read-back verify**, not output diff: there are no generated tools to compare
  (codegen is 4.0). Dify-vs-Temporal output parity is SPEC-014.
- Registry fields come from the manifest tool: `skill_code`, `skill_index`, `macro_category_name` are required
  (rejected before any write); `skill_name` falls back to the description; `macro_category`, `requires_llm` optional.
  `skill_index` is never guessed.

## Conflicts logged
- Diagram: "No Bifrost in CAM" vs `v3.3-baseline` `config.py` (Bifrost URL + endpoint slugs for RFQ_Flow). Diagram wins; recorded.

## Defects found, owned by later specs
- D1 (SPEC-015): `/pipeline/routing-sequence` calls `call_tool("Production_Logic_DB-execute_sql")`; unroutable
  on this branch, returns `{"error": ...}` to the Temporal activity. Fix: read via `db.get_routing_sequence`.
- D2 (SPEC-015): `workflow.py` does `step["tool_name"]`; real `routing_sequence` is an array of strings.
  `test_temporal_workflow` mocks dict steps and hides it.

## Update 2026-11-03: Jungle register command checked against a real Jungle
- The command the importer printed (`mcpjungle register --name X --transport streamable_http --url Y`, copied from
  the 3.3 script Reference infra/mcp-jungle/register-centum-servers.sh) was never executed in SPEC-013. Run against
  the installed build (ghcr.io/mcpjungle/mcpjungle:latest-stdio) it fails: `unknown flag: --transport`.
- That build's `register` has only --name, --url, --description, --bearer-token, --conf, --force; --url is
  "URL of the streamable http MCP server". Version difference: the 3.3 Jungle was older (it accepted --transport).
  `jungle_register_argv` now omits the flag (testing/test_manifest_pipeline.py updated, RED first).
- Verified: `centum_intake` (scrub, :18004) and `centum_reporting` (:18105) registered on this machine's Jungle;
  all 8 Standard_BOM_Flow tool names listed. Intake (:8002), gerber and distributor were NOT registered: intake's
  prefix is also `centum_intake` (it would replace the scrub server's registration), and in 3.3 those three were
  served through Bifrost, not Jungle.
- This Jungle's registry was empty (0 servers, 0 tools in its Postgres) before this registration.

## Out of scope
Jinja2/AST codegen, LLM slot filling, certify, FastMCP server deploy (all 4.0 track).
