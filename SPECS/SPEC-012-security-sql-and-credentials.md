# SPEC-012 — Security: SQL hardening + credentials to env

**Status:** completed (see progress.json)
**Branch:** feat/spec-012-security (from feat/spec-011-baseline-repair)
**Depends on:** SPEC-011

## Context
Goal section 3 asks to parameterize every SQL statement that is built with an f-string from `rfq_id`, and to move credentials out of files. Findings from reading the code (2026-10-30):

- `fastapi-router/fastapi_router.py` (`rfq_id`, `profile_name`) and the four MCP servers (`intake`, `gerber-integration`, `scrub-intake`) already validate IDs with a `^[A-Za-z0-9_\-]+$` / `^[\w-]+$` check at entry. A hostile `rfq_id` cannot reach SQL there.
- The metadata tool (`Production_FileMetedata_DB-execute_sql`, `postgres_metadata__execute_sql`) is a remote MCP tool that accepts only a raw `sql` string (`fastapi-router/tool_calling.py:call_tool`). Its SQL cannot be parameterized from this repo.
- `intake/mcp_server.py` `scan_local_file` wrote `file_type`, `scan_status` and `file_id` into an UPDATE without escaping. `execution_logs` was already escaped with `''`.
- `docker-compose.yml` fell back to `changeme` for `POSTGRES_PASSWORD`.
- `setup_postgres.ps1` and `SECRETS.md` (both at `C:\CAM[3.4]-RFQ_centum\`, outside the git repo) contained the app and superuser passwords in plain text.
- A search of git history for the app-user password string returns nothing: the password was never committed to this repo.

## Scope
1. Escape `file_type`, `scan_status`, `file_id` in the intake telemetry UPDATE (same `''` rule already used for logs).
2. `docker-compose.yml`: `POSTGRES_PASSWORD` is required (`:?`), no `changeme` default.
3. `setup_postgres.ps1`: credentials read from `CAM_PG_APP_USER`, `CAM_PG_APP_PASSWORD`, `CAM_PG_SUPERUSER_PASSWORD`; script throws if unset; passwords no longer printed.
4. `SECRETS.md`: passwords replaced by env-var references.
5. `CAM-Source/.env.example` with placeholder values only.
6. `testing/test_sql_hardening.py`: hostile-ID rejection for the three MCP `_validate_id` functions.

## Acceptance
- Full `pytest` from CAM-Source root: all previous tests still pass; the new tests pass; the only skips are the three shadow-run tests (services not running).
- `git grep` finds no literal password in the repo.

## Tests
- `testing/test_sql_hardening.py::test_mcp_validate_id_rejects_hostile_rfq_id` (3 cases) — hostile strings: `CE-1'; DROP TABLE ...--`, `CE-1 OR 1=1`, NUL byte, `../etc/passwd`, `CE-1'`.
- The existing `test_security_fixes.py::test_sql_injection_blocked_by_identifier_validator` covers `fastapi_router._validate_sql_identifier`.

## Decisions (OPEN items, with the default I chose)
- **"Parameterize everywhere" is not achievable for the remote metadata tool.** Default: validate at entry (already done) and tighten the one unescaped path (item 1). Recorded as a constraint, not a claim of parameterization.
- **`rfq_lit` / `sql_quote` sites in `mcp-tools/reporting/superset/` (~70 sites)** are already escaped with `''` doubling. Default: leave them. A rewrite would not fix an injection that does not exist.
- **`bom_qa_lookup_server.py:137,148`** build SQL with f-strings after `_validate_sql_token`. `_run_query_raw` takes only a string. Default: leave; the validator is the guard.
- **Credential rotation:** the passwords were in plain text in local files on this machine. Default: not rotated by me. Flagged to Harish: rotate the app-user and `postgres` passwords before any shared use. Harish reports the live postgres, Bifrost and Temporal password is a different value from the one in `fastapi-router/.env`; that value must be confirmed and set via env vars, not written to any file.
- **Commit trailer:** the GOAL_PROMPT specifies `Co-Authored-By: Claude Sonnet 5.5`. Used as written.

## Out of scope
- `temporal_worker/activities.py:17` puts `rfq_id` into a URL path. Not SQL. SPEC-017 candidate.
- `accomplish-ui/` (not part of CAM 3.4 scope).
- Making `scan_local_file` directly testable (it needs ClamAV and two DB reads mocked). The escape change is covered by code review only; see Verification.

## Verification
- Escape edit in intake: covered by code review, no automated test. Not verified by execution.
