"""Cognee retrieval wrapper backing POST /rfq/{rfq_id}/chat/retrieve and
POST /rfq/{rfq_id}/chat/remember (plan §10). Returns context only --
answer synthesis is daemon-orchestrated (plan §10's "Call 2" note), so this
module never calls an LLM to produce a final answer, only to retrieve/
recall.
"""

import logging

# config MUST be imported before cognee -- see ingest.py's identical comment.
import config
import cognee
from cognee.modules.engine.models.node_set import NodeSet
from cognee.modules.search.types import SearchType

import citation_store

logger = logging.getLogger("rfq_memory.query")


async def retrieve_rfq_context(
    rfq_id: str,
    question: str,
    session_id: str | None = None,
    top_k: int = 10,
    node_set_filter: list[str] | None = None,
) -> dict:
    """rfq_id MUST already be verified by the caller (JWT-extracted) before
    this is called -- this function performs no auth itself (plan §0.B/§10:
    that happens in memory_service.py's route handler via config.verify_token
    against the path param).

    Isolation (plan revision, 2026-09-10 -- see config.node_set_tag_for's
    own docstring): dataset_name is still passed as a secondary scoping
    boundary, but the ACTUAL enforced isolation is
    `node_type=NodeSet, node_name=[rfq_tag]` -- a single-element list,
    never combined with node_set_filter's content-type tags in the same
    list (node_name_filter_operator defaults to "OR", which would widen
    the match to include other RFQs' content tagged with that same
    content-type value, not narrow it). node_set_filter, when provided, is
    applied as a pure Python post-filter on the already-RFQ-scoped chunks
    below, never merged into the node_name search parameter.

    Uses SearchType.CHUNKS (not the default GRAPH_COMPLETION) because it
    returns the verbatim ingested text per chunk (needed for the citation
    lookup below) plus each chunk's own `belongs_to_set` tags (a free
    defense-in-depth re-check that the search-time filter actually held).
    """
    dataset_name = config.dataset_name_for(rfq_id)
    rfq_tag = config.node_set_tag_for(rfq_id)

    try:
        results = await cognee.search(
            query_text=question,
            query_type=SearchType.CHUNKS,
            datasets=[dataset_name],
            node_type=NodeSet,
            node_name=[rfq_tag],
            top_k=top_k,
            session_id=session_id,
        )
    except Exception:
        logger.exception("[MEMORY QUERY ERROR] rfq_id=%s", rfq_id)
        return {"matched": False, "chunks": [], "session_recall": None, "warning": "retrieval_failed"}

    chunks = []
    for r in results or []:
        text = r.get("text") if isinstance(r, dict) else getattr(r, "text", None)
        if not text:
            continue

        # Defense-in-depth: re-verify this chunk's own tags actually
        # include this RFQ's tag, independent of trusting the search
        # filter alone -- belongs_to_set is real per-node metadata, not
        # something this service invents.
        belongs_to_set = (r.get("belongs_to_set") if isinstance(r, dict) else getattr(r, "belongs_to_set", None)) or []
        if rfq_tag not in belongs_to_set:
            logger.warning(
                "[MEMORY QUERY] dropped a chunk whose belongs_to_set %s did not include expected tag %s (rfq_id=%s)",
                belongs_to_set, rfq_tag, rfq_id,
            )
            continue

        # Citation integrity (plan §0.D): looked up from the real record
        # stored at ingest time, keyed by this exact text -- never
        # reconstructed from Cognee's own metadata or guessed. A chunk with
        # no resolvable citation is dropped, not shipped uncited-but-shown.
        citation = citation_store.lookup_citation(text)
        if not citation:
            continue

        if node_set_filter:
            # Pure Python post-filter, never merged into the search-time
            # node_name parameter (see this function's own docstring).
            content_type_tags = [t for t in belongs_to_set if t != rfq_tag]
            if not any(t in node_set_filter for t in content_type_tags):
                continue

        chunks.append({"text": text, "citation": citation, "score": None})

    session_recall = None
    if session_id:
        try:
            recall_results = await cognee.recall(question, session_id=session_id)
            if recall_results:
                session_recall = "\n".join(str(x) for x in recall_results)
        except Exception:
            logger.warning("[MEMORY QUERY] session recall failed for session_id=%s (non-fatal)", session_id)

    warning = None
    if not chunks:
        warning = "no_relevant_context_found"

    return {
        "matched": bool(chunks),
        "chunks": chunks,
        "session_recall": session_recall,
        "warning": warning,
    }


async def remember_turn(rfq_id: str, session_id: str, question: str, answer: str) -> None:
    """Fire-and-forget commit of one Q&A turn to Cognee's session memory --
    scoped by session_id (daemon-constructed as "{rfq_id}:{task_id}", plan
    §5), never a bare rfq_id, so two separate conversations about the same
    RFQ never bleed context into each other."""
    try:
        await cognee.remember(f"Q: {question}\nA: {answer}", session_id=session_id)
    except Exception:
        logger.warning("[MEMORY REMEMBER] failed for rfq_id=%s session_id=%s (non-fatal)", rfq_id, session_id)
