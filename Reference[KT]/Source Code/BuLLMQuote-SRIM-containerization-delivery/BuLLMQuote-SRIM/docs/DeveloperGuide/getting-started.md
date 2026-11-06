# Developer Guide: Getting Started

## Table of Contents

- [Local setup](#local-setup)
- [Running services](#running-services)
- [Testing](#testing)
- [Debugging](#debugging)
- [Known issues encountered during this platform's own development](#known-issues-encountered-during-this-platforms-own-development)
- [Troubleshooting checklist](#troubleshooting-checklist)
- [Related documents](#related-documents)

## Local setup

See [Deployment/deployment.md](../Deployment/deployment.md)'s "Development
setup" section for the full prerequisite list (Postgres, DuckDB files, MCP
Jungle, Ollama, Dify). This section covers day-to-day developer workflow
once that's in place.

## Running services

```
cd "centum intake"
python manage_backend.py start      # start everything
python manage_backend.py status     # one-shot health check
python manage_backend.py monitor --interval 5 --auto-restart   # continuous, auto-restart dead processes
python manage_backend.py restart    # stop + start
python manage_backend.py stop       # stop everything this script started
```

For `accomplish-ui`'s `apps/web` specifically, once dependencies are
installed (`pnpm install` at the workspace root):
```
pnpm --filter @accomplish/web dev      # dev server
pnpm --filter @accomplish/web run build   # production build (tsc + vite build)
pnpm --filter @accomplish/web run typecheck  # tsc only, no build
```

## Testing

`reporting_module` (see
[Reporting/reporting-module.md](../Reporting/reporting-module.md)) follows
a self-test convention: most modules can be run directly
(`python -m reports.<module_name>`) to execute an embedded self-test that
builds a small in-memory example and asserts on the generated formulas/
values — this is the primary regression-check mechanism for that module,
not a separate `pytest` suite. `centum intake`'s root also has a few
dedicated test scripts (`test_hierarchy_multiplier.py`,
`test_quote_win_processing.py`, `test_scrub_bom_processing.py` — see
[Backend/file-reference.md](../Backend/file-reference.md)).

`apps/web` uses Vitest (`pnpm test`, `pnpm test:unit`, `pnpm
test:integration`, `pnpm test:watch`) — a conventional JS test runner, in
contrast to the Python side's self-test-in-module pattern.

## Debugging

- `manage_backend.py status` is the fastest way to confirm which of the 10
  services (plus Postgres/Ollama/MCP Jungle) is actually the problem before
  digging into any single service's logs.
- Per-service logs: `centum intake\service_logs\`.
- For a stuck RFQ (Dify run seemingly not progressing), check
  `rfq_process_tracking.rfq_process_stage` and `hitl_required` directly
  (see [Database/logic-database.md](../Database/logic-database.md)) —
  `hitl_required = true` (or a `rfq_process_stage` that hasn't moved) means
  the pipeline is correctly halted awaiting human review, not broken; call
  `GET /api/dify/start/{rfq_id}` after resolving to resume.
- For a tool that appears skipped: `fastapi_router.py`'s `/tool/execute`
  gate re-checks the routing sequence on every call and silently skips
  tools not present in it — confirm the tool name is actually present in
  the target profile's `routing_sequence` (see
  [Database/logic-database.md](../Database/logic-database.md)) before
  assuming the tool itself is broken.

## Known issues encountered during this platform's own development

Real, concrete issues found and worked through while building and
documenting this platform (kept here rather than only in scattered code
comments, since they're the kind of thing that wastes real time if
rediscovered from scratch):

- **`duckdb` npm package fails to build natively on this machine.**
  `pnpm install` for `apps/web` succeeds overall, but the `duckdb` native
  postinstall script fails (`node-gyp` build error — no prebuilt binary for
  the installed Node version, and no native build toolchain available).
  Confirmed this doesn't block anything: `duckdb` is a declared dependency
  in `apps/web/package.json` but is not actually imported anywhere in that
  app's own source.
- **A `config.py` name collision** between `centum intake\config.py` (root)
  and `reporting_module\config.py` — two different files with the same
  module name. Any file that does `sys.path.insert(0, ".../reporting_module")`
  needs that insert to come AFTER the root directory in the insert order
  (last-`insert(0, ...)`-wins) so `import config` resolves to
  `reporting_module`'s version, not the root's. Get this wrong and you get
  a **silent** bug, not an import error: `bom_qa_lookup_server.py` was
  found to import successfully but crash with `AttributeError` at first
  real request, because it was quietly picking up the wrong `config.py`.
- **`reporting_module`'s own 3 local `.duckdb` files were stale/wrong
  data** — confirmed via file-hash and last-modified comparison against
  the real, actively-used files in `centum intake\database\`. Always
  verify which DuckDB files a given code path actually resolves to
  (`config.py`'s `REPORTING_DATABASE_DIR` override) rather than assuming a
  `.duckdb` file sitting next to the code is the live one.
- **Excel formula blank-guards**: when generating live Excel formulas
  (rather than static computed values) in `reporting_module`'s `reports/`
  builders, an `IFERROR()`-wraps-the-computation approach was tried first
  for handling blank/missing inputs and did NOT fix real `#VALUE!` errors
  in generated workbooks — only guarding the blank case explicitly BEFORE
  the computation (`IF(AND(...,$K<>""),...,"")` style, not
  `IFERROR($K*$I,"")` style) worked. This is the established pattern
  throughout `reporting_module`'s formula-generation code — see
  [Reporting/reporting-module.md](../Reporting/reporting-module.md) for
  the specific files this applies to.
- **`manage_backend.py`'s hardcoded absolute paths** break the moment any
  service is moved (as encountered directly while building the
  `BuLLMQuote-SRIM` consolidation repo) — copying a service's source files
  elsewhere does NOT make them independently runnable/manageable until
  every path reference is deliberately updated. See
  [Deployment/deployment.md](../Deployment/deployment.md).

## Troubleshooting checklist

1. `python manage_backend.py status` — is everything healthy?
2. Is the RFQ's `rfq_process_tracking` row where you expect
   (`rfq_process_stage`, `hitl_required`, `is_active`)?
3. Is the tool name you expect actually present in
   `quote_routing_profiles.routing_sequence` for the active profile, and is
   its `system_skills_registry` row `is_active = true`?
4. Is MCP Jungle actually reachable and does it have the expected backing
   server (`postgres-mcp`, plus whichever FastMCP server owns the tool in
   question) registered?
5. For DuckDB path issues: which `config.py` / `REPORTING_DATABASE_DIR`
   value is actually in effect for the process you're debugging?

## Related documents

- [Deployment/deployment.md](../Deployment/deployment.md)
- [Database/logic-database.md](../Database/logic-database.md)
- [DMR/dynamic-master-router.md](../DMR/dynamic-master-router.md)
- [Reporting/reporting-module.md](../Reporting/reporting-module.md)
