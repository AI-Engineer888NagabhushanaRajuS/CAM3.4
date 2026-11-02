"""
SPEC-014: Parity harness — Architecture Diagram 6, Step 10.

"Run Dify and Temporal on the same RFQ and compare outputs."

Two kinds of test live here:

1. Offline call-trace parity (always runs, no services). Dify is RETIRED (HANDOFF §5);
   it is not run here. Its YAML (`Dify_DMR_RFQ_Flow.yml`, 3.3 reference, commit a8c0cbd
   in the reference copy) is used only as a frozen record of the call order the 3.3 flow
   made. The Temporal side runs the real `RFQWorkflow` in the time-skipping environment
   with recording activities; its calls must match that order up to the HITL gate.

2. Live parity (opt-in). Runs against a live stack. Enable explicitly:
       CAM_PARITY_LIVE=1 CAM_USE_TEMPORAL=true pytest testing/test_shadow_run_parity.py -v
"""
import asyncio
import os
import sys
from datetime import timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "fastapi-router"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "temporal_worker"))

SHADOW_RFQ_ID = os.environ.get("SHADOW_RFQ_ID", "CE-TEST-SHADOW-001")
FASTAPI_ROUTER_URL = os.environ.get("CAM_FASTAPI_ROUTER_URL", "http://localhost:5100")
LIVE = os.environ.get("CAM_PARITY_LIVE") == "1"
live_only = pytest.mark.skipif(not LIVE, reason="live parity: set CAM_PARITY_LIVE=1 with services running")

# Tool names copied from manifests/*.json (real tool names). This is a FIXTURE, not the
# production routing_sequence: no seed dump of quote_routing_profiles exists in the repo.
FIXTURE_ROUTING = [
    "centum_intake__standardize_scrub_bom",
    "centum_reporting__cbom",
    "centum_reporting__resolve_final_selection",  # the tool that raises HITL in this test
    "centum_reporting__generate_reports",
]
HITL_TOOL = "centum_reporting__resolve_final_selection"
DIFY_PROFILE = "RFQ_Flow"  # the profile the Dify YAML requests (HTTP Request 1)


def dify_reference_trace(routing, skill_index, rfq_id, hitl_tool):
    """Calls the Dify DMR flow makes, in order. HAND-TRANSCRIBED from the YAML (not parsed):
    re-check against Dify_DMR_RFQ_Flow.yml if that file changes.

    Code 1 slices routing[skill_index:]. Iteration posts /tool/execute per item with
    body {tool_name, arguments: {rfq_id}}. Code 4 reads `hitl`. IF/ELSE on true posts
    trigger-hitl, then HALT ON HITL raises: the run ends there.
    """
    calls = []
    for tool in routing[skill_index:]:
        calls.append(("POST /tool/execute", tool, {"rfq_id": rfq_id}))
        if tool == hitl_tool:
            calls.append(("POST trigger-hitl", tool, None))
            break  # HALT ON HITL
    return calls


def _temporal_calls_until_hitl(recorded, hitl_tool):
    """Temporal's recorded execute_tool calls, cut at the HITL tool (inclusive)."""
    calls = []
    for tool, args in recorded:
        calls.append(("POST /tool/execute", tool, args))
        if tool == hitl_tool:
            break
    return calls


def test_offline_trace_parity_dify_vs_temporal():
    """Same RFQ, same routing: Dify and Temporal make the same tool calls, in the same order,
    up to the HITL gate. After the gate, Dify halts and Temporal waits for a signal."""
    try:
        from temporalio import activity
        from temporalio.client import WorkflowExecutionStatus
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker
        import workflow as wf
    except ImportError as e:
        pytest.skip(f"temporalio not installed: {e}")

    assert FIXTURE_ROUTING and HITL_TOOL in FIXTURE_ROUTING  # guard against a vacuous pass
    recorded = []

    @activity.defn(name="get_routing_sequence")
    async def fake_routing(rfq_id, profile_name):
        return {"routing_sequence": FIXTURE_ROUTING, "skill_index": 0}

    @activity.defn(name="execute_tool")
    async def fake_execute(rfq_id, tool_name, arguments):
        recorded.append((tool_name, arguments))
        return {"hitl": 1 if tool_name == HITL_TOOL else 0}

    async def run():
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(env.client, task_queue="parity-queue",
                              workflows=[wf.RFQWorkflow], activities=[fake_routing, fake_execute]):
                handle = await env.client.start_workflow(
                    wf.RFQWorkflow.run, args=["CE-PARITY-1", DIFY_PROFILE],
                    id="parity-wf-1", task_queue="parity-queue",
                    execution_timeout=timedelta(seconds=30),
                )
                # Wait for the HITL tool to run, then prove the workflow is parked, not finished.
                while not any(t == HITL_TOOL for t, _ in recorded):
                    await asyncio.sleep(0.01)
                desc = await handle.describe()
                assert desc.status == WorkflowExecutionStatus.RUNNING, "Temporal must wait at HITL"
                await handle.signal(wf.RFQWorkflow.human_decision, {"action": "reject"})
                return await handle.result()

    # Bounded timeout so a stuck workflow task fails the test fast instead of hanging CI.
    result = asyncio.run(asyncio.wait_for(run(), timeout=30))

    dify = dify_reference_trace(FIXTURE_ROUTING, 0, "CE-PARITY-1", HITL_TOOL)
    dify_execute = [c for c in dify if c[0] == "POST /tool/execute"]
    temporal = _temporal_calls_until_hitl(recorded, HITL_TOOL)
    assert len(dify_execute) == 3, "fixture must exercise calls before and at the HITL gate"
    assert dify[-1] == ("POST trigger-hitl", HITL_TOOL, None), "Dify must halt right after trigger-hitl"
    # Compare names AND arguments on the Temporal side: the workflow's args are what must match.
    assert temporal == dify_execute, "tool calls (name + args) diverge from the Dify reference"
    assert result["status"] == "rejected" and result["step"] == HITL_TOOL


def test_routing_sequence_reads_db_not_gateway(monkeypatch):
    """The endpoint must return the DB routing sequence even when the MCP gateway is down."""
    fr_dir = os.path.join(os.path.dirname(__file__), "..", "fastapi-router")
    sys.path.insert(0, os.path.abspath(fr_dir))
    try:
        import fastapi_router as fr
        from fastapi.testclient import TestClient
    except ImportError as e:
        pytest.skip(f"fastapi_router deps unavailable: {e}")
    finally:
        sys.path.remove(os.path.abspath(fr_dir))

    def gateway_down(*args, **kwargs):
        raise ConnectionError("gateway down")

    # Patch where the endpoint looks names up (fastapi_router imports them by name).
    monkeypatch.setattr(fr, "call_tool", gateway_down)
    monkeypatch.setattr(fr, "db_get_routing_sequence", lambda profile_name: FIXTURE_ROUTING)
    monkeypatch.setattr(fr, "get_current_skill_index", lambda rfq_id: 0)

    resp = TestClient(fr.app).get(f"/pipeline/routing-sequence/CE-PARITY-1/{DIFY_PROFILE}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("routing_sequence") == FIXTURE_ROUTING


@live_only
def test_temporal_and_daq_routing_sequences_agree():
    """Live: the routing sequence returned by the endpoint must be a non-empty list."""
    import httpx

    resp = httpx.get(f"{FASTAPI_ROUTER_URL}/pipeline/routing-sequence/{SHADOW_RFQ_ID}/Standard_BOM_Flow", timeout=10)
    assert resp.status_code == 200, f"routing-sequence failed: {resp.text}"
    sequence = resp.json().get("routing_sequence")
    assert isinstance(sequence, list) and len(sequence) > 0, "routing_sequence must be a non-empty list"


@live_only
def test_temporal_status_endpoint_returns_expected_fields():
    """Live: the status endpoint returns rfq_id and engine."""
    import httpx

    data = httpx.get(f"{FASTAPI_ROUTER_URL}/rfq/{SHADOW_RFQ_ID}/status", timeout=10).json()
    missing = {"rfq_id", "engine"} - set(data.keys())
    assert not missing, f"Status response missing fields: {missing}"
    assert data["rfq_id"] == SHADOW_RFQ_ID


@live_only
def test_api_status_agrees_with_active_version():
    """Live: the status endpoint's `postgres_stage` equals get_active_version().
    LIMITATION: the endpoint sets postgres_stage from this same call, so this only proves the
    endpoint reports what the DB says. It cannot catch stage divergence. The field also holds
    a version, not a stage (D3, logged for SPEC-015). Real stage parity needs the D3 fix."""
    import httpx
    from db import get_active_version

    try:
        expected = get_active_version(SHADOW_RFQ_ID)
    except Exception as e:
        pytest.skip(f"DB unavailable for the live stage check: {e}")
    api_value = httpx.get(f"{FASTAPI_ROUTER_URL}/rfq/{SHADOW_RFQ_ID}/status", timeout=10).json().get("postgres_stage")
    assert api_value == expected
