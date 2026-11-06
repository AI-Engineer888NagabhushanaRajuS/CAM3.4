# SPEC-005: HITL via Temporal Signals (Replace Sidecar Router)

**Status:** COMPLETED  
**Branch:** `feat/spec-005-hitl-temporal-signals`  
**Commit target:** `feat: replace HITL sidecar router with Temporal workflow signals`  
**Depends on:** SPEC-004

## Context

CAM 3.3's HITL mechanism uses `hitl_router.py` (:5002) as a sidecar server. When the
reporting module detects a conflict (supplier selection ambiguity), it writes to
`Postgres.final_selection_conflicts` and calls `set_hitl_required()` in `db.py`.
The `fastapi_router.py` checks this flag after each tool call and blocks further routing
by not advancing `rfq_process_stage`.

The user sees HITL requests via SSE notifications in accomplish-ui. They resolve them by
calling `hitl_router` endpoints which advance `rfq_process_stage` in Postgres.

**Known issues in current HITL:**
- `unified_quote_package.approved_by` not wired (UUID vs VARCHAR mismatch, noted in hitl_router.py)
- `rfq_id` scheme mismatch between UUID-typed `rfq_master.rfq_id` and VARCHAR "CE-005570" IDs
- Sidecar must be running for HITL to work (adds another service to manage)
- No audit trail of HITL decisions beyond Postgres row updates

**CAM 3.4 target:** HITL becomes a Temporal workflow signal. The workflow parks at
`workflow.wait_condition(lambda: self._hitl_decision is not None)` until the user acts.
The hitl_router.py sends a Temporal signal instead of just advancing Postgres stage.

## What to Build

### 1. Extend `temporal_worker/client.py` with HITL signal support

This was partially defined in SPEC-004. Complete it:

```python
async def send_hitl_approve(rfq_id: str, resolution: dict) -> bool:
    """Approve a HITL gate — unblocks the workflow to continue."""
    client = await Client.connect(config.TEMPORAL_HOST)
    handle = client.get_workflow_handle(f"rfq-{rfq_id}")
    await handle.signal("human_decision", {"action": "approve", **resolution})
    return True

async def send_hitl_reject(rfq_id: str, reason: str) -> bool:
    """Reject a HITL gate — terminates the workflow."""
    client = await Client.connect(config.TEMPORAL_HOST)
    handle = client.get_workflow_handle(f"rfq-{rfq_id}")
    await handle.signal("human_decision", {"action": "reject", "reason": reason})
    return True

async def get_workflow_status(rfq_id: str) -> dict:
    """Get current workflow status — running, paused at HITL, completed, failed."""
    client = await Client.connect(config.TEMPORAL_HOST)
    handle = client.get_workflow_handle(f"rfq-{rfq_id}")
    desc = await handle.describe()
    return {
        "status": str(desc.status),
        "workflow_id": desc.workflow_id,
        "run_id": desc.run_id,
    }
```

### 2. Modify `hitl_router.py` — add Temporal signal path

The existing `hitl_router.py` has two key HITL gates:
- `resolve_final_selection` (supplier conflict resolution)
- `detect_alternates` (alternate part approval)

For each gate's approval endpoint, add the Temporal signal call:

```python
# In hitl_router.py, import temporal client
import os
USE_TEMPORAL = os.getenv("CAM_USE_TEMPORAL", "false").lower() == "true"

# In the resolve_final_selection approval endpoint:
@app.post("/hitl/resolve-conflict/{rfq_id}")
async def resolve_conflict(rfq_id: str, resolution: ConflictResolution):
    # Keep existing Postgres writes (advance rfq_process_stage)
    _advance_past_resolve_final_selection(rfq_id)
    
    # NEW: Also send Temporal signal if Temporal is active
    if USE_TEMPORAL:
        from temporal_worker import client as tc
        import asyncio
        asyncio.run(tc.send_hitl_approve(rfq_id, {
            "gate": "resolve_final_selection",
            "resolution": resolution.dict()
        }))
    
    return {"status": "resolved", "rfq_id": rfq_id}
```

### 3. Add HITL status endpoint to `fastapi_router.py`

Add `GET /rfq/{rfq_id}/status` that returns both Postgres stage AND Temporal workflow status:

```python
@app.get("/rfq/{rfq_id}/status")
async def get_rfq_status(rfq_id: str):
    """Unified RFQ status: combines Postgres stage + Temporal workflow status."""
    # Get Postgres stage (existing)
    stage = get_active_version(rfq_id)  # or similar function from db.py
    
    # Get Temporal status (new)
    temporal_status = None
    if USE_TEMPORAL:
        try:
            from temporal_worker import client as tc
            import asyncio
            temporal_status = asyncio.run(tc.get_workflow_status(rfq_id))
        except Exception as e:
            temporal_status = {"error": str(e)}
    
    # Check for pending HITL from Postgres
    hitl_required = check_hitl_required(rfq_id)  # from db.py
    
    return {
        "rfq_id": rfq_id,
        "postgres_stage": stage,
        "temporal": temporal_status,
        "hitl_required": hitl_required,
        "engine": "temporal" if USE_TEMPORAL else "dify",
    }
```

### 4. Fix the UUID/VARCHAR mismatch in `hitl_router.py`

The existing comment says:
> `unified_quote_package.rfq_id` and `rfq_master.rfq_id` are both UUID, keyed off `rfq_master.rfq_number`,
> and no `rfq_master` row exists for the VARCHAR-style rfq_id scheme`

Fix: the `approved_by` write is non-critical (HITL still works without it). But fix the
lookup to not fail:

```python
# In hitl_router.py _advance_past_resolve_final_selection:
# Wrap the unified_quote_package write in a try/except and log the failure
# instead of letting it raise -- the routing advancement must still happen.
try:
    _write_approval_to_unified_quote_package(rfq_id, approved_by)
except Exception as e:
    print(f"[HITL] approved_by write skipped (UUID mismatch): {e}")
    # Non-fatal: routing advancement proceeds normally
```

### 5. Temporal history as HITL audit trail

Each HITL decision is automatically recorded in Temporal workflow history (event log).
Add an endpoint to retrieve HITL decisions from Temporal history:

```python
# In hitl_router.py or fastapi_router.py:
@app.get("/rfq/{rfq_id}/audit-trail")
async def get_audit_trail(rfq_id: str):
    """Returns HITL decisions from Temporal workflow history."""
    if not USE_TEMPORAL:
        return {"error": "Temporal not enabled"}
    
    client = await Client.connect(config.TEMPORAL_HOST)
    handle = client.get_workflow_handle(f"rfq-{rfq_id}")
    history_events = []
    async for event in handle.fetch_history_events():
        if "SignalExternalWorkflowExecutionInitiated" in str(event.event_type) or \
           "WorkflowExecutionSignaled" in str(event.event_type):
            history_events.append({
                "type": str(event.event_type),
                "timestamp": str(event.event_time),
            })
    return {"rfq_id": rfq_id, "hitl_events": history_events}
```

### 6. Tests for HITL signal flow

Create `tests/test_hitl_signals.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch

async def test_hitl_approve_sends_temporal_signal(mock_temporal_client):
    """Approving a conflict sends the human_decision signal to the workflow."""
    with patch("temporal_worker.client.Client.connect") as mock_connect:
        handle = AsyncMock()
        mock_connect.return_value.get_workflow_handle.return_value = handle
        
        from temporal_worker.client import send_hitl_approve
        await send_hitl_approve("CE-005570", {"supplier": "ARROW", "cpn": "CPN-001"})
        
        handle.signal.assert_called_once_with(
            "human_decision",
            {"action": "approve", "supplier": "ARROW", "cpn": "CPN-001"}
        )

async def test_workflow_resumes_after_hitl_signal(temporal_env):
    """Workflow that paused at HITL gate resumes after signal."""
    # Use temporalio testing framework (TestWorkflowEnvironment)
    from temporalio.testing import WorkflowEnvironment
    from temporal_worker.workflow import RFQWorkflow
    
    async with await WorkflowEnvironment.start_time_skipping() as env:
        handle = await env.client.start_workflow(RFQWorkflow.run, ...)
        # Send signal
        await handle.signal(RFQWorkflow.human_decision, {"action": "approve"})
        result = await handle.result()
        assert result["status"] == "completed"
```

## Files to Create/Modify

- `temporal_worker/client.py` (extend with HITL signal functions)
- `fastmcp-router/hitl_router.py` (add Temporal signal path, fix UUID mismatch)
- `fastmcp-router/fastapi_router.py` (add `/rfq/{rfq_id}/status` endpoint)
- `tests/test_hitl_signals.py` (new)

## Acceptance Criteria

1. `POST /hitl/resolve-conflict/{rfq_id}` with `CAM_USE_TEMPORAL=true` sends a Temporal signal
2. The Temporal workflow's `wait_condition` is unblocked when signal arrives
3. UUID/VARCHAR mismatch in `hitl_router.py` no longer causes a 500 error
4. `GET /rfq/{rfq_id}/status` returns both Postgres stage and Temporal workflow status
5. `python -m pytest tests/test_hitl_signals.py -v` passes
6. All files committed to `feat/spec-005-hitl-temporal-signals` branch

## Domain Context

HITL gate 1: `resolve_final_selection` — when multiple suppliers quoted the same part,
a human must pick the winner. This occurs after `centum_reporting__resolve_final_selection`
writes conflict rows to `Postgres.final_selection_conflicts`.

HITL gate 2: `detect_alternates` — when the intake tool finds a CPN with multiple MPNs
(alternate sources), a human must confirm which to use. This is triggered by
`centum_intake__detect_alternates` (in `mcp-tools/intake/detect_alternates.py`).

In both cases: human acts in accomplish-ui → HITL endpoint called → Temporal signal sent →
workflow resumes → next tool in routing_sequence executes.
