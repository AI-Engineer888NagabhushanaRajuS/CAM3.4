"""
Temporal workflow unit tests using mocked activities.
Tests that RFQWorkflow calls tools in the correct sequence and handles HITL gates.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "temporal_worker"))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Pure-logic tests (no Temporal SDK needed)
# ---------------------------------------------------------------------------

def test_workflow_module_imports():
    """workflow.py must import without error (even without Temporal running)."""
    try:
        import workflow as wf
        assert hasattr(wf, "RFQWorkflow")
    except ImportError as e:
        pytest.skip(f"temporalio not installed: {e}")


def test_activities_module_imports():
    """activities.py must import without error."""
    try:
        import activities as act
        assert hasattr(act, "get_routing_sequence")
        assert hasattr(act, "execute_tool")
    except ImportError as e:
        pytest.skip(f"temporalio not installed: {e}")


def test_client_module_imports():
    """client.py must import without error."""
    try:
        import client as tc
        assert hasattr(tc, "start_rfq_workflow")
        assert hasattr(tc, "send_hitl_signal")
        assert hasattr(tc, "get_workflow_id")
    except ImportError as e:
        pytest.skip(f"temporalio not installed: {e}")


def test_config_defaults():
    """config.py must have expected defaults."""
    try:
        import config
        assert config.TEMPORAL_HOST == "localhost:7233"
        assert config.TASK_QUEUE == "cam-rfq-pipeline"
        assert config.NAMESPACE == "default"
        assert config.FASTAPI_ROUTER_URL == "http://localhost:5100"  # D5: router listens on 5100
    except ImportError as e:
        pytest.skip(f"temporalio not installed: {e}")


def test_get_workflow_id_deterministic():
    """get_workflow_id() must return a stable, deterministic ID for each rfq_id."""
    try:
        import client as tc
        wid1 = tc.get_workflow_id("RFQ-001")
        wid2 = tc.get_workflow_id("RFQ-001")
        wid3 = tc.get_workflow_id("RFQ-002")
        assert wid1 == wid2
        assert wid1 != wid3
        assert "RFQ-001" in wid1
    except ImportError as e:
        pytest.skip(f"temporalio not installed: {e}")


# ---------------------------------------------------------------------------
# Temporal SDK integration tests (require temporalio installed)
# ---------------------------------------------------------------------------

def test_temporal_workflow_calls_tools_in_sequence():
    """RFQWorkflow.run() must call execute_tool for each step in routing_sequence."""
    try:
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker
        import asyncio
        import workflow as wf
        import activities as act
    except ImportError as e:
        pytest.skip(f"temporalio not installed: {e}")

    mock_routing = {
        "routing_sequence": [
            "centum_intake__standardize_scrub_bom",
            "centum_reporting__cbom",
        ],
        "skill_index": 0,
    }
    mock_tool_result = {"status": "success", "hitl_required": False}

    called_tools = []

    from temporalio import activity

    @activity.defn(name="get_routing_sequence")
    async def mock_get_routing(rfq_id, profile_name):
        return mock_routing

    @activity.defn(name="execute_tool")
    async def mock_execute_tool(rfq_id, tool_name, arguments):
        called_tools.append(tool_name)
        return mock_tool_result

    async def run():
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue="test-queue",
                workflows=[wf.RFQWorkflow],
                activities=[mock_get_routing, mock_execute_tool],
            ):
                result = await env.client.execute_workflow(
                    wf.RFQWorkflow.run,
                    args=["TEST-RFQ-001", "Standard_BOM_Flow"],
                    id="test-workflow-001",
                    task_queue="test-queue",
                )

        assert result["status"] == "completed"
        assert result["rfq_id"] == "TEST-RFQ-001"
        assert called_tools == [
            "centum_intake__standardize_scrub_bom",
            "centum_reporting__cbom",
        ]

    asyncio.run(run())


def test_temporal_workflow_hitl_gate_blocks_until_signal():
    """When a tool returns hitl_required=True, workflow must wait for human_decision signal."""
    try:
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker
        import asyncio
        import workflow as wf
    except ImportError as e:
        pytest.skip(f"temporalio not installed: {e}")

    mock_routing = {
        "routing_sequence": [
            "centum_reporting__resolve_final_selection",
            "centum_reporting__generate_reports",
        ],
        "skill_index": 0,
    }

    call_count = [0]

    from temporalio import activity

    @activity.defn(name="get_routing_sequence")
    async def mock_get_routing(rfq_id, profile_name):
        return mock_routing

    @activity.defn(name="execute_tool")
    async def mock_execute_tool(rfq_id, tool_name, arguments):
        call_count[0] += 1
        if tool_name == "centum_reporting__resolve_final_selection":
            return {"status": "hitl_gate", "hitl": 1, "hitl_required": True}
        return {"status": "success"}

    async def run():
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue="test-queue-hitl",
                workflows=[wf.RFQWorkflow],
                activities=[mock_get_routing, mock_execute_tool],
            ):
                handle = await env.client.start_workflow(
                    wf.RFQWorkflow.run,
                    args=["TEST-RFQ-HITL", "Standard_BOM_Flow"],
                    id="test-workflow-hitl",
                    task_queue="test-queue-hitl",
                )
                # Send approve signal (simulates hitl_router.py)
                await handle.signal(wf.RFQWorkflow.human_decision, {"action": "approve"})
                result = await handle.result()

        assert result["status"] == "completed"
        assert call_count[0] == 2  # both tools called

    asyncio.run(run())


def test_routing_sequence_error_body_raises_not_empty_success():
    """The router returns HTTP 200 + {"error": ...} on a failed lookup. The activity must
    raise, so the workflow never reports an empty 'completed' run."""
    import asyncio
    import activities as act

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"error": "RFQ 'CE-X' not found"}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, timeout):
            return _Resp()

    with patch.object(act.httpx, "AsyncClient", _Client):
        with pytest.raises(RuntimeError, match="not found"):
            asyncio.run(act.get_routing_sequence("CE-X", "RFQ_Flow"))


def test_start_rfq_workflow_refuses_to_mask_a_running_run(monkeypatch):
    """The workflow ID is per RFQ. A second start while a run is still running must raise,
    not return the old ID: a new upload version must never be reported as triggered."""
    import asyncio
    from temporalio.exceptions import WorkflowAlreadyStartedError
    from temporalio.testing import WorkflowEnvironment
    import client as tc

    async def run():
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async def fake_connect(*args, **kwargs):
                return env.client

            monkeypatch.setattr(tc.Client, "connect", fake_connect)
            # No worker is started, so the workflow stays RUNNING, like a run parked at HITL.
            first = await tc.start_rfq_workflow("CE-IDEM-1", "RFQ_Flow")
            assert first == "rfq-CE-IDEM-1"
            with pytest.raises(WorkflowAlreadyStartedError):
                await tc.start_rfq_workflow("CE-IDEM-1", "RFQ_Flow")

    asyncio.run(run())


def test_get_workflow_status_reads_the_sdk_description_fields():
    """temporalio's WorkflowExecutionDescription exposes the id as `id`, not `workflow_id`."""
    import asyncio
    from unittest.mock import MagicMock
    import client as tc

    fake_desc = MagicMock(spec=["id", "run_id", "status"])
    fake_desc.id = "rfq-CE-STATUS-1"
    fake_desc.run_id = "run-1"
    fake_desc.status = "RUNNING"
    handle = MagicMock()

    async def describe():
        return fake_desc

    handle.describe = describe
    client_obj = MagicMock()
    client_obj.get_workflow_handle.return_value = handle

    async def fake_connect(*a, **k):
        return client_obj

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(tc.Client, "connect", fake_connect)
        out = asyncio.run(tc.get_workflow_status("CE-STATUS-1"))
    assert out["workflow_id"] == "rfq-CE-STATUS-1"


def test_failed_tool_status_fails_the_workflow():
    """The router answers HTTP 200 with status "failed" when a tool fails. That must fail the
    workflow, not let it complete with every step silently skipped."""
    import asyncio
    from datetime import timedelta
    from temporalio import activity
    from temporalio.client import WorkflowFailureError
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker
    import workflow as wf

    @activity.defn(name="get_routing_sequence")
    async def routing(rfq_id, profile_name):
        return {"routing_sequence": ["centum_reporting__cbom"], "skill_index": 0}

    @activity.defn(name="execute_tool")
    async def failing_tool(rfq_id, tool_name, arguments):
        return {"status": "failed", "error": "boom"}

    async def run():
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(env.client, task_queue="fail-queue", workflows=[wf.RFQWorkflow],
                              activities=[routing, failing_tool]):
                handle = await env.client.start_workflow(
                    wf.RFQWorkflow.run, args=["CE-FAIL-1", "Standard_BOM_Flow"],
                    id="fail-wf-1", task_queue="fail-queue",
                    execution_timeout=timedelta(seconds=60),
                )
                with pytest.raises(WorkflowFailureError):
                    await handle.result()

    asyncio.run(run())
