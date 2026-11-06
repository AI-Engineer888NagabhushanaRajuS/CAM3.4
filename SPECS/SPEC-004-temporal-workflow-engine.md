# SPEC-004: Temporal Workflow Engine (Replace Dify DMR)

**Status:** COMPLETED  
**Branch:** `feat/spec-004-temporal-orchestrator`  
**Commit target:** `feat: add Temporal workflow orchestrator as Dify DMR replacement`  
**Depends on:** SPEC-001, SPEC-002

## Context

Dify DMR (`dify-orchestration/Dify_DMR_RFQ_Flow.yml`) orchestrates the RFQ pipeline by:
1. Reading `routing_sequence` from PostgreSQL `quote_routing_profiles`
2. Looping over each tool in the sequence
3. Calling `POST /tool/execute` on `fastapi_router:5000` for each tool
4. Blocking on HITL gates via `hitl_router:5002`

The Dify YAML is a Docker-hosted workflow with HTTP request nodes + code nodes.
Its external interface: `upload_server.py` POSTs a trigger to Dify's workflow API.

**CAM 3.4 target**: Replace Dify with a Temporal workflow that does the same loop
but with durable execution, retry policies, and signal-based HITL.

**CRITICAL constraint**: `fastapi_router.py` POST `/tool/execute` contract is UNCHANGED.
Temporal calls the same endpoint that Dify calls. The tool layer is NOT touched.

## Architecture

```
BEFORE (3.3):
upload_server:3000 → POST /v1/workflows/run (Dify) → Dify loop → POST /tool/execute

AFTER (3.4):
upload_server:3000 → TemporalClient.start_workflow() → Temporal worker → POST /tool/execute
```

## What to Build

### 1. Install Temporal Python SDK

Add to `requirements.txt`:
```
temporalio>=1.7.0
```

Temporal server must be running (it's already in `docker-compose.yml` or can be added).
Use Temporal local dev server for testing: `temporal server start-dev --port 7233`

### 2. Create `temporal_worker/` directory

```
temporal_worker/
  __init__.py
  workflow.py        # RFQWorkflow definition
  activities.py      # Temporal activities (one per tool call type)
  worker.py          # Worker process entry point
  client.py          # TemporalClient wrapper for upload_server to call
  config.py          # TEMPORAL_HOST, TASK_QUEUE, NAMESPACE env vars
```

### 3. `temporal_worker/workflow.py` — the core workflow

```python
"""RFQ pipeline Temporal workflow — replaces Dify DMR.

Same logic as Dify_DMR_RFQ_Flow.yml but durable, testable, signal-aware.
"""
from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy
import activities

@workflow.defn
class RFQWorkflow:
    def __init__(self):
        self._hitl_decision = None
    
    @workflow.signal
    def human_decision(self, decision: dict):
        """Signal sent by hitl_router when user approves/rejects."""
        self._hitl_decision = decision
    
    @workflow.run
    async def run(self, rfq_id: str, profile_name: str) -> dict:
        """Execute the full RFQ pipeline for one rfq_id."""
        
        # 1. Get routing sequence from Postgres (same source as Dify)
        routing = await workflow.execute_activity(
            activities.get_routing_sequence,
            args=[rfq_id, profile_name],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        
        sequence = routing["routing_sequence"]  # list of tool dicts
        start_index = routing["skill_index"]    # resume point if re-triggered
        
        results = []
        for i, step in enumerate(sequence[start_index:], start=start_index):
            tool_name = step["tool_name"]
            
            # 2. Execute each tool via fastapi_router (UNCHANGED contract)
            result = await workflow.execute_activity(
                activities.execute_tool,
                args=[rfq_id, tool_name, step.get("arguments", {})],
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=RetryPolicy(
                    maximum_attempts=3,
                    backoff_coefficient=2.0,
                    maximum_interval=timedelta(seconds=30),
                ),
            )
            
            # 3. Check if HITL gate required
            if result.get("hitl_required"):
                # Wait for human_decision signal (no timeout — user must decide)
                await workflow.wait_condition(lambda: self._hitl_decision is not None)
                decision = self._hitl_decision
                self._hitl_decision = None  # reset for next gate
                
                if decision.get("action") == "reject":
                    return {"status": "rejected", "step": tool_name, "results": results}
            
            results.append({"tool": tool_name, "result": result})
        
        return {"status": "completed", "rfq_id": rfq_id, "results": results}
```

### 4. `temporal_worker/activities.py` — activities

```python
from temporalio import activity
import httpx

FASTAPI_ROUTER_URL = "http://localhost:5000"  # same target as Dify

@activity.defn
async def get_routing_sequence(rfq_id: str, profile_name: str) -> dict:
    """Fetch routing sequence from fastapi_router (same endpoint Dify calls)."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{FASTAPI_ROUTER_URL}/pipeline/routing-sequence/{rfq_id}/{profile_name}",
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

@activity.defn
async def execute_tool(rfq_id: str, tool_name: str, arguments: dict) -> dict:
    """POST /tool/execute — exact same call Dify makes. Contract UNCHANGED."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{FASTAPI_ROUTER_URL}/tool/execute",
            json={"rfq_id": rfq_id, "tool_name": tool_name, "arguments": arguments},
            timeout=600,  # 10 min max for heavy report generation
        )
        resp.raise_for_status()
        return resp.json()
```

### 5. `temporal_worker/worker.py` — the worker process

```python
import asyncio
from temporalio.client import Client
from temporalio.worker import Worker
from workflow import RFQWorkflow
import activities
import config

async def main():
    client = await Client.connect(config.TEMPORAL_HOST)
    worker = Worker(
        client,
        task_queue=config.TASK_QUEUE,
        workflows=[RFQWorkflow],
        activities=[activities.get_routing_sequence, activities.execute_tool],
    )
    print(f"[Temporal Worker] Starting on task queue '{config.TASK_QUEUE}'")
    await worker.run()

if __name__ == "__main__":
    asyncio.run(main())
```

### 6. `temporal_worker/client.py` — trigger helper for upload_server

```python
"""Called by upload_server.py to start a workflow instead of calling Dify."""
import asyncio
from temporalio.client import Client
import config

async def start_rfq_workflow(rfq_id: str, profile_name: str = "Standard_BOM_Flow") -> str:
    """Start an RFQ workflow and return the workflow ID."""
    client = await Client.connect(config.TEMPORAL_HOST)
    handle = await client.start_workflow(
        "RFQWorkflow",
        args=[rfq_id, profile_name],
        id=f"rfq-{rfq_id}",  # idempotent: same rfq_id = same workflow
        task_queue=config.TASK_QUEUE,
    )
    return handle.id

async def send_hitl_signal(workflow_id: str, decision: dict):
    """Send human_decision signal to a waiting workflow."""
    client = await Client.connect(config.TEMPORAL_HOST)
    handle = client.get_workflow_handle(workflow_id)
    await handle.signal("human_decision", decision)
```

### 7. Modify `upload_server.py` — add Temporal path (parallel with Dify)

Add a `USE_TEMPORAL` env var. When `True`, call `temporal_client.start_rfq_workflow()` instead of Dify.
Keep the Dify path working for the shadow-run parallel comparison (Step 4 of the migration plan).

```python
# In upload_server.py, replace the Dify call section:
import os
USE_TEMPORAL = os.getenv("CAM_USE_TEMPORAL", "false").lower() == "true"

if USE_TEMPORAL:
    from temporal_worker import client as temporal_client
    workflow_id = asyncio.run(temporal_client.start_rfq_workflow(rfq_id))
    return {"workflow_id": workflow_id, "engine": "temporal"}
else:
    # existing Dify call (unchanged)
    ...
```

### 8. Modify `hitl_router.py` — add Temporal signal path

When HITL is resolved, instead of just advancing `rfq_process_stage` in Postgres,
also send a Temporal signal to the waiting workflow.

```python
# In hitl_router.py, in the endpoint that resolves conflicts:
if USE_TEMPORAL:
    workflow_id = f"rfq-{rfq_id}"
    asyncio.run(temporal_client.send_hitl_signal(workflow_id, {"action": "approve"}))
```

### 9. Add Temporal to `docker-compose.yml`

```yaml
temporal:
  image: temporalio/auto-setup:1.32.1
  ports:
    - "7233:7233"
    - "8088:8080"  # Temporal Web UI (avoid conflict with Superset:8088)
  environment:
    - DB=sqlite
  volumes:
    - temporal_data:/etc/temporal
```

### 10. Add Temporal worker to `manage_backend.py`

Add a `temporal_worker` service entry in the SERVICES dict:
```python
"temporal_worker": {
    "cmd": [sys.executable, "-m", "temporal_worker.worker"],
    "cwd": REPO_ROOT,
    "port": None,  # no HTTP port
    "health_check": None,  # ping Temporal server instead
}
```

## Files to Create/Modify

- `temporal_worker/__init__.py` (new)
- `temporal_worker/workflow.py` (new)
- `temporal_worker/activities.py` (new)
- `temporal_worker/worker.py` (new)
- `temporal_worker/client.py` (new)
- `temporal_worker/config.py` (new)
- `fastmcp-router/upload_server.py` (add USE_TEMPORAL flag)
- `fastmcp-router/hitl_router.py` (add signal path)
- `fastmcp-router/manage_backend.py` (add temporal_worker service)
- `docker-compose.yml` (add Temporal service)
- `requirements.txt` (add temporalio)

## Acceptance Criteria

1. `python temporal_worker/worker.py` starts without errors (Temporal server must be running)
2. `CAM_USE_TEMPORAL=true python fastmcp-router/upload_server.py` starts and accepts uploads
3. With Temporal running: triggering an RFQ creates a visible workflow in Temporal Web UI
4. The workflow calls `POST /tool/execute` at least once (verifiable in fastapi_router logs)
5. `python -m pytest tests/test_temporal_workflow.py -v` passes basic workflow unit tests
6. All files committed to `feat/spec-004-temporal-orchestrator` branch

## Shadow-Run Comparison Test

Create `tests/test_temporal_workflow.py`:
```python
# Test that Temporal workflow calls the same sequence of tools as Dify would
# Use mocked activities to capture what tools were called and in what order
# Compare against expected routing_sequence from Postgres

def test_temporal_calls_same_tools_as_dify(mock_activities):
    # Load routing_sequence for "Standard_BOM_Flow" from config
    # Run workflow with mocked activities
    # Assert tools were called in sequence order from routing_sequence
    ...
```

## Temporal Version

Use `temporalio>=1.7.0` (Python SDK). The Temporal server image `temporalio/auto-setup:1.32.1`
is already referenced in the tech stack docs. The TASK_QUEUE should be `"cam-rfq-pipeline"`.
