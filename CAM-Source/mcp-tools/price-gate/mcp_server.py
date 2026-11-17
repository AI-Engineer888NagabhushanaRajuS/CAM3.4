"""MCP tools for the price-source gate (resolve_final_selection): read the conflicts, record a source per conflict, resume the run.

The same HITL endpoints the review screen uses (hitl_router.py) and the same resume call the left pane makes (upload_server.py
/api/dify/start). Every call mints its own 60-second per-RFQ token from the python bridge, as the browser does. The tools do
not decide anything: an agent passes the source it was told to use; a write is only ever a resolution the caller names.

Run: python mcp_server.py  (streamable HTTP on 8110). Inside the compose network the URLs below are the service names.
"""

import os
import re

import httpx
from fastmcp import FastMCP

mcp = FastMCP("PriceGate")

BRIDGE_URL = os.environ.get("CAM_PYTHON_BRIDGE_URL", "http://python-bridge:3110").rstrip("/")
HITL_URL = os.environ.get("CAM_HITL_ROUTER_URL", "http://hitl-router:5102").rstrip("/")
UPLOAD_URL = os.environ.get("CAM_UPLOAD_URL", "http://upload-server:3100").rstrip("/")
SOURCES = ("costing", "erp", "qw")
TIMEOUT = 30


def _rfq(rfq_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", rfq_id or ""):
        raise ValueError(f"Invalid RFQ id: {rfq_id!r}")
    return rfq_id


def _headers(rfq_id: str) -> dict:
    res = httpx.post(f"{BRIDGE_URL}/auth/token", json={"rfq_id": rfq_id}, timeout=TIMEOUT)
    res.raise_for_status()
    return {"Authorization": f"Bearer {res.json()['token']}"}


@mcp.tool()
def price_gate_status(rfq_id: str) -> dict:
    """Counts of the price-source conflicts for one RFQ: how many are pending, and whether the run waits at the gate."""
    rfq = _rfq(rfq_id)
    res = httpx.get(f"{HITL_URL}/api/rfq/{rfq}/final-selection/summary", headers=_headers(rfq), timeout=TIMEOUT)
    res.raise_for_status()
    return res.json()


@mcp.tool()
def list_price_conflicts(rfq_id: str, limit: int = 50, cursor: str | None = None) -> dict:
    """The unresolved conflicts for one RFQ: each part (CPN) at one volume with the price each source gives it.
    Returns up to `limit` items (max 500) and `next_cursor`; pass it back as `cursor` for the next page (null = last page)."""
    rfq = _rfq(rfq_id)
    params = {"limit": max(1, min(int(limit), 500))}
    if cursor:
        params["cursor"] = cursor
    res = httpx.get(
        f"{HITL_URL}/api/rfq/{rfq}/final-selection/pending",
        params=params,
        headers=_headers(rfq),
        timeout=TIMEOUT,
    )
    res.raise_for_status()
    return res.json()


@mcp.tool()
def resolve_price_conflicts(rfq_id: str, resolutions: list[dict], resolved_by: str) -> dict:
    """Record the source for conflicts. Each resolution is {"conflict_id": "...", "resolved_source": "costing" | "erp" | "qw"}.
    Only the conflicts named are written; the run stays at the gate until every conflict has a source.
    `resolved_by` is the signed-in person's email, stored with each decision."""
    rfq = _rfq(rfq_id)
    if not resolved_by or "@" not in resolved_by:
        raise ValueError("resolved_by must be the signed-in person's email")
    rows = []
    for r in resolutions:
        source = r.get("resolved_source")
        if source not in SOURCES:
            raise ValueError(f"resolved_source must be one of {SOURCES}, got {source!r}")
        rows.append({"conflict_id": str(r["conflict_id"]), "resolved_source": source, "resolved_by": resolved_by})
    res = httpx.post(
        f"{HITL_URL}/api/rfq/{rfq}/final-selection",
        json={"resolutions": rows},
        headers=_headers(rfq),
        timeout=TIMEOUT,
    )
    if res.status_code >= 400:
        raise ValueError(res.json().get("detail", f"the decisions were not saved (status {res.status_code})"))
    return res.json()


@mcp.tool()
def resume_price_gate(rfq_id: str) -> dict:
    """Carry the run on past the price-source gate, the same call the left pane makes after the decisions are saved.
    Only meaningful once every conflict has a source; the service answers with what it did."""
    rfq = _rfq(rfq_id)
    res = httpx.get(f"{UPLOAD_URL}/api/dify/start/{rfq}", headers=_headers(rfq), timeout=TIMEOUT)
    res.raise_for_status()
    return res.json()


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8110)
