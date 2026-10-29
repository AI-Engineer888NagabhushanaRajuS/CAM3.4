"""Temporal client helpers — called by upload_server.py to start workflows and
by hitl_router.py to send HITL decision signals.
"""
from temporalio.client import Client

import config
from workflow import RFQWorkflow


async def start_rfq_workflow(rfq_id: str, profile_name: str = "Standard_BOM_Flow") -> str:
    """Start an RFQ workflow and return the workflow ID.

    Idempotent: same rfq_id always produces the same workflow ID, so a second
    call for the same RFQ returns the existing workflow handle without restarting.
    """
    client = await Client.connect(config.TEMPORAL_HOST, namespace=config.NAMESPACE)
    handle = await client.start_workflow(
        RFQWorkflow.run,
        args=[rfq_id, profile_name],
        id=f"rfq-{rfq_id}",
        task_queue=config.TASK_QUEUE,
    )
    return handle.id


async def send_hitl_signal(workflow_id: str, decision: dict):
    """Send a human_decision signal to a workflow waiting at a HITL gate.

    decision: {"action": "approve" | "reject", ...}
    """
    client = await Client.connect(config.TEMPORAL_HOST, namespace=config.NAMESPACE)
    handle = client.get_workflow_handle(workflow_id)
    await handle.signal(RFQWorkflow.human_decision, decision)


def get_workflow_id(rfq_id: str) -> str:
    """Derive the deterministic Temporal workflow ID for an rfq_id."""
    return f"rfq-{rfq_id}"
