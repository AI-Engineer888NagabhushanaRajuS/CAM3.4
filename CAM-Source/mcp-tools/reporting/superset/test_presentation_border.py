"""A cell with no left border side must not stop the Excel export (it raised AttributeError on border.left.style)."""
import sys
from pathlib import Path

import openpyxl
from openpyxl.styles import Border

sys.path.insert(0, str(Path(__file__).parent))
from reports.presentation import style_sheet


def test_cell_without_left_border_side_is_styled():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "Description"
    ws["A2"] = 12.5
    ws["A2"].border = Border(left=None, right=None, top=None, bottom=None)
    style_sheet(ws)  # raised AttributeError before the fix
    assert ws["A2"].border.left is not None and ws["A2"].border.left.style == "thin"


if __name__ == "__main__":
    test_cell_without_left_border_side_is_styled()
    print("ok")
