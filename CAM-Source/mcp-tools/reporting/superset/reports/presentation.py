"""Presentation of the delivered workbook: one pass over every tab before it is saved.

What it does and, since 2026-11-18, what it no longer does (CAM 3.3 comparison, acceptance_evidence/excel_fidelity):
  * a header (bold cell) is centred and wrapped; it keeps the fill and the font colour the tab's own builder gave it (the
    reverse-engineered navy/white, yellow, red cells). A header without any fill gets the light-blue one.
  * a number typed into a cell is right-aligned; everything else keeps the alignment the builder set or Excel's own
    (text left, numbers right). A formula is NOT forced right: most formulas on BOM MATRIX / Revision History / A CLASS PARTS return
    text (description, manufacturer, MPN), and right-aligned text that does not fit is cut off on its LEFT.
  * long free text (more than 60 characters) wraps; a "*** Assembly: ... ***" caption, a merged cell and a title never do.
  * column widths: a column holding text, or a formula that returns text (found by its header: Description, Mfg Name ...), is made
    wide enough to read, up to 60 characters. Widths only grow, never shrink. A column of numbers is at least 14 wide.
  * number formats, found by the header: %/percent/scrap -> 0.00%, price/cost/amount/spend -> the money format, qty/quantity -> whole
    numbers. Only a cell still on "General" is changed.
  * body cells lose their row tints (grid borders only, every populated cell gets a thin border); yellow totals and red alerts stay.
  * fonts with no name (the builders' bare Font(bold=...)) become Calibri; sizes and colours are kept.
  * a long data tab (more than 20 rows) with no freeze panes is frozen below its header row (rows 1-3 searched).
Values and formulas are never changed.
"""
from copy import copy

from openpyxl.styles import Alignment, PatternFill
from openpyxl.utils import get_column_letter

from templates.excel_styles import THIN_BORDER
from templates.formula_templates import MONEY_FORMAT, PERCENT_FORMAT

HEADER_FILL = PatternFill("solid", fgColor="D9E1F2")
BODY_TINTS = {"F2F6FC", "D9EAF7", "FDE2E2", "E2F7E2", "E9E2FD", "FFF7D9", "F8CBAD", "FFE699", "C6E0B4"}   # row tints on data cells (incl. Feasibility risk colours; the risk text stays)
QTY_FORMAT = "#,##0"
WRAP_OVER = 60          # characters; a text longer than this wraps
MAX_WIDTH = 60
SCAN_ROWS = 500         # rows read per column to size it

# Columns that carry text although their cells are formulas (INDEX/MATCH against the CBOM tab): the header says what they hold.
# width in characters. Matched on the lower-cased header text.
TEXT_COLUMNS = {
    "description": 42, "mfg name": 26, "manufacturer": 26, "mfg part number": 26, "mpn": 26, "supp name": 26, "supplier": 26,
    "part number": 22, "cpn": 22, "assembly": 22, "fg": 22, "fg part number": 22, "commodity": 16, "long comment": 34, "remarks": 34,
    "comment": 34, "note": 34,
}


def _is_typed_number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float))


def _is_formula(value):
    return isinstance(value, str) and value.startswith("=")


def _format_for(names):
    """Number format for a column, from its header texts (lower-cased). None when the header says nothing numeric."""
    def has(*keys):
        return any(k in n for n in names for k in keys)
    if has("%", "percent", "scrap"):
        return PERCENT_FORMAT
    if has("price", "cost", "amount", "spend", "$"):
        return MONEY_FORMAT
    if has("qty", "quantity"):
        return QTY_FORMAT
    return None


def _freeze_below_header(ws):
    """Freeze under the first header row (one of rows 1-3 with two or more bold captions), on a long tab that has no freeze yet."""
    if ws.freeze_panes is not None or ws.max_row <= 20:
        return
    for r in range(1, min(ws.max_row, 3) + 1):
        bold = [c for c in ws[r] if isinstance(c.value, str) and c.font and c.font.b and not c.value.startswith("***")]
        if len(bold) >= 2:
            ws.freeze_panes = f"A{r + 1}"
            return


def style_sheet(ws):
    merged_coords = {f"{get_column_letter(c)}{r}" for rng in ws.merged_cells.ranges for r, c in rng.cells}
    formats = {col: _format_for(_header_names(ws, col)) for col in range(1, ws.max_column + 1)}
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=ws.max_column):
        for cell in row:
            is_header = bool(cell.font and cell.font.b)
            if not is_header and cell.fill is not None and cell.fill.fill_type == "solid" and cell.fill.fgColor.rgb[-6:] in BODY_TINTS:
                cell.fill = PatternFill(fill_type=None)
            if cell.value is None:
                continue
            existing = cell.alignment
            if cell.font is not None and cell.font.name is None:
                font = copy(cell.font)
                font.name = "Calibri"
                font.sz = font.sz or 11
                cell.font = font
            if not cell.border.left.style and cell.coordinate not in merged_coords:
                cell.border = THIN_BORDER
            if is_header:
                if cell.fill is None or cell.fill.fill_type is None:
                    cell.fill = HEADER_FILL
                wrap = cell.coordinate not in merged_coords and not (isinstance(cell.value, str) and cell.value.startswith("***"))
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=wrap)
            elif _is_typed_number(cell.value):
                cell.alignment = Alignment(horizontal="right", vertical="center")
            else:
                text = isinstance(cell.value, str) and not _is_formula(cell.value)
                wrap = (text and len(cell.value) > WRAP_OVER and not cell.value.startswith("***")
                        and cell.coordinate not in merged_coords)
                cell.alignment = Alignment(horizontal=existing.horizontal or ("left" if text else None), vertical="center", wrap_text=wrap)
            if not is_header and cell.number_format == "General" and (_is_typed_number(cell.value) or _is_formula(cell.value)):
                cell.number_format = formats[cell.column] or "General"
    autosize_columns(ws)
    _freeze_below_header(ws)


def _header_names(ws, col):
    """Lower-cased header texts of one column: the bold string cells (the captions "*** ..." and long titles are not headers)."""
    names = set()
    for r in range(1, min(ws.max_row, SCAN_ROWS) + 1):
        c = ws.cell(row=r, column=col)
        if isinstance(c.value, str) and c.font and c.font.b and len(c.value) <= 40 and not c.value.startswith("***"):
            names.add(c.value.strip().lower())
    return names


def autosize_columns(ws):
    for col in range(1, ws.max_column + 1):
        letter = get_column_letter(col)
        wanted = 0
        for r in range(1, min(ws.max_row, SCAN_ROWS) + 1):
            c = ws.cell(row=r, column=col)
            v = c.value
            if isinstance(v, str) and not _is_formula(v) and not (c.font and c.font.b) and not v.startswith("***"):
                wanted = max(wanted, min(len(v), MAX_WIDTH) + 2)
            elif (_is_typed_number(v) or _is_formula(v)) and c.number_format != "General":
                wanted = max(wanted, 14)
        for name in _header_names(ws, col):
            wanted = max(wanted, TEXT_COLUMNS.get(name, 0), max((len(w) for w in name.split()), default=0) + 2)
        wanted = min(wanted, MAX_WIDTH)
        dim = ws.column_dimensions[letter]
        if wanted and (dim.width is None or dim.width < wanted):
            dim.width = wanted


def style_workbook(wb):
    for ws in wb.worksheets:
        style_sheet(ws)
    return wb
