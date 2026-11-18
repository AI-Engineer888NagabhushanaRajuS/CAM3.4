"""Shared pieces of the Drills sheet modules (reports/drills_*.py): the "to fill" marker, styles, small value helpers.

Drills' internal workbook has eight sheets CAM did not produce (Scrub BOM, Supplier, Currency, Batch Qty, Raw CBOM, CBOM Checklist,
PCB Spec, Sales Checklist). acceptance_evidence/drills_sheets/DESIGN.md says where every column comes from. A Drills input that CAM
holds no data for is never invented: its cell is yellow, and where the cell itself carries text it says TO_FILL.
"""
import math
import re
from datetime import datetime

from openpyxl.styles import Alignment, Border, PatternFill, Side

TO_FILL = "to fill"
YELLOW = PatternFill("solid", fgColor="FFFF00")
_THIN = Side(style="thin")
BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
LEFT = Alignment(horizontal="left", vertical="center", wrap_text=True)
LEFT_NOWRAP = Alignment(horizontal="left", vertical="center")


def fill(rgb):
    return PatternFill("solid", fgColor=rgb)


def val(x):
    """A DuckDB value as openpyxl accepts it: NaN and non-finite floats become empty, datetimes lose their time zone."""
    if isinstance(x, float) and not math.isfinite(x):
        return None
    if isinstance(x, datetime) and x.tzinfo is not None:
        return x.replace(tzinfo=None)
    return x


def base_rfq(rfq_key):
    """'B12-CE-005632__v2' -> 'B12-CE-005632' (the DuckDB scoping key of a version -> the RFQ id Postgres knows)."""
    return str(rfq_key).split("__v")[0]


def rfq_number(rfq_key):
    """The Centum RFQ number Drills prints ('CE-005864'): the CE-nnnnnn part of the id when it has one, else the bare RFQ id."""
    m = re.search(r"CE-\d+", base_rfq(rfq_key))
    return m.group(0) if m else base_rfq(rfq_key)


def volume_label(volume):
    """'proto' -> 'Proto', '1' -> 'V1' (Drills' 'V1 Qty' header style)."""
    return "Proto" if str(volume).lower() == "proto" else f"V{volume}"


def order_volumes(volumes):
    """Proto first, then numbers ascending (the order every CAM sheet uses; queries._order_volumes)."""
    def key(v):
        if str(v).lower() == "proto":
            return (0, 0, "")
        try:
            return (1, int(v), "")
        except (TypeError, ValueError):
            return (2, 0, str(v))
    return sorted(set(volumes), key=key)


def add_sheet(wb, title, hidden=False):
    if title in wb.sheetnames:
        raise ValueError(f"the workbook already has a sheet named {title!r}; build_drills_sheets would silently rename its own")
    ws = wb.create_sheet(title=title)
    if hidden:
        ws.sheet_state = "hidden"
    return ws


def style_range(ws, row1, row2, col1, col2, *, font=None, fill_=None, border=None, align=None, number_format=None):
    for r in range(row1, row2 + 1):
        for c in range(col1, col2 + 1):
            cell = ws.cell(row=r, column=c)
            if font is not None:
                cell.font = font
            if fill_ is not None:
                cell.fill = fill_
            if border is not None:
                cell.border = border
            if align is not None:
                cell.alignment = align
            if number_format is not None:
                cell.number_format = number_format


def set_widths(ws, widths):
    """widths: {'A': 17.4, ...}"""
    for letter, w in widths.items():
        ws.column_dimensions[letter].width = w


def mark_to_fill(cell, text=True):
    """A Drills input CAM has no data for: yellow, and TO_FILL when the cell itself carries text."""
    cell.fill = YELLOW
    if text:
        cell.value = TO_FILL

