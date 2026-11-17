"""Cognee-backed RFQ chat memory service.

Runs TWO independent listeners (plan §0.B) -- not one shared LAN-facing
port with an "internal by convention" trust model:

  * `chat_app`, bound to config.CHAT_HOST:CHAT_PORT (this machine's NetBird
    mesh IP, e.g. 100.121.36.255:8108) -- JWT-verified chat routes, called
    by accomplish-ui's daemon.
  * `internal_app`, bound to 127.0.0.1:config.INTERNAL_PORT (loopback only,
    8109) -- ingest/reset routes, called only by other same-host backend
    processes (fastapi_router.py, upload_server.py, hitl_router.py). This
    port is genuinely unreachable from the LAN/frontend/daemon, not merely
    unauthenticated -- nothing outside this host can open a TCP connection
    to it at all.

Both apps run concurrently in one process via asyncio.gather over two
uvicorn.Server instances -- see main() at the bottom.
"""

import asyncio
import inspect
import logging
import os

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field
import uvicorn

# config MUST be imported before cognee -- see ingest.py's identical comment
# (config.py sets ENABLE_BACKEND_ACCESS_CONTROL/REQUIRE_AUTHENTICATION env
# vars that cognee reads once during its own module-level init).
import config
import cognee

import ingest
import query
import versioning
import citation_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("rfq_memory.service")

# ---------------------------------------------------------------------------
# Cognee bootstrap -- point it at the existing Ollama instance (plan §8/§15),
# this repo's own database/cognee_data/ folder, and the dedicated
# cognee_memory_db Postgres database for graph+relational storage (see
# config.py's own comment on COGNEE_RELATIONAL_DB_CONFIG for why Postgres
# instead of Cognee's embedded default). One shared function
# (config.configure_cognee) so this and any standalone test script apply
# identical settings.
# ---------------------------------------------------------------------------
config.configure_cognee(cognee)
citation_store.ensure_schema()


def _ollama_reachable() -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(f"{config.OLLAMA_ENDPOINT}/api/tags", timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


# =============================================================================
# LAN-facing chat app -- JWT required on every route.
# =============================================================================
chat_app = FastAPI(title="RFQ Memory — Chat")


@chat_app.get("/health")
async def health():
    ollama_ok = _ollama_reachable()
    return {"status": "ok" if ollama_ok else "degraded", "ollama_reachable": ollama_ok}


class RetrieveRequest(BaseModel):
    question: str
    session_id: str
    top_k: int = 10
    node_set_filter: list[str] | None = None


@chat_app.post("/rfq/{rfq_id}/chat/retrieve")
async def chat_retrieve(rfq_id: str, body: RetrieveRequest, token: dict = Depends(config.verify_token)):
    # token["rfq_id"] == rfq_id is already guaranteed by auth.verify_token
    # itself (it checks the JWT payload's rfq_id against this exact route's
    # own rfq_id path param) -- using `rfq_id` (the path value) below is
    # therefore equivalent to using the verified token's own claim, per
    # plan §0/§10's requirement that this value always come from a verified
    # source, never trusted from the request body.
    result = await query.retrieve_rfq_context(
        rfq_id=rfq_id,
        question=body.question,
        session_id=body.session_id,
        top_k=body.top_k,
        node_set_filter=body.node_set_filter,
    )
    # Company questions also read the masters, in their own search (see query.retrieve_company_masters). Never mixed into the
    # RFQ's own chunks' tag filter: those chunks are cited to their masters rows, and the RFQ's rows are untouched.
    masters = await query.retrieve_company_masters(body.question)
    if masters:
        # Masters first: the chat passes only the first few memory chunks to the model, and a company question is answered by them.
        result["chunks"] = masters + list(result.get("chunks", []))
        result["matched"] = True
        result["warning"] = None
    return {"rfq_id": rfq_id, **result}


class RememberRequest(BaseModel):
    session_id: str
    question: str
    answer: str


def _llm_writes_enabled() -> bool:
    """Cognee's remember/add/cognify run LLM extraction. On the default local setup that is the SAME Ollama (one 8 GB GPU,
    ~3.5 tokens/s) that answers the user's chat questions: one burst queued 41 requests (each up to 9m50s, then retried) and
    starved every answer for hours (2026-11-05). So every write path refuses unless RFQ_MEMORY_LLM_WRITES=1, whichever
    caller (daemon, upload-server, bridge, pipeline) asks. Reads (retrieve) stay on: they only embed."""
    return os.environ.get("RFQ_MEMORY_LLM_WRITES") == "1"


@chat_app.post("/rfq/{rfq_id}/chat/remember")
async def chat_remember(rfq_id: str, body: RememberRequest, token: dict = Depends(config.verify_token)):
    if not _llm_writes_enabled():
        return {"ok": True, "skipped": "RFQ_MEMORY_LLM_WRITES is off"}
    await _limited(query.remember_turn(rfq_id, body.session_id, body.question, body.answer))
    return {"ok": True}


# =============================================================================
# Loopback-only internal app -- ingest/reset. No JWT (plan §0.B: network-
# level restriction via bind address IS the security boundary here, not an
# auth header) -- only reachable by same-host backend processes.
# =============================================================================
internal_app = FastAPI(title="RFQ Memory — Internal")


class IngestRequest(BaseModel):
    rfq_id: str
    version: int
    source: str
    tool_result: dict | None = None


@internal_app.post("/internal/memory/ingest")
async def internal_ingest(body: IngestRequest):
    # Fire-and-forget from the caller's perspective (fastapi_router.py/
    # upload_server.py/hitl_router.py never await the real work) -- accept
    # immediately, do the actual cognee.add()/cognify() as a background
    # task so this HTTP response returns fast regardless of Cognee's own
    # LLM-call-heavy latency (plan §9/§18).
    if not _llm_writes_enabled():
        return {"accepted": False, "skipped": "RFQ_MEMORY_LLM_WRITES is off"}
    _spawn(ingest.ingest_stage(body.rfq_id, body.version, body.source, body.tool_result))
    return {"accepted": True}


# The event loop only keeps weak references to tasks; holding them here stops a long cognify from being
# garbage-collected mid-run.
_background_tasks: set = set()


# Even with writes on, at most RFQ_MEMORY_MAX_CONCURRENT Cognee LLM jobs run at once (default 1); the rest wait here.
# ponytail: one process-wide limit; per-RFQ fairness only if one RFQ's burst ever blocks the others.
_MAX_CONCURRENT = max(1, int(os.environ.get("RFQ_MEMORY_MAX_CONCURRENT") or 1))
_write_slots = asyncio.Semaphore(_MAX_CONCURRENT)
_running = 0
_queued = 0


async def _limited(coro):
    """Await one write job once a slot is free. Counts feed GET /internal/memory/status."""
    global _running, _queued
    _queued += 1
    try:
        await _write_slots.acquire()
    except BaseException:
        coro.close()
        raise
    finally:
        _queued -= 1
    _running += 1
    try:
        return await coro
    finally:
        _running -= 1
        _write_slots.release()


def _spawn(coro) -> None:
    task = asyncio.create_task(_limited(coro))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


class AttachmentIngestRequest(BaseModel):
    """A file the user attached in the RFQ assistant, already reduced to text by the caller."""
    rfq_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
    attachment_id: str = Field(min_length=1, max_length=128)
    filename: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1, max_length=2_000_000)


@internal_app.post("/internal/memory/ingest-attachment", status_code=202)
async def internal_ingest_attachment(body: AttachmentIngestRequest):
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="text is blank")
    if not _llm_writes_enabled():
        return {"accepted": False, "skipped": "RFQ_MEMORY_LLM_WRITES is off"}
    _spawn(ingest.ingest_attachment(body.rfq_id, body.attachment_id, body.filename, body.text))
    return {"accepted": True}


class ResetRequest(BaseModel):
    rfq_id: str


@internal_app.post("/internal/memory/reset")
async def internal_reset(body: ResetRequest):
    await versioning.prune_rfq_dataset(body.rfq_id)
    deleted = citation_store.delete_citations(body.rfq_id)
    return {"ok": True, "citations_deleted": deleted}


@internal_app.get("/internal/memory/status")
async def internal_status():
    return {"writesEnabled": _llm_writes_enabled(),
            "provider": "openrouter" if getattr(config, "_USE_OPENROUTER", False) else "ollama",
            "maxConcurrent": _MAX_CONCURRENT, "running": _running, "queued": _queued,
            "recent": list(ingest.RECENT_JOBS)[:20]}


async def _cognee_call(fn, *args, **kwargs):
    """Cognee's helpers are sync or async depending on the version: await only when they return an awaitable."""
    result = fn(*args, **kwargs)
    return await result if inspect.isawaitable(result) else result


@internal_app.get("/internal/memory/graph")
async def internal_graph(limit: int = 600, include_chunks: bool = False):
    """The company knowledge graph as Cognee holds it: entities (parts, suppliers, assemblies, RFQs...), their types, and the
    labelled relations between them. Text and embeddings are left out; chunks are included only when asked for."""
    from cognee.infrastructure.databases.graph import get_graph_engine

    limit = max(1, min(limit, 2000))
    engine = await get_graph_engine()
    nodes, edges = await engine.get_graph_data()
    keep = {"Entity", "EntityType", "NodeSet"} | ({"TextSummary", "DocumentChunk", "TextDocument"} if include_chunks else set())
    # The most connected nodes first: the core of the graph stays readable at any limit; the long tail is counted, not drawn.
    degree: dict[str, int] = {}
    for s, t, _rel, _props in edges:
        degree[str(s)] = degree.get(str(s), 0) + 1
        degree[str(t)] = degree.get(str(t), 0) + 1
    candidates = [(str(node_id), props or {}) for node_id, props in nodes if (props or {}).get("type") in keep]
    candidates.sort(key=lambda c: degree.get(c[0], 0), reverse=True)
    kept: dict[str, dict] = {}
    for node_id, props in candidates[:limit]:
        kept[node_id] = {
            "id": node_id,
            "label": str(props.get("name") or (props.get("text") or "")[:60] or props.get("type")),
            "type": props.get("type"),
            "degree": degree.get(node_id, 0),
            "properties": {k: v for k, v in props.items() if k not in ("text", "embedding") and isinstance(v, (str, int, float, bool, type(None)))},
        }
    out_edges = [
        {"source": str(s), "target": str(t), "relation": str(rel)}
        for s, t, rel, _ in edges
        if str(s) in kept and str(t) in kept
    ][: limit * 3]
    counts: dict[str, int] = {}
    for n in kept.values():
        counts[n["type"]] = counts.get(n["type"], 0) + 1
    return {"nodes": list(kept.values()), "edges": out_edges, "counts": counts, "total": {"nodes": len(nodes), "edges": len(edges)}}


class MastersRequest(BaseModel):
    sheets: list[dict] = Field(min_length=1, max_length=200)


@internal_app.post("/internal/memory/ingest-masters", status_code=202)
async def internal_ingest_masters(body: MastersRequest):
    """Company masters, parsed in the browser, into Cognee in the background (one job; reported on memory:job)."""
    _spawn(ingest.ingest_admin_masters(body.sheets))
    return {"accepted": True, "sheets": len(body.sheets)}


@internal_app.get("/internal/memory/datasets")
async def internal_datasets():
    """Every Cognee dataset with its document count, read from Cognee itself (the admin Cognee page shows these)."""
    out = []
    for d in await _cognee_call(cognee.datasets.list_datasets):
        docs = await _cognee_call(cognee.datasets.list_data, d.id)
        out.append({"name": d.name, "id": str(d.id), "documents": len(docs)})
    return {"datasets": out}


@internal_app.get("/internal/memory/datasets/{name}/documents")
async def internal_dataset_documents(name: str):
    datasets = await _cognee_call(cognee.datasets.list_datasets)
    match = next((d for d in datasets if d.name == name), None)
    if match is None:
        raise HTTPException(status_code=404, detail="no such dataset")
    docs = await _cognee_call(cognee.datasets.list_data, match.id)
    return {"dataset": name, "documents": [{"name": getattr(x, "name", ""), "mime": getattr(x, "mime_type", ""), "created": str(getattr(x, "created_at", "") or "")} for x in docs]}


@internal_app.get("/internal/memory/datasets/{name}/inventory")
async def internal_dataset_inventory(name: str):
    """What Cognee's graph holds for the dataset: node types with counts and a few samples (empty until a cognify finished)."""
    return {"dataset": name, "inventory": await _cognee_call(cognee.get_schema_inventory, dataset=name, samples_per_type=3)}


class SearchRequest(BaseModel):
    rfq_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
    question: str = Field(min_length=1, max_length=2000)


@internal_app.post("/internal/memory/search")
async def internal_search(body: SearchRequest):
    """The admin search: what retrieval returns for one RFQ's memory (same path the chat uses; no token, loopback only)."""
    return await query.retrieve_rfq_context(rfq_id=body.rfq_id, question=body.question, session_id="admin-search", top_k=8)


@internal_app.get("/health")
async def internal_health():
    return {"status": "ok"}


async def main():
    chat_config = uvicorn.Config(chat_app, host=config.CHAT_HOST, port=config.CHAT_PORT, log_level="info")
    internal_config = uvicorn.Config(internal_app, host=config.INTERNAL_HOST, port=config.INTERNAL_PORT, log_level="info")
    chat_server = uvicorn.Server(chat_config)
    internal_server = uvicorn.Server(internal_config)

    logger.info(
        "[MEMORY SERVICE] starting -- chat=%s:%s (LAN) internal=%s:%s (loopback-only)",
        config.CHAT_HOST, config.CHAT_PORT, config.INTERNAL_HOST, config.INTERNAL_PORT,
    )
    await asyncio.gather(chat_server.serve(), internal_server.serve())


if __name__ == "__main__":
    asyncio.run(main())
