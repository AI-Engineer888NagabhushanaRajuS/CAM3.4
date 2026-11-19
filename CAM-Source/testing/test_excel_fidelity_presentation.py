"""CAM 4 vs CAM 3.3 workbook fidelity, found 2026-11-18 on the same input (acceptance_evidence/excel_fidelity/COMPARISON.md):
the presentation pass (a) replaced every header's navy/white by light-blue/black, (b) right-aligned every FORMULA, although the
formulas on BOM MATRIX / Revision History / A CLASS PARTS return text, so a description or manufacturer that did not fit was cut
off on its left ("acers WA-SBRRO L"), (c) wrapped the "*** Assembly: ..." caption into a tall narrow cell, and (d) left text columns
at Excel's default width so descriptions, manufacturers and MPNs were clipped.
"""
import os
import sys

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mcp-tools", "reporting", "superset")))
from reports.presentation import style_workbook  # noqa: E402

NAVY = PatternFill("solid", fgColor="2F5496")


def _sheet():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "BOM MATRIX"
    ws.append(["", "", "*** Assembly: T0263650096AB || FG: T0263650096AB"])
    ws.append(["Part Number", "Description", "Mfg Name", "Qty"])
    for c in ws[2]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = NAVY
    ws["C1"].font = Font(bold=True)
    ws.append(["T02A0006993", "=INDEX('7.0 CBOM VL-1'!D:D,MATCH(A3,'7.0 CBOM VL-1'!C:C,0))", "=INDEX('7.0 CBOM VL-1'!F:F,1)", 4])
    ws["C1"].alignment = Alignment(wrap_text=False)
    return wb, ws


def test_header_keeps_its_builder_fill_and_font_colour():
    wb, ws = _sheet()
    style_workbook(wb)
    assert ws["A2"].fill.fgColor.rgb.endswith("2F5496")
    assert ws["A2"].font.color.rgb.endswith("FFFFFF") and ws["A2"].font.b is True
    assert ws["A2"].alignment.horizontal == "center" and ws["A2"].alignment.wrap_text is True


def test_formula_text_is_not_forced_right_and_typed_numbers_still_are():
    wb, ws = _sheet()
    style_workbook(wb)
    assert ws["B3"].alignment.horizontal != "right"
    assert ws["C3"].alignment.horizontal != "right"
    assert ws["D3"].alignment.horizontal == "right"


def test_assembly_caption_is_not_wrapped():
    wb, ws = _sheet()
    style_workbook(wb)
    assert not ws["C1"].alignment.wrap_text


def test_text_columns_are_wide_enough_even_when_their_cells_are_formulas():
    wb, ws = _sheet()
    style_workbook(wb)
    assert ws.column_dimensions["B"].width >= 40      # Description: formula column, found by its header
    assert ws.column_dimensions["C"].width >= 24      # Mfg Name
    assert ws.column_dimensions["A"].width >= 13      # Part Number, never shrunk


def test_widths_never_shrink():
    wb, ws = _sheet()
    ws.column_dimensions["D"].width = 30
    style_workbook(wb)
    assert ws.column_dimensions["D"].width == 30
