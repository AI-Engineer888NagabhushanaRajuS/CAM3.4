"""Content-hash -> citation lookup table (plan §0.D: citation metadata must
always trace back to a real source record, never be invented or inferred at
retrieval time).

Why this exists: cognee's SearchType.CHUNKS returns the verbatim text that
was add()'ed, but nothing that maps back to *our own* source record (a real
DuckDB cbom row, a real Postgres file_telemetry row, etc.) -- cognee has no
concept of that. So at ingest time, every (text, citation) pair this
service builds is also recorded here, keyed by a hash of the exact text;
at retrieval time, each returned chunk's text is re-hashed and looked up.
If no match is found, that chunk is dropped from the response rather than
shipped with a fabricated citation -- an uncited claim is safe, a
fabricated one is not.

Lives in cognee_memory_db (the same dedicated Postgres database Cognee's
own relational/graph stores use) as one small, separate table -- not
sharing this platform's logic_db_2/file_metadata_db_2, and not part of any
Cognee-managed schema (this table is entirely this service's own).
"""

import hashlib
import json
import logging

import psycopg2

import config

logger = logging.getLogger("rfq_memory.citation_store")


def _connect():
    cfg = config.COGNEE_RELATIONAL_DB_CONFIG
    return psycopg2.connect(
        host=cfg["db_host"], port=cfg["db_port"], user=cfg["db_username"],
        password=cfg["db_password"], dbname=cfg["db_name"],
    )


def ensure_schema() -> None:
    """Idempotent, additive-only -- matches this codebase's own established
    migration convention (see fastmcp-router/db.py's ensure_version_schema)."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS rfq_memory_citations (
                    content_hash TEXT PRIMARY KEY,
                    rfq_id TEXT NOT NULL,
                    citation_json TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_rfq_memory_citations_rfq_id ON rfq_memory_citations (rfq_id)"
            )
        conn.commit()


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def store_citation(text: str, rfq_id: str, citation: dict) -> None:
    """Upsert -- a re-ingest of identical text just refreshes the citation,
    never accumulates duplicates (content_hash is the primary key)."""
    content_hash = _hash(text)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO rfq_memory_citations (content_hash, rfq_id, citation_json)
                VALUES (%s, %s, %s)
                ON CONFLICT (content_hash) DO UPDATE SET
                    citation_json = EXCLUDED.citation_json,
                    rfq_id = EXCLUDED.rfq_id,
                    created_at = now()
                """,
                (content_hash, rfq_id, json.dumps(citation)),
            )
        conn.commit()


def lookup_citation(text: str) -> dict | None:
    """Returns None (not a fabricated fallback) when no real source record
    is found for this exact text -- the caller must drop the chunk, not
    invent a citation for it."""
    content_hash = _hash(text)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT citation_json FROM rfq_memory_citations WHERE content_hash = %s",
                (content_hash,),
            )
            row = cur.fetchone()
    if row is None:
        return None
    try:
        return json.loads(row[0])
    except Exception:
        logger.warning("[CITATION STORE] corrupt citation_json for hash=%s", content_hash)
        return None
