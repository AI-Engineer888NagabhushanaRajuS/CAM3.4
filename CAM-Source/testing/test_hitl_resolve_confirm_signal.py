"""The zero-conflict confirm of resolve_final_selection (POST /final-selection with an empty
resolutions list) advanced rfq_process_stage but never signalled the Temporal workflow, so
the run stayed parked at its gate forever. The non-empty branch does send the signal.
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


class _Cursor:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, *args, **kwargs):
        pass

    def fetchone(self):
        return (0,)


class _Conn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return _Cursor()


def test_empty_resolve_confirm_signals_the_waiting_workflow(monkeypatch):
    from fastapi.testclient import TestClient

    hr = _load_hitl_router(monkeypatch)
    rfq = "CE-CONFIRM-1"

    signals = []
    fake_client = types.ModuleType("client")
    fake_client.get_workflow_id = lambda rfq_id: f"rfq-{rfq_id}"

    async def send_hitl_signal(workflow_id, decision):
        signals.append((workflow_id, decision))

    fake_client.send_hitl_signal = send_hitl_signal
    monkeypatch.setitem(sys.modules, "client", fake_client)

    monkeypatch.setattr(hr, "_resolve_cbom_key", lambda rfq_id: rfq_id)
    monkeypatch.setattr(hr, "get_logic_connection", lambda: _Conn())
    monkeypatch.setattr(hr, "_advance_past_resolve_final_selection", lambda rfq_id: 6)
    hr.app.dependency_overrides[hr.auth.verify_token] = lambda: {"rfq_id": rfq}
    try:
        resp = TestClient(hr.app).post(f"/api/rfq/{rfq}/final-selection", json={"resolutions": []})
    finally:
        hr.app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    assert signals == [(f"rfq-{rfq}", {"action": "approve"})], signals
    assert resp.json()["signal_delivered"] is True
