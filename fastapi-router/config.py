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

MCP_URLS: dict[str, str] = {}   # manifest_id → direct HTTP URL, e.g. "centum_intake" → "http://...:8002/mcp"
TOOL_URLS: dict[str, str] = {}  # tool name → URL of the manifest that declares it


def _signature():
    """Cheap fingerprint of manifests/ (names + mtimes): lets a miss skip re-parsing when nothing changed."""
    try:
        return tuple(sorted((f.name, f.stat().st_mtime_ns) for f in _MANIFESTS_DIR.glob("*.json")))
    except OSError:
        return None


def _load_manifests() -> None:
    """(Re)build both maps. Swapped in whole so a concurrent reader never sees a half-built map."""
    global MCP_URLS, TOOL_URLS, _SIG
    _SIG = _signature()
    mcp_urls, tool_urls = {}, {}
    for mf in sorted(_MANIFESTS_DIR.glob("*.json")):
        try:
            data = json.loads(mf.read_text(encoding="utf-8"))
            url = f"http://{MCP_HOST}:{data['port']}/mcp"
            names = [tool["name"] for tool in data.get("tools", [])]
        except Exception as e:  # skip the whole bad manifest, never half of it
            print(f"[config] ignoring unreadable manifest {mf.name}: {e}")
            continue
        mcp_urls[data["id"]] = url
        tool_urls.update(dict.fromkeys(names, url))
    MCP_URLS, TOOL_URLS = mcp_urls, tool_urls


_load_manifests()


def get_mcp_url(tool_name: str) -> str:
    """Return the direct /mcp endpoint of the manifest that declares tool_name.

    A manifest owns its tools: the name prefix is NOT the manifest id (the scrub
    tools are `centum_intake__standardize_*` but live in manifest `centum_scrub_intake`).
    A miss rescans manifests/ only if its contents changed, so a manifest imported after
    startup needs no restart and a loop on an undeclared tool name does not re-parse every call.
    """
    if tool_name not in TOOL_URLS and _signature() != _SIG:
        _load_manifests()
    url = TOOL_URLS.get(tool_name)
    if not url:
        raise ValueError(
            f"No manifest declares tool '{tool_name}'. Known manifests: {sorted(MCP_URLS)}"
        )
    return url
