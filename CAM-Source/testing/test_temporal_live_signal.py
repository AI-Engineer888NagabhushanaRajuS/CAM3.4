"""
SPEC-015 live check: the HITL human_decision signal reaches a RUNNING workflow on a real
Temporal server (opt-in: CAM_TEMPORAL_LIVE=1, Temporal at CAM_TEMPORAL_HOST).

Only the two tool activities are stand-ins (the router and DB are not running here). The
Temporal server, the worker, the workflow, and temporal_worker/client.py's real
send_hitl_approve path are all real.
"""
import asyncio
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "temporal_worker"))

LIVE = os.environ.get("CAM_TEMPORAL_LIVE") == "1"
pytestmark = pytest.mark.skipif(not LIVE, reason="live Temporal: set CAM_TEMPORAL_LIVE=1 with a Temporal server running")

FIXTURE_ROUTING = [
    "centum_reporting__cbom",
    "centum_reporting__resolve_final_selection",  # HITL gate
    "centum_reporting__generate_reports",
]
HITL_TOOL = "centum_reporting__resolve_final_selection"


def test_hitl_signal_reaches_running_workflow_on_real_server():
    from temporalio import activity
    from temporalio.client import Client
    from temporalio.worker import Worker
    import client as temporal_client
    import config
    from workflow import RFQWorkflow

    rfq_id = f"CE-LIVE-{uuid.uuid4().hex[:8]}"
    task_queue = f"live-hitl-{uuid.uuid4().hex[:6]}"
    recorded = []

    @activity.defn(name="get_routing_sequence")
    async def fake_routing(rfq, profile):
        return {"routing_sequence": FIXTURE_ROUTING, "skill_index": 0}

    @activity.defn(name="execute_tool")
    async def fake_execute(rfq, tool, args):
        recorded.append(tool)
        return {"hitl": 1 if tool == HITL_TOOL else 0}

    async def main():
        client = await Client.connect(config.TEMPORAL_HOST, namespace=config.NAMESPACE)
        async with Worker(client, task_queue=task_queue, workflows=[RFQWorkflow],
                          activities=[fake_routing, fake_execute]):
            handle = await client.start_workflow(
                RFQWorkflow.run, args=[rfq_id, "RFQ_Flow"], id=f"rfq-{rfq_id}", task_queue=task_queue,
            )
            for _ in range(300):  # up to ~30 s for the workflow to reach the gate
                if HITL_TOOL in recorded:
                    break
                await asyncio.sleep(0.1)
            assert HITL_TOOL in recorded, f"workflow never reached the HITL gate: {recorded}"
            # Real client path: connects, looks up rfq-<id>, signals human_decision.
            assert await temporal_client.send_hitl_approve(rfq_id, {"gate": HITL_TOOL}) is True
            return await asyncio.wait_for(handle.result(), timeout=60)

    result = asyncio.run(main())
    assert result["status"] == "completed", result
    assert recorded == [
        "centum_reporting__cbom",
        HITL_TOOL,
        "centum_reporting__generate_reports",
    ], recorded
