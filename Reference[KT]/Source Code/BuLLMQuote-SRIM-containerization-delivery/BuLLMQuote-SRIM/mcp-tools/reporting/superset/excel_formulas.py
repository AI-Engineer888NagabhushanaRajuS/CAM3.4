"""Number-format application for the raw "CBOM" tab (money columns at 4 decimal places,
percentage columns as Excel `%`). The live Excel FORMULA strings for the 16 report tabs
(e.g. CBOM VL's Is Price Same / Is MPN Same / Recurring Count / Batch Qty / Ext Vol Qty
overlays) are NOT here -- they live inside reports/cbom_vl.py itself, alongside the sheet
structure they reference (column positions, Assembly Summary row ranges) that only that
module's own row-building logic knows. Splitting them out into a generic
"formula-string factory" would mean passing that same sheet-structure context right back
in through this file's API, without saving any real duplication -- so the boundary is
drawn at "generic number formatting lives here; sheet-specific live formulas live with
the sheet that owns them." See README "Design boundary" section.
"""

from templates.formula_templates import MONEY_FORMAT, PERCENT_FORMAT


def apply_money_format(ws, df, column_names, start_row=2):
    for col_name in column_names:
        if col_name not in df.columns:
            continue
        col_idx = df.columns.get_loc(col_name) + 1
        for r in range(start_row, ws.max_row + 1):
            ws.cell(row=r, column=col_idx).number_format = MONEY_FORMAT


def apply_percent_format(ws, df, column_names, start_row=2):
    for col_name in column_names:
        if col_name not in df.columns:
            continue
        col_idx = df.columns.get_loc(col_name) + 1
        for r in range(start_row, ws.max_row + 1):
            ws.cell(row=r, column=col_idx).number_format = PERCENT_FORMAT
