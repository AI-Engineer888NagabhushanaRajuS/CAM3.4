"""Direct FastMCP tool calls via stateful HTTP sessions (no Bifrost/Jungle).

FastMCP 3.x streamable-HTTP transport requires:
  1. POST /mcp with method=initialize → server returns mcp-session-id header
  2. POST /mcp with mcp-session-id header for all subsequent calls

Sessions are cached per server URL so we only initialize once per process.
"""

import itertools
import json
import threading
import requests
from config import get_mcp_url

_request_id = itertools.count(1)
_sessions: dict[str, str] = {}   # url → session_id
_sessions_lock = threading.Lock()


def _get_session(url: str) -> str:
    with _sessions_lock:
        if url in _sessions:
            return _sessions[url]
    payload = {
        "jsonrpc": "2.0",
        "id": next(_request_id),
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "cam-fastapi-router", "version": "3.4"},
        },
    }
    resp = requests.post(
        url, json=payload,
        headers={"Accept": "application/json, text/event-stream"},
        timeout=30, stream=True,
    )
    resp.raise_for_status()
    session_id = resp.headers.get("mcp-session-id", "")
    if not session_id:
        raise RuntimeError(f"No mcp-session-id returned from {url}")
    # Send notifications/initialized to complete handshake
    requests.post(
        url,
        json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        headers={"Accept": "application/json, text/event-stream",
                 "mcp-session-id": session_id},
        timeout=10,
    )
    with _sessions_lock:
        _sessions[url] = session_id
    return session_id


def _read_response(resp: requests.Response) -> dict:
    content_type = resp.headers.get("Content-Type", "")
    if "text/event-stream" in content_type:
        result = None
        for raw in resp.iter_lines():
            if not raw:
                continue
            line = raw if isinstance(raw, str) else raw.decode()
            if line.startswith("data: "):
                data = line[6:].strip()
                if data and data != "[DONE]":
                    result = json.loads(data)
        return result or {}
    return resp.json()


def _post(url: str, payload: dict) -> dict:
    session_id = _get_session(url)
    resp = requests.post(
        url, json=payload,
        headers={"Accept": "application/json, text/event-stream",
                 "mcp-session-id": session_id},
        timeout=300, stream=True,
    )
    if resp.status_code == 404 or (resp.status_code == 400 and "session" in resp.text.lower()):
        # Session expired or the server restarted (a 404 for a cached id). Purge and retry once.
        with _sessions_lock:
            _sessions.pop(url, None)
        session_id = _get_session(url)
        resp = requests.post(
            url, json=payload,
            headers={"Accept": "application/json, text/event-stream",
                     "mcp-session-id": session_id},
            timeout=300, stream=True,
        )
    resp.raise_for_status()
    return _read_response(resp)


def call_tool(tool_name: str, arguments: dict) -> dict:
    url = get_mcp_url(tool_name)
    # Server registers tools without the manifest prefix:
    # "centum_intake__scan_local_file" → "scan_local_file"
    server_name = tool_name.split("__", 1)[1] if "__" in tool_name else tool_name
    return _post(url, {
        "jsonrpc": "2.0",
        "id": next(_request_id),
        "method": "tools/call",
        "params": {"name": server_name, "arguments": arguments},
    })


def list_tools(manifest_id: str) -> dict:
    from config import MCP_URLS
    url = MCP_URLS.get(manifest_id)
    if not url:
        raise ValueError(f"Unknown manifest_id '{manifest_id}'")
    return _post(url, {
        "jsonrpc": "2.0",
        "id": next(_request_id),
        "method": "tools/list",
        "params": {},
    })


if __name__ == "__main__":
    import sys
    mid = sys.argv[1] if len(sys.argv) > 1 else "centum_intake"
    print(json.dumps(list_tools(mid), indent=2))
