"""
SPEC-017 bug: the async upload/start endpoints call the sync trigger_dify_workflow_internal
directly on the event loop. In Temporal mode that function calls asyncio.run(), which raises
inside a running loop; its broad except then reports CONNECTION_REFUSED, so no workflow starts.
"""
import asyncio
import os
import sys
import types

import pytest

FR_DIR = os.path.join(os.path.dirname(__file__), "..", "fastapi-router")


def _load_upload_server(monkeypatch):
    sys.path.insert(0, os.path.abspath(FR_DIR))
    try:
        import upload_server as us
    except ImportError as e:
        pytest.skip(f"upload_server deps unavailable: {e}")
    finally:
        sys.path.remove(os.path.abspath(FR_DIR))
    monkeypatch.setattr(us, "USE_TEMPORAL", True)
    monkeypatch.setattr(us.db, "ensure_processing_guard_schema", lambda: None)
    monkeypatch.setattr(us.db, "try_start_pipeline_run", lambda rfq_id: True)
    fake_client = types.ModuleType("client")

    calls = []

    async def start_rfq_workflow(rfq_id, profile_name=None, started_by=None, started_by_email=None):
        calls.append(("start", rfq_id, profile_name) if not started_by else ("start", rfq_id, profile_name, started_by, started_by_email))
        return f"rfq-{rfq_id}"

    async def resume_rfq_workflow(rfq_id, profile_name="Standard_BOM_Flow", started_by=None, started_by_email=None):
        calls.append(("resume", rfq_id) if not started_by else ("resume", rfq_id, started_by, started_by_email))
        return f"rfq-{rfq_id}", "RESUMED"

    fake_client.start_rfq_workflow = start_rfq_workflow
    fake_client.resume_rfq_workflow = resume_rfq_workflow
    monkeypatch.setitem(sys.modules, "client", fake_client)
    us.calls = calls
    return us


def test_start_dify_endpoint_resumes_the_parked_workflow_inside_event_loop(monkeypatch):
    # GET /api/dify/start is the UI's "continue" after the QuoteWin/Costing upload.
    us = _load_upload_server(monkeypatch)
    result = asyncio.run(us.start_dify_workflow("CE-LOOP-1", token={}))
    assert result["dify_status"] == "TRIGGERED", result
    assert result["success"] is True
    assert result["dify_response"]["workflow_id"] == "rfq-CE-LOOP-1"
    assert result["dify_response"]["outcome"] == "RESUMED"
    assert us.calls == [("resume", "CE-LOOP-1")]


def test_an_upload_starts_a_run_it_does_not_resume_one(monkeypatch):
    us = _load_upload_server(monkeypatch)
    status, summary = us.trigger_dify_workflow_internal("CE-UP-1")
    assert status == "TRIGGERED" and summary["outcome"] == "STARTED", summary
    assert us.calls == [("start", "CE-UP-1", None)]


def test_an_upload_can_pick_its_routing_profile(monkeypatch):
    # Per-upload profile (RFQ_Flow vs Standard_BOM_Flow); None means the configured default.
    us = _load_upload_server(monkeypatch)
    status, summary = us.trigger_dify_workflow_internal("CE-PROF-1", profile="RFQ_Flow")
    assert status == "TRIGGERED" and summary["outcome"] == "STARTED", summary
    assert us.calls == [("start", "CE-PROF-1", "RFQ_Flow")]


def test_who_clicked_reaches_the_run_and_the_tracking_row(monkeypatch):
    # SPEC-021: the signed-in name and email (as the app reports them) go into the workflow memo and rfq_process_tracking.triggered_by.
    us = _load_upload_server(monkeypatch)
    tracked = []
    monkeypatch.setattr(us, "_record_trigger", lambda rfq, label: tracked.append((rfq, label)))
    result = asyncio.run(us.start_dify_workflow("CE-WHO-1", token={}, x_cam_user="DigiBull%20Tester", x_cam_user_email="tester%40digibull.ai"))
    assert result["success"] is True
    assert us.calls == [("resume", "CE-WHO-1", "DigiBull Tester", "tester@digibull.ai")]
    assert tracked == [("CE-WHO-1", "DigiBull Tester <tester@digibull.ai>")]


def test_identity_headers_are_cleaned(monkeypatch):
    us = _load_upload_server(monkeypatch)
    assert us._who("%0Abad%00name") == "badname"          # control characters dropped
    assert us._email("not an email") is None and us._email('a"b@c.d') is None and us._email("a@b.co") == "a@b.co"
    assert us._label("A", None) == "A" and us._label(None, "a@b.co") is None
