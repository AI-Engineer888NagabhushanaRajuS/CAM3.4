"""Temporal client helpers — called by upload_server.py to start workflows and
by hitl_router.py to send HITL decision signals.
"""
import importlib.util
import os

from temporalio.client import Client

# fastapi-router has its own config.py. hitl_router.py loads that one first, so a bare
# `import config` here would return it. Load this folder's config.py by path instead.
_config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.py")
_config_spec = importlib.util.spec_from_file_location("temporal_worker_config", _config_path)
config = importlib.util.module_from_spec(_config_spec)
_config_spec.loader.exec_module(config)

from workflow import RFQWorkflow  # noqa: E402


async def start_rfq_workflow(rfq_id: str, profile_name: str = "Standard_BOM_Flow") -> str:
    """Start an RFQ workflow and return the workflow ID.

    The workflow ID is per RFQ, not per version. If a run for this RFQ is still running,
    Temporal raises WorkflowAlreadyStartedError: the caller must treat that as a failed
    trigger, never as a new run (returning the old ID would hide a new version).
    """
    client = await Client.connect(config.TEMPORAL_HOST, namespace=config.NAMESPACE)
    handle = await client.start_workflow(
        RFQWorkflow.run,
        args=[rfq_id, profile_name],
        id=get_workflow_id(rfq_id),
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


async def send_hitl_approve(rfq_id: str, resolution: dict) -> bool:
    """Approve a HITL gate — unblocks the workflow to continue.

    resolution: gate-specific data (e.g. {"gate": "resolve_final_selection", ...})
    """
    client = await Client.connect(config.TEMPORAL_HOST, namespace=config.NAMESPACE)
    handle = client.get_workflow_handle(get_workflow_id(rfq_id))
    await handle.signal(RFQWorkflow.human_decision, {"action": "approve", **resolution})
    return True


async def send_hitl_reject(rfq_id: str, reason: str) -> bool:
    """Reject a HITL gate — terminates the workflow."""
    client = await Client.connect(config.TEMPORAL_HOST, namespace=config.NAMESPACE)
    handle = client.get_workflow_handle(get_workflow_id(rfq_id))
    await handle.signal(RFQWorkflow.human_decision, {"action": "reject", "reason": reason})
    return True


async def get_workflow_status(rfq_id: str) -> dict:
    """Get current workflow status — running, paused at HITL, completed, failed."""
    client = await Client.connect(config.TEMPORAL_HOST, namespace=config.NAMESPACE)
    handle = client.get_workflow_handle(get_workflow_id(rfq_id))
    desc = await handle.describe()
    return {
        "status": str(desc.status),
        "workflow_id": desc.id,
        "run_id": desc.run_id,
    }


def get_workflow_id(rfq_id: str) -> str:
    """Derive the deterministic Temporal workflow ID for an rfq_id."""
    return f"rfq-{rfq_id}"
