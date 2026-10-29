"""Final-selection stage: auto-resolves cbom rows where exactly one source
(_costing/_erp/_qw) has data, and persists genuine multi-source conflicts to
Postgres logic_db.final_selection_conflicts for human review. Never returns
row-level conflict data through the MCP response -- an RFQ can have
thousands of conflicting rows, and the MCP -> FastAPI -> Dify chain cannot
carry that as one payload (large responses, memory pressure, timeout risk,
an unrenderable frontend payload). Business logic (the actual SQL) lives in
queries.py's final_selection_*_sql() functions; this module is the thin
orchestration, mirroring cbom_generator.py/enrichment.py's pattern -- plus
the one piece those don't need: talking to Postgres for the conflict table.

Why Postgres, not DuckDB, for final_selection_conflicts: it is workflow/
human-review state (who's reviewing what, what's been decided), not
analytical CBOM data. Postgres (logic_db, alongside system_skills_registry/
quote_routing_profiles/unified_quote_package) gives proper concurrent-writer
support for multiple reviewers, real transactional guarantees, and keeps
auditing where the rest of the orchestration state already lives. DuckDB
(cbom.duckdb) stays the system of record for CBOM values only -- it
receives writes solely for final, decided values (see apply_resolved_conflict
below), never the in-progress review state itself.
"""

import json
import os
import sys
import uuid

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
# [BuLLMQuote-SRIM MIGRATION NOTE -- fixed 2026-08-11] see currency.py's
# identical note: db.py now lives in fastmcp-router/, a sibling directory
# three levels up from this file, not its immediate parent.
_PROJECT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(_THIS_DIR))), "fastmcp-router"
)
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

from psycopg2.extras import execute_values

import helpers
import queries
from db import get_logic_connection

FINAL_SELECTION_CONFLICTS_DDL = """
CREATE TABLE IF NOT EXISTS final_selection_conflicts (
    conflict_id VARCHAR PRIMARY KEY,
    rfq_id VARCHAR NOT NULL,
    cbom_item_id VARCHAR NOT NULL,
    bom_item_id VARCHAR,
    -- VARCHAR (not SMALLINT) to match cbom_db.cbom.volume_no's PROTO-support type
    -- change (see queries.py/schema.py) -- can hold "proto" alongside numbered
    -- volumes ("1", "2", ...). See ensure_conflicts_table() for the idempotent
    -- migration that upgrades a pre-existing SMALLINT column in place.
    volume_no VARCHAR,
    cpn VARCHAR,
    available_sources JSONB,
    resolved_source VARCHAR,
    resolved_by VARCHAR,
    resolved_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT now()
)
"""

FINAL_SELECTION_CONFLICTS_INDEX_DDL = """
CREATE INDEX IF NOT EXISTS idx_final_selection_conflicts_rfq
ON final_selection_conflicts(rfq_id, resolved_source)
"""

# Fields captured per source for a conflicting row -- everything a reviewer
# needs to compare candidates, and everything apply_resolved_conflict() needs
# to write into cbom.duckdb's final_* once one is chosen.
SOURCE_FIELDS = [
    "price_conv", "price_original", "currency_original", "mfg_name",
    "supp_name", "pkg_qty", "moq", "lead_time", "unit_of_measure",
]


def ensure_conflicts_table(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute(FINAL_SELECTION_CONFLICTS_DDL)
        cur.execute(FINAL_SELECTION_CONFLICTS_INDEX_DDL)
        # Idempotent migration for a pre-existing table created before the PROTO
        # support change -- CREATE TABLE IF NOT EXISTS above won't retype an
        # already-existing column, so upgrade it in place, same idiom as
        # database.py's connect()/_column_type() for the DuckDB side.
        cur.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'final_selection_conflicts' AND column_name = 'volume_no'"
        )
        row = cur.fetchone()
        if row and row[0] == "smallint":
            cur.execute(
                "ALTER TABLE final_selection_conflicts "
                "ALTER COLUMN volume_no TYPE VARCHAR USING volume_no::VARCHAR"
            )


def resolve_final_selection(con, rfq_id):
    """con is an open DuckDB connection (database.connect()). Auto-resolves
    single-source rows directly into cbom.duckdb's final_* (+ recomputes the
    derived columns), and persists multi-source conflicts to Postgres.
    Returns a lightweight summary only -- never the conflict rows themselves.
    """
    rfq_lit = helpers.sql_quote(rfq_id)

    con.execute(queries.final_selection_auto_resolve_sql(rfq_lit))
    for statement in queries.final_selection_recompute_derived_sql(rfq_lit):
        con.execute(statement)

    conflict_rows = con.execute(queries.final_selection_conflict_query_sql(rfq_lit)).fetchall()
    columns = [d[0] for d in con.description]

    conflicts_to_insert = []
    for row in conflict_rows:
        record = dict(zip(columns, row))
        available_sources = {}
        for source in ("costing", "erp", "qw"):
            if (
                record.get(f"price_conv_{source}") is not None
                or record.get(f"mfg_name_{source}") is not None
                or record.get(f"unit_of_measure_{source}") is not None
            ):
                available_sources[source] = {
                    field: record.get(f"{field}_{source}")
                    for field in SOURCE_FIELDS
                }
        conflicts_to_insert.append((
            str(uuid.uuid4()),
            rfq_id,
            str(record["cbom_item_id"]),
            str(record["bom_item_id"]) if record["bom_item_id"] is not None else None,
            record["volume_no"],
            record["cpn"],
            json.dumps(available_sources, default=str),
        ))

    with get_logic_connection() as pg_conn:
        ensure_conflicts_table(pg_conn)
        with pg_conn.cursor() as cur:
            # resolve_final_selection is idempotent/re-runnable (same as
            # cbom/enrich_* before it) -- clear this rfq_id's stale
            # unresolved conflicts from any prior run before inserting the
            # current set. Never touches already-resolved rows, so a
            # completed human review is never discarded by a re-run.
            cur.execute(
                "DELETE FROM final_selection_conflicts WHERE rfq_id = %s AND resolved_source IS NULL",
                (rfq_id,)
            )
            if conflicts_to_insert:
                execute_values(
                    cur,
                    """
                    INSERT INTO final_selection_conflicts
                        (conflict_id, rfq_id, cbom_item_id, bom_item_id, volume_no, cpn, available_sources)
                    VALUES %s
                    """,
                    conflicts_to_insert,
                    template="(%s, %s, %s, %s, %s, %s, %s::jsonb)"
                )
            cur.execute(
                "SELECT COUNT(*) FROM final_selection_conflicts WHERE rfq_id = %s AND resolved_source IS NULL",
                (rfq_id,)
            )
            pending_count = cur.fetchone()[0]
        pg_conn.commit()

    return {
        "status": "success",
        "rfq_id": rfq_id,
        # Always halt here, even with zero pending conflicts (e.g. only one
        # pricing source was uploaded, so there was structurally nothing to
        # reconcile) -- this is the only gate before the Finalize Price / CBOM
        # preview review, and skipping it here would let the pipeline run
        # straight through to Quote Readiness with no review opportunity at
        # all. hitl_router.py's submit_resolutions() accepts an empty
        # resolutions list as a no-op confirm precisely for this case.
        "hitl": 1,
        "pending_conflicts": pending_count,
        "review_required": pending_count > 0,
    }


def apply_resolved_conflict(con, rfq_id, cbom_item_id, source_values):
    """Writes one human-resolved conflict's chosen source values into
    cbom.duckdb's final_* for that specific row. Does NOT recompute the
    derived columns itself -- call recompute_derived_columns() once after a
    whole batch, not per row, since it's a set-based UPDATE across the
    rfq_id. Called by hitl_router.py's POST /final-selection once Postgres
    has already recorded the resolution.
    """
    con.execute(
        """
        UPDATE cbom_db.cbom
        SET
            final_price_conv = ?,
            final_price_original = ?,
            final_currency_original = ?,
            final_mfg_name = ?,
            final_supp_name = ?,
            final_pkg_qty = ?,
            final_moq = ?,
            final_lead_time = ?,
            final_unit_of_measure = ?
        WHERE cbom_item_id = ? AND rfq_id = ?
        """,
        [
            source_values.get("price_conv"),
            source_values.get("price_original"),
            source_values.get("currency_original"),
            source_values.get("mfg_name"),
            source_values.get("supp_name"),
            source_values.get("pkg_qty"),
            source_values.get("moq"),
            source_values.get("lead_time"),
            source_values.get("unit_of_measure"),
            cbom_item_id,
            rfq_id,
        ]
    )


def recompute_derived_columns(con, rfq_id):
    """Re-runs the same is_costed/scrap_percent/abc_classification/etc.
    recompute resolve_final_selection uses -- call once after applying a
    batch of human resolutions (see hitl_router.py), not per row.
    """
    rfq_lit = helpers.sql_quote(rfq_id)
    for statement in queries.final_selection_recompute_derived_sql(rfq_lit):
        con.execute(statement)
