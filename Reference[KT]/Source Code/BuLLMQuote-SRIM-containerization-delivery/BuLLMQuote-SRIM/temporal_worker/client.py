"""Temporal client helpers — called by upload_server.py and hitl_router.py."""

from temporalio.client import Client

import config


async def _get_client() -> Client:
    return await Client.connect(config.TEMPORAL_HOST, namespace=config.NAMESPACE)


async def start_rfq_workflow(rfq_id: str, profile_name: str = "Standard_BOM_Flow") -> str:
    """Start an RFQ workflow and return the workflow ID.

    Idempotent: same rfq_id → same workflow ID. If the workflow already exists
    and is still running, Temporal returns the handle without starting a new one.
    """
    client = await _get_client()
    handle = await client.start_workflow(
        "RFQWorkflow",
        args=[rfq_id, profile_name],
        id=f"rfq-{rfq_id}",
        task_queue=config.TASK_QUEUE,
    )
    return handle.id


async def send_hitl_signal(workflow_id: str, decision: dict) -> None:
    """Send human_decision signal to a workflow waiting at a HITL gate."""
    client = await _get_client()
    handle = client.get_workflow_handle(workflow_id)
    await handle.signal("human_decision", decision)


async def get_workflow_status(workflow_id: str) -> dict:
    """Return current workflow status as a dict."""
    client = await _get_client()
    handle = client.get_workflow_handle(workflow_id)
    desc = await handle.describe()
    return {
        "workflow_id": workflow_id,
        "status": str(desc.status),
        "start_time": desc.start_time.isoformat() if desc.start_time else None,
    }
