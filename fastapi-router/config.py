"""Manifest-driven MCP server routing.

Reads port assignments from manifests/*.json so there is one source of truth
for every tool→server mapping (SPEC-003). No Bifrost/Jungle gateway needed —
FastMCP 3.x servers accept direct HTTP tool calls at POST /mcp with
Accept: application/json, text/event-stream.
"""

import json
import os
import pathlib

# In Docker the env var points to each container's internal hostname.
# Bare-metal default is the NetBird mesh IP where all MCP servers listen.
MCP_HOST = os.environ.get("CAM_MCP_HOST", "100.121.36.255")

_MANIFESTS_DIR = pathlib.Path(__file__).parent.parent / "manifests"

# manifest_id → direct HTTP URL, e.g. "centum_intake" → "http://...:8002/mcp"
MCP_URLS: dict[str, str] = {}
for _mf in _MANIFESTS_DIR.glob("*.json"):
    try:
        _data = json.loads(_mf.read_text(encoding="utf-8"))
        MCP_URLS[_data["id"]] = f"http://{MCP_HOST}:{_data['port']}/mcp"
    except Exception:
        pass


def get_mcp_url(tool_name: str) -> str:
    """Return the direct /mcp endpoint for a tool like 'centum_intake__scan_local_file'."""
    manifest_id = tool_name.split("__")[0]
    url = MCP_URLS.get(manifest_id)
    if not url:
        raise ValueError(
            f"No MCP server for manifest '{manifest_id}' (tool '{tool_name}'). "
            f"Known: {sorted(MCP_URLS)}"
        )
    return url
