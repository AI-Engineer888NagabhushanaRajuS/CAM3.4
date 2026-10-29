"""
HITL signal flow tests for SPEC-005.
Tests that hitl_router.py sends the correct Temporal signals when conflicts
are resolved, and that the workflow unblocks after receiving the signal.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "temporal_worker"))


# ---------------------------------------------------------------------------
# Client helper tests (pure logic, no Temporal server needed)
# ---------------------------------------------------------------------------

def test_client_has_hitl_helpers():
    """temporal_worker/client.py must expose send_hitl_approve/reject/get_status."""
    try:
        import client as tc
        assert hasattr(tc, "send_hitl_approve")
        assert hasattr(tc, "send_hitl_reject")
        assert hasattr(tc, "get_workflow_status")
        assert hasattr(tc, "send_hitl_signal")
    except ImportError as e:
        import pytest
        pytest.skip(f"temporalio not installed: {e}")


def test_get_workflow_id_matches_hitl_router_convention():
    """The workflow ID format must be 'rfq-{rfq_id}' — same scheme used by upload_server."""
    try:
        import client as tc
        assert tc.get_workflow_id("CE-005570") == "rfq-CE-005570"
        assert tc.get_workflow_id("RFQ-001") == "rfq-RFQ-001"
    except ImportError as e:
        import pytest
        pytest.skip(f"temporalio not installed: {e}")


# ---------------------------------------------------------------------------
# Mock-based signal dispatch tests
# ---------------------------------------------------------------------------

def test_send_hitl_approve_calls_signal():
    """send_hitl_approve must call handle.signal with action=approve."""
    import pytest
    try:
        import asyncio
        from unittest.mock import AsyncMock, patch, MagicMock
    except ImportError as e:
        pytest.skip(str(e))

    try:
        import client as tc
    except ImportError as e:
        pytest.skip(f"temporalio not installed: {e}")

    handle_mock = AsyncMock()
    client_mock = AsyncMock()
    client_mock.get_workflow_handle.return_value = handle_mock

    async def run():
        with patch.object(tc, "Client") as MockClient:
            MockClient.connect = AsyncMock(return_value=client_mock)
            await tc.send_hitl_approve("CE-005570", {"gate": "resolve_final_selection"})
        handle_mock.signal.assert_called_once()
        call_args = handle_mock.signal.call_args
        # first positional arg is the signal method reference
        signal_payload = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
        assert signal_payload.get("action") == "approve"
        assert signal_payload.get("gate") == "resolve_final_selection"

    asyncio.get_event_loop().run_until_complete(run())


def test_send_hitl_reject_calls_signal_with_reject():
    """send_hitl_reject must call handle.signal with action=reject."""
    import pytest
    try:
        import asyncio
        from unittest.mock import AsyncMock, patch
    except ImportError as e:
        pytest.skip(str(e))

    try:
        import client as tc
    except ImportError as e:
        pytest.skip(f"temporalio not installed: {e}")

    handle_mock = AsyncMock()
    client_mock = AsyncMock()
    client_mock.get_workflow_handle.return_value = handle_mock

    async def run():
        with patch.object(tc, "Client") as MockClient:
            MockClient.connect = AsyncMock(return_value=client_mock)
            await tc.send_hitl_reject("CE-005570", "wrong part number")
        call_args = handle_mock.signal.call_args
        signal_payload = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
        assert signal_payload.get("action") == "reject"
        assert signal_payload.get("reason") == "wrong part number"

    asyncio.get_event_loop().run_until_complete(run())


# ---------------------------------------------------------------------------
# Temporal SDK integration tests
# ---------------------------------------------------------------------------

def test_workflow_resumes_after_hitl_approve():
    """Workflow paused at HITL gate must resume and complete after human_decision approve."""
    import pytest
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

    gate_called = []
    post_gate_called = []

    async def mock_get_routing(rfq_id, profile_name):
        return mock_routing

    async def mock_execute_tool(rfq_id, tool_name, arguments):
        if tool_name == "centum_reporting__resolve_final_selection":
            gate_called.append(tool_name)
            return {"status": "hitl_gate", "hitl": 1, "hitl_required": True}
        post_gate_called.append(tool_name)
        return {"status": "success"}

    async def run():
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue="test-hitl-resume",
                workflows=[wf.RFQWorkflow],
                activities=[mock_get_routing, mock_execute_tool],
            ):
                handle = await env.client.start_workflow(
                    wf.RFQWorkflow.run,
                    args=["CE-005570", "Standard_BOM_Flow"],
                    id="test-hitl-resume",
                    task_queue="test-hitl-resume",
                )
                await handle.signal(wf.RFQWorkflow.human_decision, {
                    "action": "approve",
                    "gate": "resolve_final_selection",
                })
                result = await handle.result()

        assert result["status"] == "completed"
        assert gate_called == ["centum_reporting__resolve_final_selection"]
        assert post_gate_called == ["centum_reporting__generate_reports"]

    asyncio.get_event_loop().run_until_complete(run())


def test_workflow_terminates_on_hitl_reject():
    """Workflow receiving action=reject at HITL gate must return status=rejected."""
    import pytest
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

    async def mock_get_routing(rfq_id, profile_name):
        return mock_routing

    async def mock_execute_tool(rfq_id, tool_name, arguments):
        return {"status": "hitl_gate", "hitl": 1, "hitl_required": True}

    async def run():
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue="test-hitl-reject",
                workflows=[wf.RFQWorkflow],
                activities=[mock_get_routing, mock_execute_tool],
            ):
                handle = await env.client.start_workflow(
                    wf.RFQWorkflow.run,
                    args=["CE-005570", "Standard_BOM_Flow"],
                    id="test-hitl-reject",
                    task_queue="test-hitl-reject",
                )
                await handle.signal(wf.RFQWorkflow.human_decision, {
                    "action": "reject",
                    "reason": "wrong supplier",
                })
                result = await handle.result()

        assert result["status"] == "rejected"

    asyncio.get_event_loop().run_until_complete(run())


# ---------------------------------------------------------------------------
# fastapi_router.py status endpoint smoke test
# ---------------------------------------------------------------------------

def test_rfq_status_endpoint_exists():
    """GET /rfq/{rfq_id}/status must be registered on the FastAPI app."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "fastapi-router"))
    try:
        import importlib
        # Avoid importing the whole router (it imports db, tool_calling, etc.)
        # Just verify the route is registered via the app's route list.
        import fastapi_router as fr
        routes = [r.path for r in fr.app.routes]
        assert "/rfq/{rfq_id}/status" in routes
    except ImportError as e:
        import pytest
        pytest.skip(f"fastapi_router deps unavailable: {e}")
