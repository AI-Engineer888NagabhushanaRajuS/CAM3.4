"""Chat-attachment ingestion for the rfq-memory service, without Cognee, Postgres or Docker.

memory_service.py and ingest.py import cognee, connect to Postgres and read JWT_SECRET at import time,
so those modules are replaced with stubs in sys.modules before the real files are loaded.
"""
import asyncio
import importlib.util
import os
import sys
import types

import pytest
import requests
from fastapi.testclient import TestClient

ROOT = os.path.join(os.path.dirname(__file__), "..")
MEMORY_DIR = os.path.join(ROOT, "mcp-tools", "rfq-memory")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def stubs(monkeypatch):
    calls = {"add": [], "cognify": [], "citations": []}

    async def add(data, dataset_name, node_set):
        calls["add"].append((data, dataset_name, node_set))

    async def cognify(datasets):
        calls["cognify"].append(datasets)

    cognee = types.SimpleNamespace(add=add, cognify=cognify, config=None)
    config = types.SimpleNamespace(
        RFQ_MEMORY_ENABLED=True,
        dataset_name_for=lambda rfq_id: f"rfq_{rfq_id}",
        node_set_tag_for=lambda rfq_id: f"rfq_{rfq_id}",
        configure_cognee=lambda module: None,
        verify_token=lambda: {},
        OLLAMA_ENDPOINT="http://unused",
    )
    citation_store = types.SimpleNamespace(
        store_citation=lambda text, rfq_id, citation: calls["citations"].append((text, rfq_id, citation)),
        ensure_schema=lambda: None,
        delete_citations=lambda rfq_id: 0,
    )
    for name, module in {
        "cognee": cognee, "config": config, "citation_store": citation_store,
        "versioning": types.SimpleNamespace(), "query": types.SimpleNamespace(),
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    ingest = _load("ingest", os.path.join(MEMORY_DIR, "ingest.py"))
    monkeypatch.setitem(sys.modules, "ingest", ingest)
    return ingest, calls


@pytest.fixture
def internal_client(stubs, monkeypatch):
    ingest, _ = stubs
    spawned = []

    async def fake_ingest_attachment(*args):
        spawned.append(args)

    monkeypatch.setattr(ingest, "ingest_attachment", fake_ingest_attachment)
    service = _load("memory_service_under_test", os.path.join(MEMORY_DIR, "memory_service.py"))
    with TestClient(service.internal_app) as client:
        yield client, spawned


def test_route_accepts_attachment_and_schedules_ingestion(internal_client, monkeypatch):
    monkeypatch.setenv("RFQ_MEMORY_LLM_WRITES", "1")   # writes are off by default, see the guard tests below
    client, spawned = internal_client
    body = {"rfq_id": "RFQ-1", "attachment_id": "a1", "filename": "terms.pdf", "text": "Net 45 days."}
    res = client.post("/internal/memory/ingest-attachment", json=body)
    assert res.status_code == 202
    assert res.json() == {"accepted": True}
    assert spawned == [("RFQ-1", "a1", "terms.pdf", "Net 45 days.")]


@pytest.mark.parametrize("value", [None, "", "0", "true", "yes"])
def test_llm_writes_are_refused_unless_explicitly_enabled(internal_client, monkeypatch, value):
    """Cognee writes run LLM jobs on the same Ollama that answers chat: 41 queued jobs starved every answer for hours
    (2026-11-05). Only the exact value "1" enables them; nothing is scheduled otherwise."""
    if value is None:
        monkeypatch.delenv("RFQ_MEMORY_LLM_WRITES", raising=False)
    else:
        monkeypatch.setenv("RFQ_MEMORY_LLM_WRITES", value)
    client, spawned = internal_client
    attach = {"rfq_id": "RFQ-1", "attachment_id": "a1", "filename": "terms.pdf", "text": "Net 45 days."}
    res = client.post("/internal/memory/ingest-attachment", json=attach)
    assert res.status_code == 202 and res.json()["accepted"] is False and "RFQ_MEMORY_LLM_WRITES" in res.json()["skipped"]
    stage = client.post("/internal/memory/ingest", json={"rfq_id": "RFQ-1", "version": 1, "source": "file_upload"})
    assert stage.status_code == 200 and stage.json()["accepted"] is False
    assert spawned == []


@pytest.mark.parametrize("bad", [
    {"attachment_id": "a1", "filename": "f.txt", "text": "x"},                      # rfq_id missing
    {"rfq_id": "RFQ 1; drop", "attachment_id": "a1", "filename": "f.txt", "text": "x"},  # unsafe rfq_id
    {"rfq_id": "RFQ-1", "attachment_id": "a1", "filename": "f.txt", "text": ""},     # empty text
    {"rfq_id": "RFQ-1", "attachment_id": "a1", "filename": "f.txt", "text": "  \n "},  # blank text
    {"rfq_id": "RFQ-1", "attachment_id": "a1", "filename": "", "text": "x"},          # no filename
])
def test_route_rejects_invalid_bodies(internal_client, bad):
    client, spawned = internal_client
    assert client.post("/internal/memory/ingest-attachment", json=bad).status_code == 422
    assert spawned == []


def test_long_attachment_is_split_and_every_piece_gets_its_own_citation(stubs):
    ingest, calls = stubs
    paragraph = "Supplier terms: payment net 45 days, 2% early-payment discount within 10 days. " * 10
    text = "\n".join([paragraph] * 6)
    result = asyncio.run(ingest.ingest_attachment("RFQ-1", "a1", "terms.pdf", text))

    pieces = len(calls["add"])
    assert result == {"status": "ok", "items": pieces}
    assert pieces > 1
    assert all(len(data) <= ingest.ATTACHMENT_PIECE_CHARS + 100 for data, _, _ in calls["add"])
    assert all(node_set == ["rfq_RFQ-1", "attachment"] for _, _, node_set in calls["add"])
    assert calls["cognify"] == [["rfq_RFQ-1"]]
    # The stored citation is keyed by exactly the text handed to cognee.add.
    assert [c[0] for c in calls["citations"]] == [data for data, _, _ in calls["add"]]
    first = calls["citations"][0][2]
    assert first["sourceType"] == "file_telemetry"
    assert first["identifier"] == {"rfq_id": "RFQ-1", "attachment_id": "a1", "filename": "terms.pdf", "part": 1}
    assert first["label"] == f"Attachment — terms.pdf (part 1/{pieces})"


def test_split_keeps_all_text_and_hard_cuts_huge_paragraphs(stubs):
    ingest, _ = stubs
    text = "short line\n" + "x" * 3000 + "\nlast line"
    pieces = ingest.split_attachment_text(text, max_chars=1000)
    assert all(len(p) <= 1000 for p in pieces)
    assert "".join(pieces).replace("\n", "") == text.replace("\n", "")


def test_client_swallows_connection_errors(monkeypatch):
    client = _load("rfq_memory_client_under_test", os.path.join(ROOT, "fastapi-router", "rfq_memory_client.py"))

    def refuse(*args, **kwargs):
        raise requests.ConnectionError("connection refused")

    monkeypatch.setattr(client.requests, "post", refuse)
    assert client.queue_attachment_ingestion("RFQ-1", "a1", "terms.pdf", "text") is None


def test_client_posts_the_attachment_body(monkeypatch):
    client = _load("rfq_memory_client_under_test", os.path.join(ROOT, "fastapi-router", "rfq_memory_client.py"))
    seen = {}
    monkeypatch.setattr(client.requests, "post", lambda url, json, timeout: seen.update(url=url, json=json))
    client.queue_attachment_ingestion("RFQ-1", "a1", "terms.pdf", "text")
    assert seen["url"].endswith("/internal/memory/ingest-attachment")
    assert seen["json"] == {"rfq_id": "RFQ-1", "attachment_id": "a1", "filename": "terms.pdf", "text": "text"}
