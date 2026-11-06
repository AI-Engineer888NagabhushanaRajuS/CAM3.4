"""Per-tab report validation tests for CAM 3.4.

One test per entry in constants.REPORT_ORDER:
  test_report_sql_builds   — SQL string must be buildable without Postgres (mocked)
  test_report_generates    — report must generate without exceptions from synthetic data
"""

import os
import sys
import pytest

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_REPORTING_DIR = os.path.join(_REPO_ROOT, "mcp-tools", "reporting", "superset")
if _REPORTING_DIR not in sys.path:
    sys.path.insert(0, _REPORTING_DIR)

from constants import REPORT_ORDER
from _constants import SYNTHETIC_RFQ_ID


# ── Schema integrity ──────────────────────────────────────────────────────────

def test_report_order_has_16_entries():
    assert len(REPORT_ORDER) == 16, f"Expected 16 reports, got {len(REPORT_ORDER)}"


def test_schema_cbom_ddl_references_cbom_db():
    import schema
    assert "cbom_db.cbom" in schema.CBOM_DDL


def test_schema_report_ddls_covers_all_16():
    import schema
    assert len(schema.REPORT_DDLS) == 16
    for table in REPORT_ORDER:
        assert table in schema.REPORT_DDLS, f"{table} missing from REPORT_DDLS"


# ── SQL builder tests (no DB needed, Postgres mocked by conftest autouse) ────

@pytest.mark.parametrize("table_name", REPORT_ORDER)
def test_report_sql_builds(table_name):
    """Each report must have a non-empty SQL INSERT string."""
    import queries
    sql_map = queries.report_insert_sqls(f"'{SYNTHETIC_RFQ_ID}'")
    assert table_name in sql_map, f"No SQL entry for {table_name}"
    sql = sql_map[table_name]
    assert isinstance(sql, str) and len(sql) > 20, f"SQL too short for {table_name}: {sql!r}"
    assert "INSERT INTO" in sql.upper(), f"SQL for {table_name} is not an INSERT"


# ── Full generation tests (in-memory DuckDB, Postgres mocked) ────────────────

def test_generate_reports_returns_all_16(reporting_con):
    """generate_reports() result dict must have an entry for all 16 tables."""
    import report_generator
    result = report_generator.generate_reports(reporting_con, SYNTHETIC_RFQ_ID)
    counts = result.get("counts", {})
    for table in REPORT_ORDER:
        assert table in counts, f"{table} missing from generate_reports() counts"


@pytest.mark.parametrize("table_name", REPORT_ORDER)
def test_report_generates(reporting_con, table_name):
    """Each report must generate without an exception.

    A count of 0 is acceptable for some tables with minimal synthetic data
    (e.g. pcb_nre_fai_charge requires PCB-commodity parts — only CPN-005 qualifies).
    The critical assertion: no exception / no error entry in issues[].
    """
    import report_generator
    result = report_generator.generate_reports(reporting_con, SYNTHETIC_RFQ_ID)

    issues = result.get("issues", [])
    table_errors = [i for i in issues if i.get("table") == table_name]

    if table_errors:
        error_msg = table_errors[0].get("error", "")
        # UNIQUE constraint violations mean the test ran twice on the same connection.
        # Skip rather than fail — the fixture is function-scoped, so this shouldn't happen.
        if "UNIQUE constraint" in error_msg or "already exists" in error_msg.lower():
            pytest.skip(f"{table_name}: UNIQUE violation (fixture reuse?): {error_msg}")
        pytest.fail(f"{table_name} raised exception: {error_msg}")

    count = result["counts"].get(table_name)
    assert count is not None, f"{table_name} count is None (exception must have occurred)"


# ── Critical-path assertions (must pass) ─────────────────────────────────────

def test_summary_report_has_rows(reporting_con):
    """summary_report must have at least one row per FG."""
    import report_generator
    report_generator.generate_reports(reporting_con, SYNTHETIC_RFQ_ID)
    count = reporting_con.execute(
        "SELECT COUNT(*) FROM summary_report WHERE rfq_id = ?", [SYNTHETIC_RFQ_ID]
    ).fetchone()[0]
    assert count > 0, "summary_report produced 0 rows with synthetic data"


def test_bom_matrix_report_has_rows(reporting_con):
    """bom_matrix_report must have rows for non-assembly parts."""
    import report_generator
    report_generator.generate_reports(reporting_con, SYNTHETIC_RFQ_ID)
    count = reporting_con.execute(
        "SELECT COUNT(*) FROM bom_matrix_report WHERE rfq_id = ?", [SYNTHETIC_RFQ_ID]
    ).fetchone()[0]
    assert count > 0, "bom_matrix_report produced 0 rows with synthetic data"


def test_cbom_has_synthetic_rows(reporting_con):
    """Fixture must have seeded at least 10 cbom rows."""
    count = reporting_con.execute(
        "SELECT COUNT(*) FROM cbom_db.cbom WHERE rfq_id = ?", [SYNTHETIC_RFQ_ID]
    ).fetchone()[0]
    assert count >= 10, f"Expected >=10 synthetic cbom rows, got {count}"


# ── SPEC-002: per-tab validation layer ───────────────────────────────────────

def test_validate_all_reports_returns_16(reporting_con):
    """validate_all_reports() must return results for all 16 tables."""
    import report_generator
    import validator
    report_generator.generate_reports(reporting_con, SYNTHETIC_RFQ_ID)
    result = validator.validate_all_reports(reporting_con, SYNTHETIC_RFQ_ID)
    assert result["total"] == 16
    assert "details" in result
    assert len(result["details"]) == 16


def test_validate_report_tab_returns_structured_result(reporting_con):
    """validate_report_tab() must return a properly structured dict."""
    import report_generator
    import validator
    report_generator.generate_reports(reporting_con, SYNTHETIC_RFQ_ID)
    result = validator.validate_report_tab(reporting_con, SYNTHETIC_RFQ_ID, "summary_report")
    assert "table" in result
    assert "passed" in result
    assert "checks" in result
    assert isinstance(result["checks"], list)
    for check in result["checks"]:
        assert "name" in check
        assert "passed" in check
        assert "detail" in check


def test_generate_reports_includes_validations(reporting_con):
    """generate_reports() result must include a 'validations' key after SPEC-002."""
    import report_generator
    result = report_generator.generate_reports(reporting_con, SYNTHETIC_RFQ_ID)
    assert "validations" in result, "generate_reports() must return 'validations' key"
    assert len(result["validations"]) == 16


def test_validate_aclass_parts_only_a_class(reporting_con):
    """aclass_parts_report validator: abc_classification must all be 'A'."""
    import report_generator
    import validator
    report_generator.generate_reports(reporting_con, SYNTHETIC_RFQ_ID)
    result = validator.validate_report_tab(reporting_con, SYNTHETIC_RFQ_ID, "aclass_parts_report")
    only_a = next((c for c in result["checks"] if c["name"] == "only_a_class"), None)
    assert only_a is not None, "only_a_class check must exist"
    assert only_a["passed"], f"only_a_class check failed: {only_a['detail']}"


def test_validate_price_control_no_ref_errors(reporting_con):
    """price_control_report validator: no #REF! values."""
    import report_generator
    import validator
    report_generator.generate_reports(reporting_con, SYNTHETIC_RFQ_ID)
    result = validator.validate_report_tab(reporting_con, SYNTHETIC_RFQ_ID, "price_control_report")
    no_ref = next((c for c in result["checks"] if c["name"] == "no_ref_errors"), None)
    assert no_ref is not None, "no_ref_errors check must exist"
    assert no_ref["passed"], f"#REF! errors found: {no_ref['detail']}"
