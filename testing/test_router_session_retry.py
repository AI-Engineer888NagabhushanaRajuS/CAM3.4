"""
SPEC-015 bug (fastapi-router/tool_calling.py _post): the router caches one MCP session id per
server URL. If the tool server restarts, that id is gone and the server answers 404. Only a 400
was treated as an expired session, so every later call failed until the router restarted.
A 404 must purge the cached session, re-initialise, and retry once.
"""
import os
import sys

import pytest

FR = os.path.join(os.path.dirname(__file__), "..", "fastapi-router")


class _Resp:
    def __init__(self, status, body=None, headers=None):
        self.status_code = status
        self._body = body or {}
        self.headers = headers or {}
        self.text = "Not Found" if status == 404 else ""

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def test_404_purges_the_cached_session_and_retries_once(monkeypatch):
    sys.path.insert(0, os.path.abspath(FR))
    try:
        import tool_calling as tc
    except ImportError as e:
        pytest.skip(f"tool_calling deps unavailable: {e}")
    finally:
        sys.path.remove(os.path.abspath(FR))

    url = "http://scrub-intake-mcp-server:8004/mcp"
    monkeypatch.setattr(tc, "_sessions", {url: "stale-session"})
    calls = []

    def fake_post(u, json=None, headers=None, timeout=None, stream=None):
        calls.append(headers.get("mcp-session-id"))
        if headers.get("mcp-session-id") == "stale-session":
            return _Resp(404)
        if json.get("method") == "initialize":
            return _Resp(200, headers={"mcp-session-id": "fresh-session"})
        if json.get("method") == "notifications/initialized":
            return _Resp(202)
        return _Resp(200, {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}, {"Content-Type": "application/json"})

    monkeypatch.setattr(tc.requests, "post", fake_post)
    out = tc._post(url, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {}})
    assert out.get("result") == {"ok": True}, out
    assert "stale-session" in calls and calls[-1] == "fresh-session", calls
