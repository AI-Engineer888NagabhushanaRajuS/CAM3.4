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
    await query.remember_turn(rfq_id, body.session_id, body.question, body.answer)
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


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
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
