# SPEC-007 — Security Fixes + Temporal Default

## Branch
`feat/spec-007-security-temporal-default`

## Why
Architecture diagrams (Diagram 5, Diagram 6) mandate Temporal as the 3.4 default path.
Three critical/high defects discovered in gap audit must be fixed before any new features land:
1. Dead HITL webhook in daemon fires HTTP to a route that doesn't exist
2. SQL injection in fastapi_router routing-sequence and status endpoints
3. Temporal still defaults to disabled (USE_TEMPORAL=false) — Dify is still the happy path

## Scope (files to change)

### 1. Fix dead HITL webhook — `accomplish-ui/apps/daemon/src/browser-api-server.ts`
Around line 1022–1040: the daemon fires
`POST http://127.0.0.1:8000/api/orchestrator/resume` when HITL is approved/rejected.
That route does not exist in fastapi_router.py. The real routes are:
- `POST /rfq/{rfq_id}/hitl/approve`
- `POST /rfq/{rfq_id}/hitl/reject`
Fix: replace `ORCHESTRATOR_CALLBACK` construction and usage to call the correct routes.
The rfq_id must be extracted from the request body (it is already sent as part of the HITL payload).

### 2. Fix SQL injection — `fastapi-router/fastapi_router.py`
Two injection points:
a) The routing-sequence DuckDB query at ~line 171–180: uses f-string with rfq_id directly.
   Fix: use parameterized query `execute("SELECT ... WHERE rfq_id = ?", [rfq_id])`.
b) The status endpoint summary queries at ~lines 623, 628, 632: f-string interpolation of rfq_lit.
   Fix: same — parameterized, drop the rfq_lit variable.

### 3. Flip Temporal to default — `fastapi-router/upload_server.py`
Change:
```python
USE_TEMPORAL = os.environ.get("CAM_USE_TEMPORAL", "false").lower() == "true"
```
to:
```python
USE_TEMPORAL = os.environ.get("CAM_USE_TEMPORAL", "true").lower() == "true"
```
Also update the inline comment to say "Default: Temporal path (3.4). Set CAM_USE_TEMPORAL=false only for Dify fallback."

### 4. docker-compose.yml — ensure CAM_USE_TEMPORAL is not explicitly set to false
Scan `docker-compose.yml` for any `CAM_USE_TEMPORAL=false` env var and remove/flip.

## Tests
- `testing/test_security_fixes.py`: parameterized query test (try rfq_id = "CE-001'; DROP TABLE rfq_master--", verify no exception, verify DuckDB param is used)
- Extend `testing/test_upload_server.py` to assert USE_TEMPORAL defaults to True when env var absent

## Acceptance criteria
- `browser-api-server.ts`: no reference to `/api/orchestrator/resume`; correct route called
- `fastapi_router.py`: zero f-string SQL interpolation on user-supplied rfq_id
- `upload_server.py`: `os.environ.get("CAM_USE_TEMPORAL", "true")`
- All existing tests pass
