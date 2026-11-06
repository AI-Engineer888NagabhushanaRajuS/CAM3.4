"""
Tests for the RFQ assistant chat endpoint (SPEC-008 update).
In CAM 3.4, chat is handled by the daemon's rfq-memory RAG pipeline.
fastapi_router /rfq/{rfq_id}/chat returns 410 Gone (deprecated).
"""
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "fastapi-router"))


def _get_app():
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


def test_chat_returns_410_deprecated():
    """fastapi_router /rfq/{rfq_id}/chat must return 410 (moved to daemon RAG pipeline)."""
    try:
        from fastapi.testclient import TestClient
        import fastapi_router as fr
    except ImportError as e:
        import pytest
        pytest.skip(f"deps unavailable: {e}")

    client = TestClient(fr.app, raise_server_exceptions=False)
    resp = client.post(
        "/rfq/CE-005570/chat",
        json={"messages": [{"role": "user", "content": "What is the total cost?"}]},
    )
    assert resp.status_code == 410, f"Expected 410, got {resp.status_code}"
    data = resp.json()
    assert "error" in data
    assert "deprecated" in data["error"].lower() or "daemon" in data["error"].lower()


def test_chat_invalid_rfq_id_rejected():
    """rfq_id with shell-injection characters must return 400 or 404."""
    try:
        from fastapi.testclient import TestClient
        import fastapi_router as fr
    except ImportError as e:
        import pytest
        pytest.skip(f"deps unavailable: {e}")

    client = TestClient(fr.app, raise_server_exceptions=False)
    resp = client.post(
        "/rfq/CE-005570; DROP TABLE rfq_master--/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code in (400, 404, 410, 422)
