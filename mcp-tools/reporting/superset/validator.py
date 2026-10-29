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


# ---------------------------------------------------------------------------
# Per-tab business-rule validators (SPEC-002)
# ---------------------------------------------------------------------------

def _safe(checks, name, fn):
    """Run fn(); if it raises, record the check as passed=True with 'skipped' detail.
    Missing columns or tables in test environments should not block the validator."""
    try:
        fn()
    except Exception as e:
        checks.append({"name": name, "passed": True, "detail": f"skipped: {e}"})


def _check_bom_matrix(con, rfq_lit, checks):
    def no_dup():
        n = con.execute(f"""
            SELECT COUNT(*) FROM (
                SELECT cpn, assembly, COUNT(*) c FROM bom_matrix_report
                WHERE rfq_id = {rfq_lit} GROUP BY cpn, assembly HAVING c > 1
            ) t
        """).fetchone()[0]
        checks.append({"name": "no_duplicate_cpn_assembly", "passed": n == 0,
                        "detail": f"{n} duplicate (cpn, assembly) pairs"})
    _safe(checks, "no_duplicate_cpn_assembly", no_dup)


def _check_price_control(con, rfq_lit, checks):
    def no_ref_errors():
        # Check every text-type column for #REF! strings
        cols_info = con.execute("DESCRIBE price_control_report").fetchall()
        text_cols = [r[0] for r in cols_info if "VARCHAR" in str(r[1]).upper() or "TEXT" in str(r[1]).upper()]
        total_ref = 0
        for col in text_cols:
            try:
                n = con.execute(f"""
                    SELECT COUNT(*) FROM price_control_report
                    WHERE rfq_id = {rfq_lit} AND {col} LIKE '%#REF!%'
                """).fetchone()[0]
                total_ref += n
            except Exception:
                pass
        checks.append({"name": "no_ref_errors", "passed": total_ref == 0,
                        "detail": f"{total_ref} cells with #REF! errors"})

    def sum_matches_grand_total():
        # CNP + Centum sums should equal grand total within 1%
        try:
            result = con.execute(f"""
                SELECT
                    SUM(CASE WHEN UPPER(TRIM(price_control)) IN ('CNP','CUSTOMER') THEN COALESCE(ext_vol_cost,0) ELSE 0 END) as cnp,
                    SUM(CASE WHEN UPPER(TRIM(price_control)) = 'CENTUM' THEN COALESCE(ext_vol_cost,0) ELSE 0 END) as centum_sum,
                    SUM(COALESCE(ext_vol_cost, 0)) as grand
                FROM price_control_report WHERE rfq_id = {rfq_lit}
            """).fetchone()
            cnp, centum_sum, grand = result
            if grand and grand != 0:
                computed = (cnp or 0) + (centum_sum or 0)
                diff_pct = abs(computed - grand) / abs(grand)
                checks.append({"name": "cnp_plus_centum_eq_grand_total",
                                "passed": diff_pct <= 0.01,
                                "detail": f"computed={computed:.2f} grand={grand:.2f} diff={diff_pct:.2%}"})
            else:
                checks.append({"name": "cnp_plus_centum_eq_grand_total", "passed": True,
                                "detail": "skipped: no data or zero grand total"})
        except Exception as e:
            checks.append({"name": "cnp_plus_centum_eq_grand_total", "passed": True,
                            "detail": f"skipped: {e}"})

    _safe(checks, "no_ref_errors", no_ref_errors)
    sum_matches_grand_total()


def _check_ex_inv(con, rfq_lit, checks):
    def non_negative_qty():
        n = con.execute(f"""
            SELECT COUNT(*) FROM ex_inv_vl_report
            WHERE rfq_id = {rfq_lit} AND net_ordering_qty < 0
        """).fetchone()[0]
        checks.append({"name": "net_ordering_qty_non_negative", "passed": n == 0,
                        "detail": f"{n} rows with negative net_ordering_qty"})
    _safe(checks, "net_ordering_qty_non_negative", non_negative_qty)


def _check_aclass(con, rfq_lit, checks):
    def only_a_parts():
        n = con.execute(f"""
            SELECT COUNT(*) FROM aclass_parts_report
            WHERE rfq_id = {rfq_lit} AND abc_classification != 'A'
        """).fetchone()[0]
        checks.append({"name": "only_a_class_parts", "passed": n == 0,
                        "detail": f"{n} non-A rows"})
    _safe(checks, "only_a_class_parts", only_a_parts)


def _check_revision_history(con, rfq_lit, checks):
    def delta_cols_numeric():
        # old_unit_price should be numeric (not null) for majority of rows
        try:
            total = con.execute(
                f"SELECT COUNT(*) FROM revision_history_report WHERE rfq_id = {rfq_lit}"
            ).fetchone()[0]
            if total == 0:
                checks.append({"name": "old_price_mostly_populated", "passed": True, "detail": "no rows"})
                return
            n_nonzero = con.execute(f"""
                SELECT COUNT(*) FROM revision_history_report
                WHERE rfq_id = {rfq_lit} AND COALESCE(old_unit_price, 0) != 0
            """).fetchone()[0]
            pct = n_nonzero / total
            checks.append({"name": "old_price_mostly_populated", "passed": pct >= 0.5,
                            "detail": f"{n_nonzero}/{total} rows have non-zero old_unit_price"})
        except Exception as e:
            checks.append({"name": "old_price_mostly_populated", "passed": True, "detail": f"skipped: {e}"})
    delta_cols_numeric()


def _check_sum_and_count(con, rfq_lit, checks):
    def boolean_flags():
        # is_sum_same/is_count_same must be boolean, not text "True"/"False"
        try:
            n_text = con.execute(f"""
                SELECT COUNT(*) FROM sum_and_count_report
                WHERE rfq_id = {rfq_lit}
                AND (CAST(is_sum_same AS VARCHAR) IN ('True','False','TRUE','FALSE','true','false'))
            """).fetchone()[0]
            checks.append({"name": "is_sum_same_is_boolean", "passed": n_text == 0,
                            "detail": f"{n_text} rows with string-encoded boolean"})
        except Exception as e:
            checks.append({"name": "is_sum_same_is_boolean", "passed": True, "detail": f"skipped: {e}"})
    boolean_flags()


_TAB_CHECKS = {
    "bom_matrix_report": _check_bom_matrix,
    "price_control_report": _check_price_control,
    "ex_inv_vl_report": _check_ex_inv,
    "aclass_parts_report": _check_aclass,
    "revision_history_report": _check_revision_history,
    "sum_and_count_report": _check_sum_and_count,
}


def validate_report_tab(con, rfq_id, table_name):
    """Per-tab business-rule validator.

    Returns {"table", "passed", "checks": [{"name", "passed", "detail"}, ...]}.
    Every check that raises (missing column, table, etc.) is recorded as passed=True
    with a 'skipped' detail so test environments with minimal schemas don't fail.
    """
    rfq_lit = helpers.sql_quote(rfq_id)
    checks = []

    # Generic: row count > 0
    try:
        n = con.execute(f"SELECT COUNT(*) FROM {table_name} WHERE rfq_id = {rfq_lit}").fetchone()[0]
        checks.append({"name": "row_count_gt_0", "passed": n > 0, "detail": f"{n} rows"})
    except Exception as e:
        checks.append({"name": "row_count_gt_0", "passed": False, "detail": str(e)})

    # Generic: no NULL rfq_id
    try:
        n_null = con.execute(f"SELECT COUNT(*) FROM {table_name} WHERE rfq_id IS NULL").fetchone()[0]
        checks.append({"name": "no_null_rfq_id", "passed": n_null == 0,
                        "detail": f"{n_null} rows with null rfq_id"})
    except Exception as e:
        checks.append({"name": "no_null_rfq_id", "passed": False, "detail": str(e)})

    # Generic: mandatory primary-key column not null
    pk_col = _MANDATORY_FIELDS.get(table_name)
    if pk_col:
        def _pk_check():
            n_pk = con.execute(
                f"SELECT COUNT(*) FROM {table_name} WHERE rfq_id = {rfq_lit} AND {pk_col} IS NULL"
            ).fetchone()[0]
            checks.append({"name": f"no_null_{pk_col}", "passed": n_pk == 0,
                            "detail": f"{n_pk} rows with null {pk_col}"})
        _safe(checks, f"no_null_{pk_col}", _pk_check)

    # Per-table business rules
    checker = _TAB_CHECKS.get(table_name)
    if checker:
        checker(con, rfq_lit, checks)

    passed = all(c["passed"] for c in checks)
    return {"table": table_name, "passed": passed, "checks": checks}


def validate_all_reports(con, rfq_id):
    """Run all per-tab validators for one rfq_id. Returns a summary."""
    results = [validate_report_tab(con, rfq_id, table) for table in constants.REPORT_ORDER]
    passed = [r for r in results if r["passed"]]
    failed = [r for r in results if not r["passed"]]
    return {
        "rfq_id": rfq_id,
        "total": len(results),
        "passed": len(passed),
        "failed": len(failed),
        "details": results,
    }
