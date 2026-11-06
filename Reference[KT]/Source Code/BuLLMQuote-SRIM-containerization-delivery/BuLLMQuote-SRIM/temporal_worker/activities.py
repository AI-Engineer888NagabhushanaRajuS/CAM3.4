"""Temporal activities for the RFQ pipeline.

Each activity is a thin HTTP client that calls the existing fastapi_router endpoints —
the same endpoints Dify calls. The tool contract (POST /tool/execute) is UNCHANGED.
"""

import httpx
from temporalio import activity

import config


@activity.defn
async def get_routing_sequence(rfq_id: str, profile_name: str) -> dict:
    """Fetch routing_sequence + skill_index from fastapi_router (same endpoint Dify calls)."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{config.FASTAPI_ROUTER_URL}/pipeline/routing-sequence/{rfq_id}/{profile_name}",
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()


@activity.defn
async def execute_tool(rfq_id: str, tool_name: str, arguments: dict) -> dict:
    """POST /tool/execute — exact same call Dify makes. Contract is UNCHANGED."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{config.FASTAPI_ROUTER_URL}/tool/execute",
            json={"rfq_id": rfq_id, "tool_name": tool_name, "arguments": arguments},
            timeout=600,  # 10 min max for heavy report generation
        )
        resp.raise_for_status()
        return resp.json()
