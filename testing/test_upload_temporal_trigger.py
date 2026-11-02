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

    async def start_rfq_workflow(rfq_id, profile_name="Standard_BOM_Flow", client=None):
        return f"rfq-{rfq_id}"

    fake_client.start_rfq_workflow = start_rfq_workflow
    monkeypatch.setitem(sys.modules, "client", fake_client)
    return us


def test_start_dify_endpoint_starts_temporal_workflow_inside_event_loop(monkeypatch):
    us = _load_upload_server(monkeypatch)
    result = asyncio.run(us.start_dify_workflow("CE-LOOP-1", token={}))
    assert result["dify_status"] == "TRIGGERED", result
    assert result["success"] is True
    assert result["dify_response"]["workflow_id"] == "rfq-CE-LOOP-1"
