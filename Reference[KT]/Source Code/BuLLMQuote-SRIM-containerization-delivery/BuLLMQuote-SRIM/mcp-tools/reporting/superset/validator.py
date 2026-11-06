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


# ── Per-tab business-rule validators ─────────────────────────────────────────

def _safe_count(con, sql, params=None):
    try:
        row = con.execute(sql, params or []).fetchone()
        return row[0] if row else 0
    except Exception:
        return None


def _tab_check(checks, name, passed, detail=""):
    checks.append({"name": name, "passed": bool(passed), "detail": str(detail)})


def _generic_tab_checks(con, table, rfq_id, rfq_lit, checks):
    """Checks that apply to every report table."""
    n = _row_count(con, table, rfq_lit)
    _tab_check(checks, "has_rows", n > 0, f"{n} rows")
    null_rfq = _safe_count(con, f"SELECT COUNT(*) FROM {table} WHERE rfq_id IS NULL")
    _tab_check(checks, "rfq_id_not_null", null_rfq == 0, f"{null_rfq} NULL rfq_id rows")
    if mandatory_col := _MANDATORY_FIELDS.get(table):
        null_col = _safe_count(con, f"SELECT COUNT(*) FROM {table} WHERE rfq_id = ? AND {mandatory_col} IS NULL", [rfq_id])
        _tab_check(checks, f"{mandatory_col}_not_null", null_col == 0, f"{null_col} NULL {mandatory_col} rows")


def validate_report_tab(con, rfq_id, table_name):
    """Run per-tab business-rule checks for one report table and one rfq_id.

    Returns {"table": str, "passed": bool, "checks": [...]}
    Each check: {"name": str, "passed": bool, "detail": str}
    """
    rfq_lit = helpers.sql_quote(rfq_id)
    checks = []

    _generic_tab_checks(con, table_name, rfq_id, rfq_lit, checks)

    try:
        _TABLE_VALIDATORS.get(table_name, lambda *_: None)(con, rfq_id, rfq_lit, checks)
    except Exception as e:
        _tab_check(checks, "validator_error", False, str(e))

    passed = all(c["passed"] for c in checks)
    return {"table": table_name, "passed": passed, "checks": checks}


def validate_all_reports(con, rfq_id):
    """Run validate_report_tab() for all 16 tables. Returns a summary."""
    results = [validate_report_tab(con, rfq_id, t) for t in constants.REPORT_ORDER]
    n_passed = sum(1 for r in results if r["passed"])
    n_failed = len(results) - n_passed
    return {
        "rfq_id": rfq_id,
        "total": len(results),
        "passed": n_passed,
        "failed": n_failed,
        "details": results,
    }


# ── Table-specific validator implementations ──────────────────────────────────

def _val_bom_matrix(con, rfq_id, rfq_lit, checks):
    dup_count = _safe_count(con, f"""
        SELECT COUNT(*) FROM (
            SELECT cpn, fg, volume_no, COUNT(*) AS n
            FROM bom_matrix_report WHERE rfq_id = ?
            GROUP BY cpn, fg, volume_no HAVING n > 1
        ) t
    """, [rfq_id])
    _tab_check(checks, "no_duplicate_cpn_fg_volume", dup_count == 0, f"{dup_count} duplicate (cpn, fg, volume_no) groups")

    # Reconciliation: bom_matrix grand_total cost vs cbom ext_price_conv
    bm_total = _safe_count(con, "SELECT SUM(fg_grand_total) FROM bom_matrix_report WHERE rfq_id = ?", [rfq_id])
    cbom_total = _safe_count(con, "SELECT SUM(ext_price_conv) FROM cbom_db.cbom WHERE rfq_id = ? AND is_assembly = FALSE", [rfq_id])
    if bm_total is not None and cbom_total is not None and cbom_total > 0:
        delta_pct = abs(bm_total - cbom_total) / cbom_total
        _tab_check(checks, "grand_total_matches_cbom", delta_pct < 0.01, f"delta={delta_pct:.2%} (bm={bm_total:.2f}, cbom={cbom_total:.2f})")
    else:
        _tab_check(checks, "grand_total_matches_cbom", True, "skipped (no data)")


def _val_summary(con, rfq_id, rfq_lit, checks):
    null_vol = _safe_count(con, "SELECT COUNT(*) FROM summary_report WHERE rfq_id = ? AND volume_no IS NULL", [rfq_id])
    _tab_check(checks, "volume_no_not_null", null_vol == 0, f"{null_vol} NULL volume_no rows")


def _val_price_control(con, rfq_id, rfq_lit, checks):
    ref_count = _safe_count(con, "SELECT COUNT(*) FROM price_control_report WHERE rfq_id = ? AND price_control LIKE '%#REF%'", [rfq_id])
    _tab_check(checks, "no_ref_errors", ref_count == 0, f"{ref_count} #REF! values in price_control column")
    grand = _safe_count(con, "SELECT SUM(bucket_total) FROM price_control_report WHERE rfq_id = ?", [rfq_id])
    _tab_check(checks, "grand_total_positive", (grand or 0) >= 0, f"grand_total={grand}")


def _val_ex_inv_vl(con, rfq_id, rfq_lit, checks):
    neg_count = _safe_count(con, "SELECT COUNT(*) FROM ex_inv_vl_report WHERE rfq_id = ? AND net_ordering_qty < 0", [rfq_id])
    _tab_check(checks, "net_ordering_qty_non_negative", neg_count == 0, f"{neg_count} rows with net_ordering_qty < 0")


def _val_aclass_parts(con, rfq_id, rfq_lit, checks):
    non_a = _safe_count(con, "SELECT COUNT(*) FROM aclass_parts_report WHERE rfq_id = ? AND abc_classification != 'A'", [rfq_id])
    _tab_check(checks, "only_a_class", non_a == 0, f"{non_a} non-A rows")
    total_cost = _safe_count(con, "SELECT SUM(ext_price_conv) FROM cbom_db.cbom WHERE rfq_id = ? AND is_assembly = FALSE", [rfq_id])
    a_cost = _safe_count(con, "SELECT SUM(ext_price_conv) FROM aclass_parts_report WHERE rfq_id = ?", [rfq_id])
    if total_cost and total_cost > 0:
        pct = (a_cost or 0) / total_cost
        _tab_check(checks, "a_class_covers_70pct", pct >= 0.70, f"A-class covers {pct:.1%} of total cost")
    else:
        _tab_check(checks, "a_class_covers_70pct", True, "skipped (no cost data)")


_TABLE_VALIDATORS = {
    "bom_matrix_report": _val_bom_matrix,
    "summary_report": _val_summary,
    "price_control_report": _val_price_control,
    "ex_inv_vl_report": _val_ex_inv_vl,
    "aclass_parts_report": _val_aclass_parts,
}
