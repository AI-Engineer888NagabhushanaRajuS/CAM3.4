# SPEC-011: Baseline Repair (green test suite, honest status)

**Status:** COMPLETED
**Branch:** `feat/spec-011-baseline-repair`
**Depends on:** SPEC-001..010

## Why
SPEC-001..010 were marked complete, but the suite had 14 failures and no `v3.3-baseline` tag existed.

## Root causes fixed
| # | Cause | Fix |
|---|-------|-----|
| 1 | `temporal_worker/`, `fastapi-router/`, reporting each ship a flat `config.py`; first import won in `sys.modules` (9 failures) | autouse `_isolate_source_dir` fixture in `testing/conftest.py`: per-module source dir first on `sys.path`, stale modules purged |
| 2 | Mock Temporal activities lacked `@activity.defn` (4) | decorate mocks with `name="get_routing_sequence"` / `"execute_tool"` |
| 3 | HITL client mock used `AsyncMock` for sync `Client.get_workflow_handle` (2) | `MagicMock` client |
| 4 | Test used private `FastMCP._tool_manager` (removed in fastmcp 3.4.2) (1) | public `await mcp.list_tools()` |
| 5 | Test asserted `_build_rfq_context`, removed on purpose in SPEC-008 (1) | assert helper absent + no `rfq_lit` f-string SQL |
| 6 | `asyncio.get_event_loop().run_until_complete` (deprecated, broke after `asyncio.run`) | `asyncio.run` |
| 7 | `pytest` from repo root failed (`from conftest import`) | `pytest.ini` moved to repo root, `pythonpath = testing` |

## Also
- Tag `v3.3-baseline` -> `4c090da` (SPEC-001 baseline commit).
- SPEC-001..006 status lines reconciled with `progress.json`.
- Old agent's uncommitted WIP (chat/Temporal wiring, 12 files) committed separately before this spec.

## Acceptance
`pytest` from `CAM-Source/` -> 87 passed, 3 skipped (shadow-run integration, needs live services), 0 failed.

## Known follow-ups (not in this spec)
- `fastapi-router/bom_qa_lookup_server.py:137` interpolates `rfq_id` into SQL (f-string); parameterize.
- Plaintext credentials in `setup_postgres.ps1` / `SECRETS.md`.
- Manifest pipeline (adapter, importer, registry writer, gateway registration, parity test) -> SPEC-012+.
