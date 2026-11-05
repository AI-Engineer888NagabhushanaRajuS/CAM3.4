"""Thin, fire-and-forget HTTP client to rfq_memory_server's loopback-only
internal ingest/reset endpoints (mcp-tools/rfq-memory/memory_service.py).

Every call here MUST carry an explicit rfq_id, version, and source (plan
§0.C -- never inferred from a DuckDB table, several of which have no
version column at all). Every call is wrapped so a failure here can NEVER
propagate to the caller -- ingestion is a best-effort side-effect, not a
step the RFQ pipeline/upload/HITL flow depends on succeeding (same
fail-open philosophy as this file's callers' own SSE-notification blocks).
"""

import os

import requests

RFQ_MEMORY_INTERNAL_URL = os.environ.get("RFQ_MEMORY_INTERNAL_URL", "http://127.0.0.1:8109")

# Short -- this is a fire-and-forget trigger; memory_service.py itself does
# the real cognee.add()/cognify() work in its own background task and
# returns 202 immediately, so this call should never legitimately take long.
_TIMEOUT_SECONDS = 2


def queue_ingestion(rfq_id: str, version: int, source: str, tool_result: dict | None = None) -> None:
    """Best-effort trigger -- swallows every exception itself so callers
    never need their own try/except around this call."""
    try:
        requests.post(
            f"{RFQ_MEMORY_INTERNAL_URL}/internal/memory/ingest",
            json={"rfq_id": rfq_id, "version": version, "source": source, "tool_result": tool_result or {}},
            timeout=_TIMEOUT_SECONDS,
        )
    except Exception as e:
        print(f"[MEMORY INGEST TRIGGER ERROR] rfq_id={rfq_id} source={source}: {e}")


def queue_attachment_ingestion(rfq_id: str, attachment_id: str, filename: str, text: str) -> None:
    """Best-effort trigger for a chat attachment's text (memory_service.py accepts with 202 and does
    add+cognify in the background). Same 2s timeout: only the request body upload is synchronous."""
    try:
        requests.post(
            f"{RFQ_MEMORY_INTERNAL_URL}/internal/memory/ingest-attachment",
            json={"rfq_id": rfq_id, "attachment_id": attachment_id, "filename": filename, "text": text},
            timeout=_TIMEOUT_SECONDS,
        )
    except Exception as e:
        print(f"[MEMORY ATTACHMENT TRIGGER ERROR] rfq_id={rfq_id} file={filename}: {e}")


def reset_memory(rfq_id: str) -> None:
    """Best-effort trigger for a full dataset prune -- see
    versioning.prune_rfq_dataset's own docstring for when this is expected
    to be called (currently: nothing in this codebase calls it
    automatically; it's a hook for a future RFQ-deletion mechanism, per
    plan §9/§23's disclosed gap)."""
    try:
        requests.post(
            f"{RFQ_MEMORY_INTERNAL_URL}/internal/memory/reset",
            json={"rfq_id": rfq_id},
            timeout=_TIMEOUT_SECONDS,
        )
    except Exception as e:
        print(f"[MEMORY RESET TRIGGER ERROR] rfq_id={rfq_id}: {e}")
