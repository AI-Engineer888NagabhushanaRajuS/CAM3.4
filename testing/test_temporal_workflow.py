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
        assert config.FASTAPI_ROUTER_URL == "http://localhost:5000"
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
            {"tool_name": "centum_intake__standardize_scrub_bom", "arguments": {}},
            {"tool_name": "centum_reporting__cbom", "arguments": {}},
        ],
        "skill_index": 0,
    }
    mock_tool_result = {"status": "success", "hitl_required": False}

    called_tools = []

    async def mock_get_routing(rfq_id, profile_name):
        return mock_routing

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

    asyncio.get_event_loop().run_until_complete(run())


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
            {"tool_name": "centum_reporting__resolve_final_selection", "arguments": {}},
            {"tool_name": "centum_reporting__generate_reports", "arguments": {}},
        ],
        "skill_index": 0,
    }

    call_count = [0]

    async def mock_get_routing(rfq_id, profile_name):
        return mock_routing

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

    asyncio.get_event_loop().run_until_complete(run())
