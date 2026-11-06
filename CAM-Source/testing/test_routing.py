"""
Tests for tool routing sets in fastapi_router.py.
Validates that DUCKDB_SCOPED_TOOLS and SCRUB_TOOLS are correct.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "fastapi-router"))


def test_duckdb_scoped_tools_has_all_reporting_tools():
    """All 6 centum_reporting__ tools must be in DUCKDB_SCOPED_TOOLS."""
    from fastapi_router import DUCKDB_SCOPED_TOOLS

    expected = {
        "centum_reporting__cbom",
        "centum_reporting__enrich_erp",
        "centum_reporting__enrich_costing_sheet",
        "centum_reporting__resolve_final_selection",
        "centum_reporting__generate_reports",
        "centum_reporting__export_reports",
    }
    missing = expected - DUCKDB_SCOPED_TOOLS
    assert not missing, f"Missing from DUCKDB_SCOPED_TOOLS: {missing}"


def test_scrub_tools_has_all_intake_tools():
    """All 4 centum_intake__ standardize tools must be in SCRUB_TOOLS."""
    from fastapi_router import SCRUB_TOOLS

    expected = {
        "centum_intake__standardize_scrub_bom",
        "centum_intake__standardize_quote_win",
        "centum_intake__standardize_erp",
        "centum_intake__standardize_costing_sheet",
    }
    missing = expected - SCRUB_TOOLS
    assert not missing, f"Missing from SCRUB_TOOLS: {missing}"


def test_duckdb_and_scrub_tool_sets_are_disjoint():
    """No tool should appear in both DUCKDB_SCOPED_TOOLS and SCRUB_TOOLS."""
    from fastapi_router import DUCKDB_SCOPED_TOOLS, SCRUB_TOOLS

    overlap = DUCKDB_SCOPED_TOOLS & SCRUB_TOOLS
    assert not overlap, f"Tools in both sets (ambiguous routing): {overlap}"
