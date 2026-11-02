"""
SPEC-017 bug: hitl_decision logged a failed Temporal signal and still answered
{"status": "ok"}. The human's decision was lost, the workflow stayed parked at its
gate, and the UI showed success.
"""
import os
import sys
import types

import pytest

FR_DIR = os.path.join(os.path.dirname(__file__), "..", "fastapi-router")


def _load_hitl_router(monkeypatch):
    sys.path.insert(0, os.path.abspath(FR_DIR))
    try:
        import hitl_router as hr
    except ImportError as e:
        pytest.skip(f"hitl_router deps unavailable: {e}")
    finally:
        sys.path.remove(os.path.abspath(FR_DIR))
    monkeypatch.setenv("CAM_USE_TEMPORAL", "true")
    return hr


def test_failed_temporal_signal_is_reported_not_ok(monkeypatch):
    from fastapi.testclient import TestClient

    hr = _load_hitl_router(monkeypatch)
    fake_client = types.ModuleType("client")

    async def send_hitl_approve(rfq_id, resolution):
        raise RuntimeError("temporal unreachable")

    fake_client.send_hitl_approve = send_hitl_approve
    monkeypatch.setitem(sys.modules, "client", fake_client)

    resp = TestClient(hr.app).post(
        "/api/rfq/CE-SIG-1/hitl/decision", json={"approved": True, "stage": "resolve_final_selection"}
    )
    assert resp.status_code >= 500, f"a lost decision must not look successful: {resp.status_code} {resp.text}"
    assert resp.json().get("status") != "ok"
