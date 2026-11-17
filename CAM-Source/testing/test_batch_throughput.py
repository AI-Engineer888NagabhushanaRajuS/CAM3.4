"""Batch throughput: 25 RFQs started together must queue in Temporal and ask the local model once per distinct header layout.

Found 2026-11-17 on the real 25-batch run: every RFQ's workflow started its tool calls at once, the calls waited on one DuckDB file lock and
one Ollama slot behind 30 s / 10 min HTTP timeouts, the timeouts fired while the work was still queued, the retries duplicated that work,
and all 25 workflows ended Failed with 0 exports. See temporal_worker/config.py and mcp-tools/scrub-intake/llm_mapping.py.
"""
import asyncio
import importlib
import json
import os
import sys
import threading
import time
import types

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "mcp-tools", "scrub-intake"))
sys.path.insert(0, os.path.join(ROOT, "temporal_worker"))

try:  # the intake image has the real client; the test environment may not
    import ollama  # noqa: F401
except ImportError:
    sys.modules["ollama"] = types.ModuleType("ollama")

import llm_mapping  # noqa: E402

REQUIRED = ("part_number", "mfg_part_number")
GOOD = json.dumps({"part_number": "Part Number", "mfg_part_number": "Mfg Part Number", "commodity": None})
MSGS = [{"role": "system", "content": "map"}, {"role": "user", "content": "headers: A, B"}]


class FakeClient:
    def __init__(self, content=GOOD, delay=0.0):
        self.calls, self.content, self.delay, self.kwargs = 0, content, delay, None

    def chat(self, **kw):
        self.calls += 1
        self.kwargs = kw
        time.sleep(self.delay)
        return {"message": {"content": self.content}}


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_mapping, "CACHE_DIR", str(tmp_path))
    fake = FakeClient()
    monkeypatch.setattr(llm_mapping, "_client", fake)
    return fake


def test_same_headers_are_asked_once(cache):
    first = llm_mapping.chat("m", MSGS, format="json", required=REQUIRED)
    second = llm_mapping.chat("m", MSGS, format="json", required=REQUIRED)
    assert cache.calls == 1
    assert first["message"]["content"] == second["message"]["content"] == GOOD
    assert cache.kwargs["format"] == "json" and cache.kwargs["keep_alive"]  # the model stays loaded between calls


def test_a_changed_prompt_or_model_is_a_new_question(cache):
    llm_mapping.chat("m", MSGS, required=REQUIRED)
    llm_mapping.chat("m", MSGS[:1] + [{"role": "user", "content": "headers: A, B, C"}], required=REQUIRED)
    llm_mapping.chat("other-model", MSGS, required=REQUIRED)
    assert cache.calls == 3


def test_a_mapping_without_a_required_field_is_never_made_permanent(cache):
    cache.content = json.dumps({"part_number": "Part Number", "mfg_part_number": None})
    llm_mapping.chat("m", MSGS, required=REQUIRED)
    llm_mapping.chat("m", MSGS, required=REQUIRED)
    assert cache.calls == 2  # asked again: the next answer may be complete


@pytest.mark.parametrize("bad", ["not json", "[1, 2]", json.dumps({"a": None}), ""])
def test_unusable_answers_are_not_cached(cache, bad):
    cache.content = bad
    llm_mapping.chat("m", MSGS, required=())
    llm_mapping.chat("m", MSGS, required=())
    assert cache.calls == 2


def test_concurrent_requests_for_one_layout_cost_one_model_call(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_mapping, "CACHE_DIR", str(tmp_path))
    slow = FakeClient(delay=0.3)
    monkeypatch.setattr(llm_mapping, "_client", slow)
    out = []
    threads = [threading.Thread(target=lambda: out.append(llm_mapping.chat("m", MSGS, required=REQUIRED)["message"]["content"])) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert slow.calls == 1 and out == [GOOD] * 6


def test_an_unwritable_cache_only_costs_speed(monkeypatch):
    monkeypatch.setattr(llm_mapping, "CACHE_DIR", os.path.join(os.devnull, "no", "such", "dir"))
    fake = FakeClient()
    monkeypatch.setattr(llm_mapping, "_client", fake)
    assert llm_mapping.chat("m", MSGS, required=REQUIRED)["message"]["content"] == GOOD


def test_the_four_standardizers_use_the_cached_call():
    for name in ("scrub_bom_processing", "quote_win_processing", "costing_sheet_processing", "erp_processing"):
        src = open(os.path.join(ROOT, "mcp-tools", "scrub-intake", name + ".py"), encoding="utf-8").read()
        assert "llm_mapping.chat(" in src and "ollama.chat(" not in src, name


def test_worker_cap_default_and_override(monkeypatch):
    monkeypatch.delenv("CAM_WORKER_MAX_ACTIVITIES", raising=False)
    import config
    assert importlib.reload(config).MAX_CONCURRENT_ACTIVITIES == 4
    monkeypatch.setenv("CAM_WORKER_MAX_ACTIVITIES", "2")
    assert importlib.reload(config).MAX_CONCURRENT_ACTIVITIES == 2
    monkeypatch.delenv("CAM_WORKER_MAX_ACTIVITIES")
    importlib.reload(config)


def test_worker_passes_the_cap_to_temporal(monkeypatch):
    pytest.importorskip("temporalio")
    import worker

    seen = {}

    class FakeWorker:
        def __init__(self, client, **kw):
            seen.update(kw)

        async def run(self):
            return None

    async def fake_connect(*a, **kw):
        return object()

    monkeypatch.setattr(worker, "Worker", FakeWorker)
    monkeypatch.setattr(worker.Client, "connect", fake_connect)
    monkeypatch.setattr(worker.config, "MAX_CONCURRENT_ACTIVITIES", 3)
    asyncio.run(worker.main())
    assert seen["max_concurrent_activities"] == 3
