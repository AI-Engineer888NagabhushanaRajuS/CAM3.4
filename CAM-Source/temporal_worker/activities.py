"""Temporal activities — thin HTTP wrappers over fastapi_router endpoints.

Each activity is stateless and safe to retry. The `execute_tool` activity calls
the same POST /tool/execute endpoint that Dify called — the contract is UNCHANGED.
"""
from temporalio import activity
import httpx

import config


@activity.defn
async def get_routing_sequence(rfq_id: str, profile_name: str) -> dict:
    """Fetch the routing sequence for this rfq_id and profile from fastapi_router.
    Returns {"routing_sequence": [...], "skill_index": int}.
    """
    url = f"{config.FASTAPI_ROUTER_URL}/pipeline/routing-sequence/{rfq_id}/{profile_name}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, timeout=120.0)
        resp.raise_for_status()
        body = resp.json()
        # The router reports lookup failures as HTTP 200 + {"error": ...}. Raise here so the
        # workflow never mistakes a failed lookup for an empty, successful routing sequence.
        if "error" in body:
            raise RuntimeError(f"routing-sequence lookup failed for {rfq_id}/{profile_name}: {body['error']}")
        return body


@activity.defn
async def execute_tool(rfq_id: str, tool_name: str, arguments: dict) -> dict:
    """POST /tool/execute — exact same call Dify made. Contract UNCHANGED.

    Returns the tool response dict. Raises httpx.HTTPStatusError on non-2xx.
    Caller (workflow) decides whether to halt on hitl_required.
    """
    payload = {"rfq_id": rfq_id, "tool_name": tool_name, "arguments": arguments}
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{config.FASTAPI_ROUTER_URL}/tool/execute",
            json=payload,
            timeout=config.TOOL_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
