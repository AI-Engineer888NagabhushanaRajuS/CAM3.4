"""Bounded Cognee writes in the rfq-memory service: a semaphore around every write job, and its status route."""
import asyncio
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(__file__))
from test_rfq_memory_attachment import MEMORY_DIR, _load, stubs  # noqa: E402,F401  (stubs is a fixture)


def service(monkeypatch, limit=None, writes="1"):
    if limit is None:
        monkeypatch.delenv("RFQ_MEMORY_MAX_CONCURRENT", raising=False)
    else:
        monkeypatch.setenv("RFQ_MEMORY_MAX_CONCURRENT", limit)
    if writes is None:
        monkeypatch.delenv("RFQ_MEMORY_LLM_WRITES", raising=False)
    else:
        monkeypatch.setenv("RFQ_MEMORY_LLM_WRITES", writes)
    return _load("memory_service_limits", os.path.join(MEMORY_DIR, "memory_service.py"))


async def run_jobs(svc, n):
    """Spawn n jobs that each hold their slot for a moment; return the highest number running together."""
    state = {"now": 0, "peak": 0}
    gate = asyncio.Event()

    async def job():
        state["now"] += 1
        state["peak"] = max(state["peak"], state["now"])
        await gate.wait()
        state["now"] -= 1

    for _ in range(n):
        svc._spawn(job())
    await asyncio.sleep(0.05)
    during = (svc._running, svc._queued)
    gate.set()
    while svc._background_tasks:
        await asyncio.gather(*list(svc._background_tasks))
    return state["peak"], during


def test_five_jobs_with_limit_one_never_overlap(stubs, monkeypatch):
    svc = service(monkeypatch)
    peak, during = asyncio.run(run_jobs(svc, 5))
    assert peak == 1
    assert during == (1, 4)                       # one running, four waiting their turn
    assert (svc._running, svc._queued) == (0, 0)  # everything drained


def test_limit_is_configurable(stubs, monkeypatch):
    svc = service(monkeypatch, limit="2")
    peak, during = asyncio.run(run_jobs(svc, 5))
    assert peak == 2 and during == (2, 3)


@pytest.mark.parametrize("bad", ["0", "-3", ""])
def test_a_nonsense_limit_still_allows_one_job(stubs, monkeypatch, bad):
    assert service(monkeypatch, limit=bad)._MAX_CONCURRENT == 1


def test_a_failing_job_frees_its_slot(stubs, monkeypatch):
    svc = service(monkeypatch)

    async def scenario():
        async def boom():
            raise RuntimeError("cognee failed")
        svc._spawn(boom())
        await asyncio.gather(*list(svc._background_tasks), return_exceptions=True)
        return await asyncio.wait_for(svc._limited(asyncio.sleep(0, "next")), 1)

    assert asyncio.run(scenario()) == "next"
    assert (svc._running, svc._queued) == (0, 0)


def test_remember_turn_goes_through_the_same_limit(stubs, monkeypatch):
    svc = service(monkeypatch)
    state = {"now": 0, "peak": 0}

    async def remember(*args):
        state["now"] += 1
        state["peak"] = max(state["peak"], state["now"])
        await asyncio.sleep(0.01)
        state["now"] -= 1

    svc.query.remember_turn = remember
    body = svc.RememberRequest(session_id="s", question="q", answer="a")

    async def scenario():
        await asyncio.gather(*(svc.chat_remember("RFQ-1", body, token={}) for _ in range(4)))

    asyncio.run(scenario())
    assert state["peak"] == 1


def test_status_route_reports_settings_and_counts(stubs, monkeypatch):
    svc = service(monkeypatch, limit="3")
    with TestClient(svc.internal_app) as client:
        assert client.get("/internal/memory/status").json() == {
            "writesEnabled": True, "provider": "ollama", "maxConcurrent": 3, "running": 0, "queued": 0, "recent": []}
        svc.config._USE_OPENROUTER = True
        assert client.get("/internal/memory/status").json()["provider"] == "openrouter"


def test_guard_is_unchanged_status_reports_writes_off(stubs, monkeypatch):
    svc = service(monkeypatch, writes=None)
    spawned = []
    monkeypatch.setattr(svc, "_spawn", spawned.append)
    with TestClient(svc.internal_app) as client:
        assert client.get("/internal/memory/status").json()["writesEnabled"] is False
        res = client.post("/internal/memory/ingest", json={"rfq_id": "RFQ-1", "version": 1, "source": "file_upload"})
        assert res.json()["accepted"] is False and "RFQ_MEMORY_LLM_WRITES" in res.json()["skipped"]
    assert spawned == []
