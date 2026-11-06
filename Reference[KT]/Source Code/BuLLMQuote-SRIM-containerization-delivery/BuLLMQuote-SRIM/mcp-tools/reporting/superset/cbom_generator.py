"""CBOM generation stage: clears and regenerates the `cbom` table for one rfq_id.

Business logic lives in queries.py (the tie-break view, the CBOM INSERT SQL); this module
is the thin orchestration around it -- volume detection, view creation, insert, and the
row-count/priced-row-count summary returned to the caller.
"""

import helpers
import queries


def clear_cbom_rfq(con, rfq_id):
    con.execute(f"DELETE FROM cbom_db.cbom WHERE rfq_id = {helpers.sql_quote(rfq_id)}")


def generate_cbom(con, rfq_id):
    """Regenerates cbom rows for one rfq_id. Caller is responsible for wrapping this in
    a transaction (see reporting_pipeline.run_pipeline) and for calling clear_cbom_rfq()
    first if regenerating (this function only inserts).
    """
    rfq_lit = helpers.sql_quote(rfq_id)
    n_scrub = con.execute(f"SELECT COUNT(*) FROM input_db.scrub_bom_items WHERE rfq_id = {rfq_lit}").fetchone()[0]
    if n_scrub == 0:
        raise ValueError(f"No scrub_bom_items rows found for rfq_id={rfq_id!r}")

    volumes = queries.detect_volumes(con, rfq_lit)
    con.execute(queries.selected_quote_sql(rfq_lit, volumes, con=con))
    con.execute(queries.cbom_insert_sql(rfq_lit, volumes))

    row_count = con.execute(f"SELECT COUNT(*) FROM cbom_db.cbom WHERE rfq_id = {rfq_lit}").fetchone()[0]
    priced = con.execute(f"SELECT COUNT(*) FROM cbom_db.cbom WHERE rfq_id = {rfq_lit} AND final_price_conv IS NOT NULL").fetchone()[0]
    return {"row_count": row_count, "priced_row_count": priced, "detected_volumes": volumes}
