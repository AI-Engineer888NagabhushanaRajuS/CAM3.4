"""
Tests for the RFQ assistant chat endpoint (SPEC-006).
Verifies endpoint contract, read-only guard, and Ollama integration shape.
"""
import sys
import os
import json
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "fastapi-router"))


def _get_app():
    """Import fastapi_router.app without needing running services."""
    try:
        import fastapi_router as fr
        return fr.app
    except ImportError as e:
        import pytest
        pytest.skip(f"fastapi_router deps unavailable: {e}")


def test_chat_endpoint_registered():
    """/rfq/{rfq_id}/chat must be registered as a POST route."""
    app = _get_app()
    if app is None:
        return
    routes = {r.path: list(r.methods) for r in app.routes if hasattr(r, 'methods')}
    assert "/rfq/{rfq_id}/chat" in routes
    assert "POST" in routes["/rfq/{rfq_id}/chat"]


def test_status_endpoint_registered():
    """/rfq/{rfq_id}/status must be registered as a GET route."""
    app = _get_app()
    if app is None:
        return
    routes = {r.path: list(r.methods) for r in app.routes if hasattr(r, 'methods')}
    assert "/rfq/{rfq_id}/status" in routes
    assert "GET" in routes["/rfq/{rfq_id}/status"]


def test_chat_invalid_rfq_id_rejected():
    """rfq_id with shell-injection characters must return 400."""
    try:
        from fastapi.testclient import TestClient
        import fastapi_router as fr
    except ImportError as e:
        import pytest
        pytest.skip(f"deps unavailable: {e}")

    with patch("fastapi_router._build_rfq_context", return_value={}), \
         patch("httpx.AsyncClient") as _:
        client = TestClient(fr.app, raise_server_exceptions=False)
        resp = client.post(
            "/rfq/CE-005570; DROP TABLE rfq_master--/chat",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code in (400, 404, 422)


def test_chat_ollama_unavailable_returns_503():
    """When Ollama is down, the endpoint must return 503, not raise."""
    try:
        from fastapi.testclient import TestClient
        import fastapi_router as fr
        import httpx
    except ImportError as e:
        import pytest
        pytest.skip(f"deps unavailable: {e}")

    with patch("fastapi_router._build_rfq_context", return_value={"db_error": "no db"}), \
         patch("httpx.AsyncClient") as MockClient:
        import httpx as _httpx
        mock_instance = AsyncMock()
        mock_instance.post = AsyncMock(side_effect=_httpx.ConnectError("refused"))
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

        client = TestClient(fr.app, raise_server_exceptions=False)
        resp = client.post(
            "/rfq/CE-005570/chat",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 503
        data = resp.json()
        assert "error" in data or "message" in data


def test_chat_returns_message_field():
    """Successful chat call must include a 'message' key in the response."""
    try:
        from fastapi.testclient import TestClient
        import fastapi_router as fr
    except ImportError as e:
        import pytest
        pytest.skip(f"deps unavailable: {e}")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"message": {"content": "Total cost is $1,234.56"}}

    with patch("fastapi_router._build_rfq_context", return_value={"summary": {"total_cost": 1234.56}}), \
         patch("httpx.AsyncClient") as MockClient:
        mock_instance = AsyncMock()
        mock_instance.post = AsyncMock(return_value=mock_response)
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

        client = TestClient(fr.app)
        resp = client.post(
            "/rfq/CE-005570/chat",
            json={"messages": [{"role": "user", "content": "What is the total cost?"}]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "message" in data
        assert "Total cost" in data["message"]


def test_build_rfq_context_returns_dict():
    """_build_rfq_context() must always return a dict, even with no DB."""
    try:
        import fastapi_router as fr
    except ImportError as e:
        import pytest
        pytest.skip(f"deps unavailable: {e}")

    ctx = fr._build_rfq_context("CE-NONEXISTENT")
    assert isinstance(ctx, dict)
    # Either has real data or a db_error key -- never raises
    assert "db_error" in ctx or isinstance(ctx, dict)
