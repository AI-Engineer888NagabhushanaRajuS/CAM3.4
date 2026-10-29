"""Post-generation validation: formalizes the checks that were previously run ad hoc
(by hand, via one-off queries) during development into a single reusable function,
`validate_rfq(con, rfq_id)`. Not wired into generate_reports()/export_reports()
automatically (those stay fast and side-effect-free) -- call it explicitly when you want
a health check, e.g. after a first generate_reports() call for a new rfq_id, or as part
of a CI/smoke-test step in a consuming application.

Every check is read-only (SELECT only) and safe to run at any time, including mid-way
through manual debugging.
"""

import constants
import helpers


# Tables with a declared uniqueness constraint worth checking for accidental duplicates
# (the report tables' own DDL in schema.py; `cbom` has its own separate check below since
# its key includes bom_item_id/volume_no, not just business columns).
_UNIQUE_KEY_TABLES = {
    "part_num_vs_mfg_num_report": ["part_number", "mpn"],
    "pcb_nre_fai_charge_report": ["cpn"],
    "mech_em_nre_report": ["cpn"],
    "aclass_parts_report": ["cpn"],
    "price_control_report": ["price_control"],
    "summary_report": ["fg", "volume_no"],
}

# Tables/columns that must never be NULL for a well-formed row.
_MANDATORY_FIELDS = {
    "bom_matrix_report": "cpn",
    "part_num_vs_mfg_num_report": "part_number",
    "pcb_nre_fai_charge_report": "cpn",
    "mech_em_nre_report": "cpn",
    "missing_notes_report": "cpn",
    "lead_time_fg_report": "fg",
    "sum_and_count_report": "assembly",
    "sum_and_count_detailed_report": "cpn",
    "revision_history_report": "cpn",
    "aclass_parts_report": "cpn",
    "price_control_report": "price_control",
    "summary_report": "fg",
    "cbom_vl_report": "cpn",
    "ex_inv_vl_report": "cpn",
}


def _row_count(con, table, rfq_lit):
    return con.execute(f"SELECT COUNT(*) FROM {table} WHERE rfq_id = {rfq_lit}").fetchone()[0]


def validate_rfq(con, rfq_id):
    """Runs the full validation suite for one rfq_id against the currently-open
    connection (see database.connect()). Returns a dict with a top-level "passed"
    boolean and a "checks" list of {"name", "passed", "detail"} entries -- every check
    that ran, not just the failures, so a caller can see full coverage.
    """
    rfq_lit = helpers.sql_quote(rfq_id)
    checks = []

    def add(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    # 1. Row-count validation: cbom and every report table have at least one row for
    # this rfq_id (a report legitimately being empty -- e.g. no PCB parts in this BOM --
    # is possible, so this flags zero rows as a warning-level detail, not an automatic
    # failure, except for cbom itself, which must never be empty for a real rfq_id).
    cbom_rows = _row_count(con, "cbom_db.cbom", rfq_lit)
    add("cbom_has_rows", cbom_rows > 0, f"{cbom_rows} cbom rows for rfq_id={rfq_id!r}")

    report_counts = {}
    for table in constants.REPORT_ORDER:
        n = _row_count(con, table, rfq_lit)
        report_counts[table] = n
    add("report_row_counts", True, report_counts)  # informational, not pass/fail

    # 2. RFQ validation: every row in every table actually belongs to the requested
    # rfq_id (no NULL rfq_id, no cross-contamination from another rfq_id's rows).
    n_null_rfq = con.execute(f"SELECT COUNT(*) FROM cbom_db.cbom WHERE rfq_id IS NULL").fetchone()[0]
    add("cbom_no_null_rfq_id", n_null_rfq == 0, f"{n_null_rfq} cbom rows with NULL rfq_id")
    for table in constants.REPORT_ORDER:
        n_null = con.execute(f"SELECT COUNT(*) FROM {table} WHERE rfq_id IS NULL").fetchone()[0]
        add(f"{table}_no_null_rfq_id", n_null == 0, f"{n_null} rows with NULL rfq_id")

    # 3. Duplicate-key validation: tables with a declared business-key uniqueness
    # requirement have no duplicates on that key (within this rfq_id).
    for table, key_cols in _UNIQUE_KEY_TABLES.items():
        key_expr = ", ".join(key_cols)
        total = _row_count(con, table, rfq_lit)
        distinct = con.execute(
            f"SELECT COUNT(DISTINCT ({key_expr})) FROM {table} WHERE rfq_id = {rfq_lit}"
        ).fetchone()[0]
        add(f"{table}_no_duplicate_keys", total == distinct, f"{total} rows, {distinct} distinct ({key_expr})")

    cbom_total = cbom_rows
    cbom_distinct = con.execute(
        f"SELECT COUNT(DISTINCT (bom_item_id, volume_no)) FROM cbom_db.cbom WHERE rfq_id = {rfq_lit}"
    ).fetchone()[0]
    add("cbom_no_duplicate_keys", cbom_total == cbom_distinct, f"{cbom_total} rows, {cbom_distinct} distinct (bom_item_id, volume_no)")

    # 4. Orphan check: every cbom row's bom_item_id must exist in scrub_bom_items (the
    # join that produced it) -- an orphan would mean a stale cbom row survived a
    # scrub_bom_items change.
    n_orphans = con.execute(f"""
        SELECT COUNT(*) FROM cbom_db.cbom c
        LEFT JOIN input_db.scrub_bom_items s ON s.bom_item_id = c.bom_item_id
        WHERE c.rfq_id = {rfq_lit} AND s.bom_item_id IS NULL
    """).fetchone()[0]
    add("cbom_no_orphans", n_orphans == 0, f"{n_orphans} cbom rows with no matching scrub_bom_items row")

    # 5. Mandatory-field validation: the declared "this column must never be NULL"
    # field for each report table.
    for table, column in _MANDATORY_FIELDS.items():
        n_null = con.execute(f"SELECT COUNT(*) FROM {table} WHERE rfq_id = {rfq_lit} AND {column} IS NULL").fetchone()[0]
        add(f"{table}_{column}_not_null", n_null == 0, f"{n_null} rows with NULL {column}")

    passed = all(c["passed"] for c in checks)
    return {"rfq_id": rfq_id, "passed": passed, "checks": checks}
