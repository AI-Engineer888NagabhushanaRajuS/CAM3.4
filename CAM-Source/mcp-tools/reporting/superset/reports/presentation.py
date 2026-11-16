"""Presentation of the delivered workbook: one pass over every tab before it is saved.

Headers (bold cells) are centred and wrapped on a light fill; numbers (typed or formulas) are right-aligned, text is left-aligned,
and every cell is vertically centred so a row with a tall comment does not push its numbers to the top. Values and formulas are not
changed: this only sets cell alignment, fonts for headers, and fills for header rows.
"""
from openpyxl.styles import Alignment, Font, PatternFill

HEADER_FILL = PatternFill("solid", fgColor="D9E1F2")


def _is_number_cell(value):
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    return isinstance(value, str) and value.startswith("=")


def style_sheet(ws):
    max_row, max_col = ws.max_row, ws.max_column
    for row in ws.iter_rows(min_row=1, max_row=max_row, max_col=max_col):
        for cell in row:
            if cell.value is None:
                continue
            is_header = bool(cell.font and cell.font.b)
            if is_header:
                cell.font = Font(bold=True, name=cell.font.name, size=cell.font.sz)
                cell.fill = HEADER_FILL
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            elif _is_number_cell(cell.value):
                cell.alignment = Alignment(horizontal="right", vertical="center")
            else:
                wrap = isinstance(cell.value, str) and len(cell.value) > 40
                cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=wrap)


def style_workbook(wb):
    for ws in wb.worksheets:
        style_sheet(ws)
    return wb
