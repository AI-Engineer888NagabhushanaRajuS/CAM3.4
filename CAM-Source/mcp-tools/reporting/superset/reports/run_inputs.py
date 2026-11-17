"""The 'Run Inputs' tab: which inputs this report was built from, and what a missing input means for the figures.

The exporter knows which inputs it could read (the BOM rows and the QuoteWin rows of this RFQ's version). An input that is required and
missing means the run was allowed to go on without it ("Proceed with missing values"): the tab says so, row by row, so the report is never
read as if every input had been given. Pure functions; the exporter passes in the row counts it already loaded.
"""

from openpyxl.styles import Alignment, Font, PatternFill

HEADERS = ["Input", "Required", "Status", "What it means for this report"]

# (input, required, what the figures are when it is missing)
INPUTS = (
    ("BOM file", True, "No BOM rows: the report has no parts."),
    ("QuoteWin export", True, "No QuoteWin prices: parts are not priced from QuoteWin; costs and the Missing Notes show the gap."),
)


def run_input_rows(bom_rows: int, quotewin_rows: int) -> list[list[str]]:
    """One row per input the exporter can see, with its status in plain words."""
    counts = {"BOM file": bom_rows, "QuoteWin export": quotewin_rows}
    out = []
    for name, required, missing_effect in INPUTS:
        n = counts[name]
        if n > 0:
            status, effect = "Provided", f"{n} rows read."
        elif required:
            status, effect = "MISSING (required)", missing_effect
        else:
            status, effect = "Not provided", missing_effect
        out.append([name, "Yes" if required else "No", status, effect])
    return out


def has_missing_required(rows: list[list[str]]) -> bool:
    return any(r[1] == "Yes" and r[2].startswith("MISSING") for r in rows)


def build_run_inputs_sheet(wb, rows: list[list[str]], title: str = "Run Inputs"):
    """Adds the tab last. Missing required inputs are filled red so they cannot be missed."""
    ws = wb.create_sheet(title=title)
    ws.append(HEADERS)
    for c in ws[1]:
        c.font = Font(bold=True)
    for row in rows:
        ws.append(row)
        if row[1] == "Yes" and row[2].startswith("MISSING"):
            for c in ws[ws.max_row]:
                c.fill = PatternFill("solid", fgColor="F8D7DA")
    for col, width in zip("ABCD", (22, 12, 22, 90)):
        ws.column_dimensions[col].width = width
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    return ws
