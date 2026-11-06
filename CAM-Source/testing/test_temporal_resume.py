"""Resuming a run parked at a human gate: the UI's "continue" call (GET /api/dify/start/{rfq}).

In 3.3 the Dify DMR ended at every human gate and "continue" started a fresh Dify run from
skill_index. The Temporal run does NOT end: it parks inside the workflow waiting for a signal. The UI
only ever calls /api/dify/start after the QuoteWin/Costing upload, so with the 3.4 trigger that call
tried to start a second workflow with the same ID, failed, and the parked run waited forever.

Run against the SDK's real time-skipping test server (same as test_temporal_workflow.py).
"""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "temporal_worker"))

try:
    from temporalio import activity
    from temporalio.client import WorkflowExecutionStatus
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker
    import client as tc
    import workflow as wf
except ImportError as e:  # pragma: no cover
    pytest.skip(f"temporalio not installed: {e}", allow_module_level=True)

ROUTING = {"routing_sequence": ["t_slow", "t_gate", "t_after"], "skill_index": 0}


class Stack:
    """A worker whose tools can be held open, so a test controls exactly where the run is."""

    def __init__(self):
        self.called, self.release = [], {}

    def hold(self, tool):
        self.release[tool] = asyncio.Event()
        return self.release[tool]

    def activities(self):
        stack = self

        @activity.defn(name="get_routing_sequence")
        async def routing(rfq_id, profile_name):
            return ROUTING

        @activity.defn(name="execute_tool")
        async def execute(rfq_id, tool, arguments):
            stack.called.append(tool)
            if tool in stack.release:
                await stack.release[tool].wait()
            return {"status": "success", "hitl": 1} if tool == "t_gate" else {"status": "success"}

        return [routing, execute]


async def until(handle, predicate, what, timeout=20):
    for _ in range(int(timeout / 0.1)):
        state = await handle.query(wf.RFQWorkflow.hitl_state)
        if predicate(state):
            return state
        await asyncio.sleep(0.1)
    raise AssertionError(f"workflow never {what}")


def run_with_stack(monkeypatch, body):
    async def main():
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async def fake_connect(*args, **kwargs):
                return env.client

            monkeypatch.setattr(tc.Client, "connect", fake_connect)
            stack = Stack()
            async with Worker(env.client, task_queue=tc.config.TASK_QUEUE, workflows=[wf.RFQWorkflow],
                              activities=stack.activities()):
                return await body(env, stack)

    return asyncio.run(main())


def test_resume_releases_a_run_parked_at_a_gate(monkeypatch):
    async def body(env, stack):
        wid = await tc.start_rfq_workflow("R-RES-1")
        handle = env.client.get_workflow_handle(wid)
        state = await until(handle, lambda s: s["awaiting"], "parked at the gate")
        assert state["tool"] == "t_gate"
        assert await tc.resume_rfq_workflow("R-RES-1") == (wid, "RESUMED")
        return await handle.result(), stack.called

    result, called = run_with_stack(monkeypatch, body)
    assert result["status"] == "completed" and called == ["t_slow", "t_gate", "t_after"]


def test_resume_while_a_step_is_running_changes_nothing_and_cannot_pre_approve_the_gate(monkeypatch):
    async def body(env, stack):
        slow = stack.hold("t_slow")
        wid = await tc.start_rfq_workflow("R-RES-2")
        handle = env.client.get_workflow_handle(wid)
        for _ in range(100):  # wait until t_slow is really executing
            if "t_slow" in stack.called:
                break
            await asyncio.sleep(0.1)
        assert await tc.resume_rfq_workflow("R-RES-2") == (wid, "RUNNING")
        slow.set()
        # the later human gate must still wait for a human
        state = await until(handle, lambda s: s["awaiting"], "reached the gate and waited")
        assert state["tool"] == "t_gate"
        assert (await handle.describe()).status == WorkflowExecutionStatus.RUNNING
        assert await tc.resume_rfq_workflow("R-RES-2") == (wid, "RESUMED")
        return await handle.result()

    assert run_with_stack(monkeypatch, body)["status"] == "completed"


def test_a_stray_decision_between_gates_does_not_pre_approve_the_next_gate(monkeypatch):
    async def body(env, stack):
        slow = stack.hold("t_slow")
        wid = await tc.start_rfq_workflow("R-RES-3")
        handle = env.client.get_workflow_handle(wid)
        for _ in range(100):
            if "t_slow" in stack.called:
                break
            await asyncio.sleep(0.1)
        await handle.signal(wf.RFQWorkflow.human_decision, {"action": "approve"})  # nobody is waiting yet
        slow.set()
        await until(handle, lambda s: s["awaiting"], "reached the gate and waited")
        return (await handle.describe()).status

    assert run_with_stack(monkeypatch, body) == WorkflowExecutionStatus.RUNNING


def test_a_decision_sent_while_the_gate_tool_is_still_running_is_honoured(monkeypatch):
    # The UI can answer the moment it is told a review is needed, before the activity has returned.
    async def body(env, stack):
        gate = stack.hold("t_gate")
        wid = await tc.start_rfq_workflow("R-RES-4")
        handle = env.client.get_workflow_handle(wid)
        for _ in range(100):
            if "t_gate" in stack.called:
                break
            await asyncio.sleep(0.1)
        await handle.signal(wf.RFQWorkflow.human_decision, {"action": "approve"})
        gate.set()
        return await asyncio.wait_for(handle.result(), timeout=20)

    assert run_with_stack(monkeypatch, body)["status"] == "completed"


def test_resume_never_starts_a_run_that_was_never_uploaded(monkeypatch):
    # Opening an RFQ calls resume; with nothing ever uploaded there is no run to resume and no inputs to start one.
    async def body(env, stack):
        outcome = await tc.resume_rfq_workflow("R-RES-5")
        return outcome, stack.called

    outcome, called = run_with_stack(monkeypatch, body)
    assert outcome == (None, "NOT_STARTED") and called == []


def test_resume_after_a_finished_run_starts_nothing_new(monkeypatch):
    async def body(env, stack):
        wid = await tc.start_rfq_workflow("R-RES-6")
        await until(env.client.get_workflow_handle(wid), lambda s: s["awaiting"], "parked at the gate")
        await tc.resume_rfq_workflow("R-RES-6")  # parked at the gate: released
        await env.client.get_workflow_handle(wid).result()
        wid2, outcome2 = await tc.resume_rfq_workflow("R-RES-6")  # the run is finished now: no new run
        second_run = (await env.client.get_workflow_handle(wid2).describe()).run_id
        first_run = (await env.client.get_workflow_handle(wid).describe()).run_id
        return outcome2, first_run == second_run

    assert run_with_stack(monkeypatch, body) == ("COMPLETED", True)


def test_a_new_upload_supersedes_a_run_still_parked_for_the_same_rfq(monkeypatch):
    # Upload = a new version. The old run (typically parked at the scrub gate) is obsolete: it must be
    # replaced, not left as a zombie that makes every later trigger fail.
    async def body(env, stack):
        wid = await tc.start_rfq_workflow("R-RES-6")
        old = env.client.get_workflow_handle(wid)
        await until(old, lambda s: s["awaiting"], "parked at the gate")
        old_run = (await old.describe()).run_id
        wid2 = await tc.start_rfq_workflow("R-RES-6")
        new = env.client.get_workflow_handle(wid2)
        new_desc = await new.describe()
        old_desc = await env.client.get_workflow_handle(wid, run_id=old_run).describe()
        return wid == wid2, new_desc.run_id != old_run, old_desc.status

    same_id, new_run, old_status = run_with_stack(monkeypatch, body)
    assert same_id and new_run and old_status == WorkflowExecutionStatus.TERMINATED
