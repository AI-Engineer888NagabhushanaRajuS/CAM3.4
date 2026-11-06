"""The router tells the daemon (SSE hub for the web UI) what the pipeline is doing.

Found by reading how the UI is driven, then confirmed against the code:
 1. notify_skill_progress posted to a hard-coded mesh IP (http://100.121.36.255:9334), so a daemon on
    this machine never heard about progress. It now reads CAM_DAEMON_URL.
 2. The UI opens its review screen only on the daemon's `hitl:request` SSE event. The Dify DMR sent it
    (HTTP Request 3: POST /api/internal/trigger-hitl {rfqId, stage, hitlType}); the Temporal path never
    did, so a run paused at a human gate showed nothing to the user.
"""
import json
import os
import sys

import pytest

FR_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "fastapi-router"))
TOOL = "centum_intake__standardize_scrub_bom"
DAEMON = "http://daemon.test:9334"


@pytest.fixture
def fr(monkeypatch):
    sys.path.insert(0, FR_DIR)
    other_config = sys.modules.pop("config", None)  # another test file may have loaded temporal_worker's
    try:
        import fastapi_router
    finally:
        sys.path.remove(FR_DIR)
        if other_config is not None:
            sys.modules["config"] = other_config
    monkeypatch.setenv("CAM_DAEMON_URL", DAEMON)
    monkeypatch.setattr(fastapi_router, "get_all_live_tool_names", lambda: [TOOL])
    monkeypatch.setattr(fastapi_router, "get_active_version", lambda rfq: 1)
    monkeypatch.setattr(fastapi_router, "get_skill_by_code", lambda name: {
        "skillCode": "M03.1", "skillName": "Scrub", "macroCategory": 1, "macroCategoryName": "intake"})
    monkeypatch.setattr(fastapi_router, "set_hitl_required", lambda *a, **k: None)
    monkeypatch.setattr(fastapi_router, "increment_skill_index", lambda *a, **k: None)
    monkeypatch.setattr(fastapi_router.rfq_memory_client, "queue_ingestion", lambda **k: None)
    return fastapi_router


def _run(fr, monkeypatch, tool_result):
    posted = []
    monkeypatch.setattr(fr, "call_tool", lambda tool_name, arguments: {
        "result": {"content": [{"text": json.dumps(tool_result)}]}})
    monkeypatch.setattr(fr.httpx, "post", lambda url, **kw: posted.append((url, kw.get("json"))))
    fr.execute_tool(fr.ToolExecuteRequest(rfq_id="R1", tool_name=TOOL, arguments={"rfq_id": "R1"}))
    return posted


def test_progress_goes_to_the_configured_daemon(fr, monkeypatch):
    posted = _run(fr, monkeypatch, {"status": "success"})
    urls = [u for u, _ in posted]
    assert urls and all(u == f"{DAEMON}/api/internal/emit-skill-progress" for u in urls), urls


def test_a_human_gate_pushes_hitl_request_to_the_daemon(fr, monkeypatch):
    posted = _run(fr, monkeypatch, {"status": "success", "hitl": 1})
    pushes = [(u, body) for u, body in posted if u.endswith("/api/internal/trigger-hitl")]
    assert pushes == [(f"{DAEMON}/api/internal/trigger-hitl",
                       {"rfqId": "R1", "stage": TOOL, "hitlType": "approval"})], posted


def test_a_hitl_required_flag_is_a_human_gate_too(fr, monkeypatch):
    # RFQ_Flow intake tools (scan_local_file) report the gate as hitl_required, not hitl
    posted = _run(fr, monkeypatch, {"status": "success", "hitl_required": True})
    assert [u for u, _ in posted if u.endswith("/api/internal/trigger-hitl")], posted


def test_a_normal_step_does_not_ask_for_a_review(fr, monkeypatch):
    posted = _run(fr, monkeypatch, {"status": "success"})
    assert not [u for u, _ in posted if u.endswith("/api/internal/trigger-hitl")], posted


def test_a_failed_step_is_not_a_review_request(fr, monkeypatch):
    posted = _run(fr, monkeypatch, {"status": "failed", "error": "boom"})
    assert not [u for u, _ in posted if u.endswith("/api/internal/trigger-hitl")], posted


def test_daemon_being_down_never_breaks_the_tool_call(fr, monkeypatch):
    def refuse(url, **kw):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(fr, "call_tool", lambda tool_name, arguments: {
        "result": {"content": [{"text": json.dumps({"status": "success", "hitl": 1})}]}})
    monkeypatch.setattr(fr.httpx, "post", refuse)
    resp = fr.execute_tool(fr.ToolExecuteRequest(rfq_id="R1", tool_name=TOOL, arguments={"rfq_id": "R1"}))
    assert resp.status_code == 200
