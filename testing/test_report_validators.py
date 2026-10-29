"""
Tests for the per-tab validator layer added in SPEC-002.
Uses the in-memory DuckDB fixture from conftest.py (minimal schema).
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp-tools", "reporting", "superset"))

from conftest import REPORT_TABLES, TEST_RFQ_ID
import pytest


@pytest.fixture(scope="module")
def validator_mod():
    import validator
    return validator


def test_validate_report_tab_returns_correct_shape(con, validator_mod):
    """validate_report_tab() must return a dict with table/passed/checks keys."""
    result = validator_mod.validate_report_tab(con, TEST_RFQ_ID, "bom_matrix_report")
    assert "table" in result
    assert "passed" in result
    assert "checks" in result
    assert isinstance(result["checks"], list)
    for check in result["checks"]:
        assert "name" in check
        assert "passed" in check
        assert "detail" in check


def test_validate_all_reports_covers_all_16_tables(con, validator_mod):
    """validate_all_reports() must return results for all 16 tables."""
    result = validator_mod.validate_all_reports(con, TEST_RFQ_ID)
    assert result["total"] == 16
    returned_tables = [r["table"] for r in result["details"]]
    assert returned_tables == REPORT_TABLES


def test_validate_all_reports_summary_keys(con, validator_mod):
    """validate_all_reports() result must have rfq_id, total, passed, failed, details."""
    result = validator_mod.validate_all_reports(con, TEST_RFQ_ID)
    assert result["rfq_id"] == TEST_RFQ_ID
    assert result["passed"] + result["failed"] == result["total"]


def test_validate_report_tab_missing_rfq_is_row_count_fail(con, validator_mod):
    """validate_report_tab for a non-existent rfq_id reports row_count_gt_0 as failed."""
    result = validator_mod.validate_report_tab(con, "NONEXISTENT-RFQ", "bom_matrix_report")
    row_count_check = next(c for c in result["checks"] if c["name"] == "row_count_gt_0")
    assert row_count_check["passed"] is False


@pytest.mark.parametrize("table", REPORT_TABLES)
def test_validate_report_tab_does_not_crash(con, validator_mod, table):
    """validate_report_tab() must not raise for any of the 16 tables, even with minimal schema."""
    result = validator_mod.validate_report_tab(con, TEST_RFQ_ID, table)
    assert isinstance(result, dict)
    assert result["table"] == table


def test_sum_and_count_is_sum_same_is_boolean():
    """sum_and_count() must return bool not string for Is Sum Same/Is Count Same."""
    from reports.sum_and_count import sum_and_count

    payload = {
        "scrub_bom_items": [{"Assembly": "A", "CPN": "C1", "Quantity": 10}],
        "rfqs": [{"cpn": "C1", "volume_no": 1}],
    }
    rows = sum_and_count(payload)
    assert len(rows) == 1
    assert isinstance(rows[0]["Is Sum Same"], bool), "Is Sum Same must be bool not str"
    assert isinstance(rows[0]["Is Count Same"], bool), "Is Count Same must be bool not str"


def test_sum_and_count_mismatch_is_false():
    """Is Sum Same/Count Same is False when volumes differ."""
    from reports.sum_and_count import sum_and_count

    payload = {
        "scrub_bom_items": [{"Assembly": "A", "CPN": "C1", "Quantity": 5}],
        "rfqs": [],
    }
    rows = sum_and_count(payload)
    # No rfqs means VL sums are 0 while Scrub sum is 5 -> mismatch
    assert rows[0]["Is Sum Same"] is False


def test_validate_reports_mcp_tool_registered():
    """centum_reporting__validate_reports must appear as a registered tool in mcp_server."""
    import mcp_server
    tool_names = [t.name for t in mcp_server.mcp._tool_manager.list_tools()]
    assert "validate_reports" in tool_names, (
        f"validate_reports not found in registered tools: {tool_names}"
    )
