"""The Run Inputs tab: a required input that is missing is said so, and it blocks the release-ready label (reports/run_inputs.py)."""
import os
import sys

import openpyxl

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mcp-tools", "reporting", "superset")))
from reports import run_inputs as ri  # noqa: E402


def test_both_inputs_provided_is_not_missing():
    rows = ri.run_input_rows(bom_rows=502, quotewin_rows=480)
    assert [r[2] for r in rows] == ["Provided", "Provided"]
    assert not ri.has_missing_required(rows)


def test_a_missing_quotewin_is_a_missing_required_input():
    rows = ri.run_input_rows(bom_rows=502, quotewin_rows=0)
    quote = next(r for r in rows if r[0] == "QuoteWin export")
    assert quote[1] == "Yes" and quote[2] == "MISSING (required)"
    assert ri.has_missing_required(rows)


def test_a_missing_bom_is_missing_and_says_no_parts():
    rows = ri.run_input_rows(bom_rows=0, quotewin_rows=10)
    assert ri.has_missing_required(rows)
    assert "no parts" in rows[0][3].lower()


def test_the_tab_is_written_with_red_fill_for_a_missing_required_input(tmp_path):
    wb = openpyxl.Workbook()
    wb.active.title = "Summary"
    ri.build_run_inputs_sheet(wb, ri.run_input_rows(bom_rows=5, quotewin_rows=0))
    ws = wb["Run Inputs"]
    assert [c.value for c in ws[1]] == ri.HEADERS
    assert ws["C3"].value == "MISSING (required)"
    assert ws["C3"].fill.fgColor.rgb.endswith("F8D7DA")
    assert ws["C2"].fill.fill_type is None
    path = tmp_path / "x.xlsx"
    wb.save(path)
    assert openpyxl.load_workbook(path)["Run Inputs"]["A3"].value == "QuoteWin export"
