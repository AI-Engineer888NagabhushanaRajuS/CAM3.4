"""What a released workbook IS, read from its contents (SPEC-022). Runs only on a copy that both engines already released.

The rules mirror what the pipeline reads: `standardize_scrub_bom` needs a sheet named SCRUB BOM (case and spaces
ignored, scrub_bom_processing._resolve_sheet_name); `standardize_quote_win` finds its table by the header row holding
Part Number, Mfg Part Number and Commodity (quote_win_processing._HEADER_ROW_SIGNATURE). Nothing is guessed beyond
that: a file matching no layout is `unknown`, and there is no costing-sheet role because no sample exists.
"""
import csv
import os
import re
from typing import Optional

SHEET_SCRUB_BOM = "SCRUB BOM"
QUOTEWIN_SIGNATURE = ("part number", "mfg part number", "commodity")
HEAD_ROWS = 12            # rows read to find a header
QUOTEWIN_ROWS = 2000      # the QuoteWin table sits below a report preamble
MAX_SHEETS = 8

LABELS = {
    "scrub_bom": "BOM workbook (SCRUB BOM)",
    "bom": "BOM without a SCRUB BOM sheet",
    "volume": "Volume file",
    "quotewin": "QuoteWin export",
    "document": "Reference document",
    "unknown": "Not recognised",
}
_VOLUME_COL = re.compile(r"^(v|vl|vol|volume)[\s_-]*\d*(\s*qty)?$")
_ID_COLS = ("cpn", "mpn", "part number", "mfg part number", "manufacturer part number")
_BOM_ONLY_COLS = ("quantity", "qty", "uom", "commodity", "reference designator", "ref des")


def _cells(row) -> list:
    return [str(c).strip().lower() for c in row if c is not None and str(c).strip()]


def _result(role: str, reason: str, sheets: list, problems: Optional[list] = None) -> dict:
    return {"role": role, "role_label": LABELS[role], "role_reason": reason, "problems": problems or [], "sheets": sheets[:MAX_SHEETS]}


def _is_volume_header(cells: list) -> bool:
    has_id = any(c in _ID_COLS for c in cells)
    has_vol = any(_VOLUME_COL.match(c) for c in cells)
    return has_id and has_vol and not any(c in _BOM_ONLY_COLS for c in cells)


def _is_bom_header(cells: list) -> bool:
    return any(c in _ID_COLS for c in cells) and any(c in _BOM_ONLY_COLS for c in cells)


def _classify_tables(sheets: list, tables: dict) -> dict:
    """tables: {sheet name: first rows}. Applies the rules in order; the first match wins."""
    if any(s.strip().upper() == SHEET_SCRUB_BOM for s in sheets):
        extra = [s for s in sheets if s.strip().lower() in ("settings", "batch")]
        return _result("scrub_bom", f"Has a sheet named {SHEET_SCRUB_BOM}" + (f" and {' / '.join(extra)}" if extra else " (no Settings/Batch: one implicit volume)"), sheets)
    for name, rows in tables.items():
        for row in rows:
            cells = _cells(row)
            if all(sig in cells for sig in QUOTEWIN_SIGNATURE):
                return _result("quotewin", f"Sheet {name} has the QuoteWin table header (Part Number, Mfg Part Number, Commodity)", sheets,
                               ["QuoteWin files belong to the ERP & Quoting tools step, not to RFQ creation."])
    for name, rows in tables.items():
        for row in rows[:HEAD_ROWS]:
            cells = _cells(row)
            if _is_bom_header(cells):
                return _result("bom", f"Sheet {name} looks like a BOM (columns {', '.join(cells[:5])}) but no sheet is named {SHEET_SCRUB_BOM}", sheets,
                               [f"No sheet named {SHEET_SCRUB_BOM} (sheets: {', '.join(sheets) or 'none'}). The first pipeline step would reject this file as invalid input; use the Scrub BOM workbook."])
            if _is_volume_header(cells):
                return _result("volume", f"Sheet {name} has part columns and volume columns only", sheets)
    return _result("unknown", "No sheet matches a BOM, volume or QuoteWin layout", sheets)


def classify_file(path: str, name: Optional[str] = None) -> dict:
    """Role of a released file. Never raises: a file that cannot be opened is `unknown` with the reason."""
    ext = os.path.splitext(name or path)[1].lower()
    try:
        if ext in (".xlsx", ".xlsm"):
            import openpyxl
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            try:
                sheets = list(wb.sheetnames)
                tables = {}
                for s in sheets[:MAX_SHEETS]:
                    limit = QUOTEWIN_ROWS if len(tables) < 3 else HEAD_ROWS
                    tables[s] = [r for _, r in zip(range(limit), wb[s].iter_rows(values_only=True))]
                return _classify_tables(sheets, tables)
            finally:
                wb.close()
        if ext in (".csv", ".tsv"):
            with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
                rows = [r for _, r in zip(range(QUOTEWIN_ROWS), csv.reader(f, delimiter="\t" if ext == ".tsv" else ","))]
            return _classify_tables([os.path.basename(name or path)], {os.path.basename(name or path): rows})
        if ext == ".xls":
            try:
                import xlrd
            except ImportError:
                return _result("unknown", "Legacy .xls files cannot be read on this server", [])
            book = xlrd.open_workbook(path, on_demand=True)
            try:
                sheets = book.sheet_names()
                tables = {s: [book.sheet_by_name(s).row_values(i) for i in range(min(book.sheet_by_name(s).nrows, QUOTEWIN_ROWS))] for s in sheets[:MAX_SHEETS]}
                return _classify_tables(sheets, tables)
            finally:
                book.release_resources()
        return _result("document", f"A {ext.lstrip('.') or 'plain'} document, kept as context for the assistant", [])
    except Exception as e:
        return _result("unknown", f"Could not read the file: {type(e).__name__}", [])
