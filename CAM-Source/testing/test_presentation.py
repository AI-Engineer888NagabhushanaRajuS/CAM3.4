"""Workbook presentation (mcp-tools/reporting/superset/reports/presentation.py): headers centred, numbers right, text left; values and formulas kept."""
import os
import sys

import openpyxl

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mcp-tools", "reporting", "superset")))
from reports.presentation import style_workbook  # noqa: E402


def test_headers_are_centred_numbers_right_text_left_and_nothing_else_changes():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Tab"
    ws.append(["Part", "Qty", "Note"])
    ws["A1"].font = openpyxl.styles.Font(bold=True)
    ws["B1"].font = openpyxl.styles.Font(bold=True)
    ws["C1"].font = openpyxl.styles.Font(bold=True)
    ws.append(["R1", 2.5, "short"])
    ws.append(["R2", "=B2*2", "x" * 70])
    style_workbook(wb)
    assert ws["A1"].alignment.horizontal == "center" and ws["A1"].font.b is True
    assert ws["B2"].alignment.horizontal == "right" and ws["B2"].value == 2.5
    # a formula keeps Excel's own alignment (numbers right, text left): most formulas on the report tabs return TEXT, which right-aligned is cut off on its left
    assert ws["B3"].alignment.horizontal != "right" and ws["B3"].value == "=B2*2"
    assert ws["A2"].alignment.horizontal == "left" and ws["C3"].alignment.wrap_text is True
    assert ws["A2"].alignment.vertical == "center"
