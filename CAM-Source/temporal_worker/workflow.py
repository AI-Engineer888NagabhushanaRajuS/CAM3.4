"""RFQ pipeline Temporal workflow — replaces Dify DMR.

Same logic as Dify_DMR_RFQ_Flow.yml but durable, testable, signal-aware.
The critical constraint: fastapi_router.py POST /tool/execute contract is UNCHANGED.
This workflow calls the same endpoint Dify called.
"""
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    import activities


@workflow.defn
class RFQWorkflow:
    def __init__(self):
        self._hitl_decision = None
        self._awaiting_tool = None

    @workflow.signal
    def human_decision(self, decision: dict):
        """Signal sent by hitl_router when a human approves or rejects a HITL gate."""
        self._hitl_decision = decision

    @workflow.query
    def hitl_state(self) -> dict:
        """Is the run parked at a human gate? The UI's "continue" call signals a run only when this says
        it is waiting, so a stray click can never pre-approve a later gate."""
        return {"awaiting": self._awaiting_tool is not None, "tool": self._awaiting_tool}

    @workflow.run
    async def run(self, rfq_id: str, profile_name: str) -> dict:
        """Execute the full RFQ pipeline for one rfq_id.

        Mirrors the Dify DMR loop:
          1. Fetch routing_sequence from Postgres (via fastapi_router)
          2. For each tool in sequence: execute_tool activity
          3. If hitl_required: wait for human_decision signal, then continue or abort
          4. Return final status dict
        """
        # 1. Fetch routing sequence (same source Dify used)
        routing = await workflow.execute_activity(
            activities.get_routing_sequence,
            args=[rfq_id, profile_name],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        sequence = routing.get("routing_sequence", [])
        start_index = routing.get("skill_index", 0)

        results = []
        # D2 fix (SPEC-015): routing_sequence is a list of tool-name strings.
        # Arguments are the Dify body's {"rfq_id": rfq} (HTTP Request 2), same for every tool.
        tool_args = {"rfq_id": rfq_id}
        for tool_name in sequence[start_index:]:

            # A decision that arrived while nobody was waiting for one must not pre-approve this step's
            # gate. (A decision sent while THIS tool is still running, before it asks for one, is kept:
            # the UI may answer the moment it is told a review is needed.)
            self._hitl_decision = None

            # 2. Call the tool via fastapi_router (unchanged contract)
            result = await workflow.execute_activity(
                activities.execute_tool,
                args=[rfq_id, tool_name, tool_args],
                start_to_close_timeout=timedelta(minutes=20),  # a QuoteWin standardize can wait on a cold model load (see TOOL_CALL_TIMEOUT)
                retry_policy=RetryPolicy(
                    maximum_attempts=3,
                    backoff_coefficient=2.0,
                    maximum_interval=timedelta(seconds=30),
                ),
            )

            # A tool failure comes back as HTTP 200 with status "failed" (fastapi_router). Fail the run
            # here; otherwise the workflow completes with every remaining step silently skipped.
            if result.get("status") == "failed":
                raise ApplicationError(
                    f"{tool_name} failed: {result.get('error')}", non_retryable=True
                )

            # 3. HITL gate: block until human sends human_decision signal
            if result.get("hitl_required") or result.get("hitl") == 1:
                self._awaiting_tool = tool_name
                await workflow.wait_condition(
                    lambda: self._hitl_decision is not None
                )
                self._awaiting_tool = None
                decision = self._hitl_decision
                self._hitl_decision = None  # reset for next gate

                if decision.get("action") == "reject":
                    return {
                        "status": "rejected",
                        "rfq_id": rfq_id,
                        "step": tool_name,
                        "results": results,
                    }

            results.append({"tool": tool_name, "result": result})

        return {
            "status": "completed",
            "rfq_id": rfq_id,
            "profile": profile_name,
            "steps_executed": len(results),
            "results": results,
        }
