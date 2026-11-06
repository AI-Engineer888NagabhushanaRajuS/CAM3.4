"""Report generation stage: clears and regenerates all 16 report tables for one rfq_id,
reading from the already-generated `cbom` table (and, for a few reports, the raw input
tables directly). Business logic lives in queries.py; this module is the thin
orchestration loop around it.
"""

import constants
import helpers
import queries
import validator


def clear_reports_rfq(con, rfq_id):
    rfq_lit = helpers.sql_quote(rfq_id)
    for table in constants.REPORT_ORDER:
        con.execute(f"DELETE FROM {table} WHERE rfq_id = {rfq_lit}")


def generate_reports(con, rfq_id):
    """Regenerates all 16 report tables for one rfq_id. Caller is responsible for
    wrapping this in a transaction (see reporting_pipeline.run_pipeline) and for calling
    clear_reports_rfq() first if regenerating.

    Returns {"counts": {table: row_count_or_None}, "issues": [{"table", "error"}, ...]} --
    a report failing does not stop the others from being attempted, so a caller can see
    the full picture of what succeeded and what didn't in one pass.
    """
    rfq_lit = helpers.sql_quote(rfq_id)
    volumes = queries.detect_volumes(con, rfq_lit)
    con.execute(queries.selected_quote_sql(rfq_lit, volumes, con=con))
    con.execute(queries.ex_inv_calc_sql(rfq_lit))

    counts = {}
    issues = []
    validations = {}
    insert_sqls = queries.report_insert_sqls(rfq_lit)
    for table in constants.REPORT_ORDER:
        try:
            con.execute(insert_sqls[table])
            counts[table] = con.execute(f"SELECT COUNT(*) FROM {table} WHERE rfq_id = {rfq_lit}").fetchone()[0]
        except Exception as e:
            issues.append({"table": table, "error": str(e)})
            counts[table] = None
            continue
        v = validator.validate_report_tab(con, rfq_id, table)
        validations[table] = v
        # Validation failures are advisory (not fatal) — run_pipeline's ROLLBACK guard
        # only fires on SQL errors in `issues`. Callers inspect `validations` separately.
    return {"counts": counts, "issues": issues, "validations": validations}
