"""Generic worksheet-styling helpers used by exporter.py's raw "CBOM" tab. The 16 report
tabs (reports/*.py) do their own styling internally (already verified against the
reference production workbook) and are not routed through this file -- see the "Design
boundary" note in templates/excel_styles.py.
"""

from openpyxl.utils import get_column_letter

from templates.excel_styles import DATA_FILL, HEADER_FILL, HEADER_FONT


def autosize_and_freeze(ws, df):
    """Bold white-on-navy header row, frozen below it, columns auto-sized from content
    (openpyxl has no native auto-size -- this approximates it from string length)."""
    ws.freeze_panes = "A2"
    for cell in ws[1]:
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
    for i, col in enumerate(df.columns, start=1):
        max_len = max([len(str(col))] + [len(str(v)) for v in df[col].astype(str).head(200)])
        ws.column_dimensions[get_column_letter(i)].width = min(max(max_len + 2, 10), 60)


def fill_data_rows(ws, fill=DATA_FILL, start_row=2):
    for row in ws.iter_rows(min_row=start_row, max_row=ws.max_row):
        for cell in row:
            cell.fill = fill
