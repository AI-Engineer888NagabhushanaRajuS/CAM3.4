"""
Per-report table existence and schema tests.
One parametrized test per report table — any missing or renamed table fails loud.
"""
import pytest
from conftest import REPORT_TABLES


@pytest.mark.parametrize("table", REPORT_TABLES)
def test_report_table_exists(con, table):
    """Each of the 16 report tables must exist in the DuckDB schema."""
    result = con.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?", [table]
    ).fetchone()
    assert result[0] == 1, f"Report table '{table}' is missing from DuckDB"


@pytest.mark.parametrize("table", REPORT_TABLES)
def test_report_table_has_rfq_id_column(con, table):
    """Every report table must have an rfq_id column for per-RFQ scoping."""
    cols = [row[0] for row in con.execute(f"DESCRIBE {table}").fetchall()]
    assert "rfq_id" in cols, f"Table '{table}' is missing required column: rfq_id"


def test_exactly_16_report_tables_defined():
    """Guard against accidental addition/removal from REPORT_TABLES."""
    assert len(REPORT_TABLES) == 16, (
        f"Expected exactly 16 report tables, got {len(REPORT_TABLES)}. "
        "Update REPORT_TABLES in conftest.py if a new report was added."
    )


def test_report_tables_match_constants():
    """REPORT_TABLES in conftest must match REPORT_ORDER in constants.py."""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp-tools", "reporting", "superset"))
    from constants import REPORT_ORDER
    assert REPORT_TABLES == REPORT_ORDER, (
        "conftest.REPORT_TABLES does not match constants.REPORT_ORDER. "
        "Keep them in sync — constants.py is the single source of truth."
    )
