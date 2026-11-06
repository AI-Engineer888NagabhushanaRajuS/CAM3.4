"""ERP/costing-sheet enrichment stages: fill the _erp/_costing columns on cbom rows that
already exist for one rfq_id. Business logic lives in queries.py (erp_enrichment_sql()/
costing_enrichment_sql()); this module is the thin orchestration around it, mirroring
cbom_generator.py's role. Each function must run after the cbom stage (cbom_generator.py)
has already inserted rows for this rfq_id -- raises ValueError if none exist yet.
"""

import helpers
import queries


def _require_cbom_rows(con, rfq_id, stage_name):
    rfq_lit = helpers.sql_quote(rfq_id)
    n = con.execute(f"SELECT COUNT(*) FROM cbom_db.cbom WHERE rfq_id = {rfq_lit}").fetchone()[0]
    if n == 0:
        raise ValueError(
            f"No cbom rows found for rfq_id={rfq_id!r} -- call the cbom tool first, before {stage_name}"
        )
    return rfq_lit


def enrich_erp(con, rfq_id):
    """Fills _erp columns on existing cbom rows for one rfq_id. Caller is responsible for
    wrapping this in a transaction (see reporting_pipeline.run_erp_enrichment).
    """
    rfq_lit = _require_cbom_rows(con, rfq_id, "enrich_erp")

    for statement in queries.erp_enrichment_sql(rfq_lit):
        con.execute(statement)

    row_count = con.execute(f"SELECT COUNT(*) FROM cbom_db.cbom WHERE rfq_id = {rfq_lit}").fetchone()[0]
    rows_matched = con.execute(
        f"SELECT COUNT(*) FROM cbom_db.cbom WHERE rfq_id = {rfq_lit} AND price_original_erp IS NOT NULL"
    ).fetchone()[0]
    return {"row_count": row_count, "rows_matched_erp": rows_matched}


def enrich_costing_sheet(con, rfq_id):
    """Fills _costing columns on existing cbom rows for one rfq_id. Caller is responsible
    for wrapping this in a transaction (see reporting_pipeline.run_costing_enrichment).
    """
    rfq_lit = _require_cbom_rows(con, rfq_id, "enrich_costing_sheet")

    for statement in queries.costing_enrichment_sql(rfq_lit):
        con.execute(statement)

    row_count = con.execute(f"SELECT COUNT(*) FROM cbom_db.cbom WHERE rfq_id = {rfq_lit}").fetchone()[0]
    rows_matched = con.execute(
        f"SELECT COUNT(*) FROM cbom_db.cbom WHERE rfq_id = {rfq_lit} AND price_original_costing IS NOT NULL"
    ).fetchone()[0]
    return {"row_count": row_count, "rows_matched_costing": rows_matched}
