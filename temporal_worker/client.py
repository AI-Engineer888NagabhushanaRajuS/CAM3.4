"""Temporal client helpers — called by upload_server.py to start workflows and
by hitl_router.py to send HITL decision signals.
"""
import importlib.util
import os

from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.common import WorkflowIDConflictPolicy
from temporalio.service import RPCError, RPCStatusCode

# fastapi-router has its own config.py. hitl_router.py loads that one first, so a bare
# `import config` here would return it. Load this folder's config.py by path instead.
_config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.py")
_config_spec = importlib.util.spec_from_file_location("temporal_worker_config", _config_path)
config = importlib.util.module_from_spec(_config_spec)
_config_spec.loader.exec_module(config)

from workflow import RFQWorkflow  # noqa: E402


async def start_rfq_workflow(rfq_id: str, profile_name: str | None = None, started_by: str | None = None, started_by_email: str | None = None) -> str:
    """Start an RFQ workflow and return the workflow ID.

    The workflow ID is per RFQ, not per version, and a new upload IS a new version: it supersedes a run
    still alive for this RFQ (typically one parked at the scrub gate), which is terminated. Failing the
    trigger instead left that run behind and made every later upload of the RFQ fail.

    `started_by` (who clicked, as the app reports it) goes into the run's memo so the History view can show it.
    """
    client = await Client.connect(config.TEMPORAL_HOST, namespace=config.NAMESPACE)
    profile_name = profile_name or config.DEFAULT_PROFILE
    handle = await client.start_workflow(
        RFQWorkflow.run,
        args=[rfq_id, profile_name],
        id=get_workflow_id(rfq_id),
        task_queue=config.TASK_QUEUE,
        id_conflict_policy=WorkflowIDConflictPolicy.TERMINATE_EXISTING,
        memo={k: v for k, v in (('started_by', started_by), ('started_by_email', started_by_email)) if v} or None,
    )
    return handle.id


async def resume_rfq_workflow(rfq_id: str, profile_name: str | None = None, started_by: str | None = None, started_by_email: str | None = None) -> tuple:
    """The UI's "continue" (GET /api/dify/start): returns (workflow_id, outcome).

    RESUMED - the run was parked at a human gate; it is told to carry on.
    RUNNING - the run is mid-step; nothing is sent (a decision stored now would pre-approve the NEXT gate).
    COMPLETED - every skill already ran; nothing to resume, so no second run is started (the UI's
                retry clicks used to start empty runs here).
    STARTED - the run terminated or failed: start one; it resumes at skill_index.
    NOT_STARTED - no run was ever started (nothing uploaded): there is nothing to resume, so none is started.
    """
    client = await Client.connect(config.TEMPORAL_HOST, namespace=config.NAMESPACE)
    handle = client.get_workflow_handle(get_workflow_id(rfq_id))
    try:
        status = (await handle.describe()).status
    except RPCError as e:
        if e.status != RPCStatusCode.NOT_FOUND:
            raise
        return None, "NOT_STARTED"
    if status == WorkflowExecutionStatus.COMPLETED:
        return handle.id, "COMPLETED"
    if status != WorkflowExecutionStatus.RUNNING:
        return await start_rfq_workflow(rfq_id, profile_name, started_by, started_by_email), "STARTED"
    if (await handle.query(RFQWorkflow.hitl_state))["awaiting"]:
        await handle.signal(RFQWorkflow.human_decision, {"action": "approve", "via": "resume"})
        return handle.id, "RESUMED"
    return handle.id, "RUNNING"


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
