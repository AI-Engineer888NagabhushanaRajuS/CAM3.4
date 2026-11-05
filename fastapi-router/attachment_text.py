"""Text of a released RFQ attachment, as labelled chunks the assistant can cite (and Repel scans for injection).

chunks(path, display_name) -> [{"text", "label"}]: spreadsheet rows as "Sheet, row N: Header=value; ..." (the same
shape and value formatting as chat_evidence.py), text files and Word paragraphs in windows, PDFs per page.
At most MAX_CHUNKS chunks per file, each at most MAX_CHUNK_CHARS. An unknown type has no text: [].
"""
import csv
import io
import os
import re
import zipfile
import xml.etree.ElementTree as ET

import openpyxl
from openpyxl.utils import get_column_letter

from chat_evidence import _fmt, _header_index

MAX_CHUNKS = 2000
MAX_CHUNK_CHARS = 1800


def _cut(text):
    return text if len(text) <= MAX_CHUNK_CHARS else text[:MAX_CHUNK_CHARS] + " ...[truncated]"


def _rows(name, sheet, rows, out, fmt=lambda v: "" if v is None else str(v).strip()):
    """rows: lists of cells (anything fmt understands). Header = the first header-looking row of the first 8."""
    values = [[getattr(c, "value", c) for c in r] for r in rows]
    head_at = _header_index(values)
    header = [fmt(c) for c in rows[head_at]] if head_at is not None else []
    for i, row in enumerate(rows):
        if len(out) >= MAX_CHUNKS:
            return
        if head_at is not None and i <= head_at:
            continue
        parts = []
        for col, cell in enumerate(row):
            shown = fmt(cell)
            if shown:
                label = header[col] if col < len(header) and header[col] else get_column_letter(col + 1)
                parts.append(f"{label}={shown}")
        if parts:
            where = f"{sheet}, row {i + 1}" if sheet else f"row {i + 1}"
            out.append({"text": _cut(f"{name}, {where}: " + "; ".join(parts)),
                        "label": f"{name}!{sheet} row {i + 1}" if sheet else f"{name} row {i + 1}"})


def _windows(name, pieces, unit, out):
    """Pack consecutive lines/paragraphs into windows of at most MAX_CHUNK_CHARS; label '<file> lines 3-9'."""
    buf, first = [], None
    for n, piece in pieces:
        piece = piece.strip()
        if not piece:
            continue
        if buf and sum(len(b) + 1 for b in buf) + len(piece) > MAX_CHUNK_CHARS:
            out.append({"text": _cut("\n".join(buf)), "label": f"{name} {unit} {first}-{last}"})
            buf, first = [], None
            if len(out) >= MAX_CHUNKS:
                return
        buf.append(piece)
        first, last = first or n, n
    if buf and len(out) < MAX_CHUNKS:
        out.append({"text": _cut("\n".join(buf)), "label": f"{name} {unit} {first}-{last}"})


def _decode(path):
    with open(path, "rb") as f:
        raw = f.read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8-sig")   # strips the one leading BOM Excel's "CSV UTF-8" writes
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def _xlsx(path, name, out):
    with open(path, "rb") as f:   # a file object: openpyxl judges a path by its extension
        _xlsx_book(openpyxl.load_workbook(f, data_only=True, read_only=True), name, out)


def _xlsx_book(wb, name, out):
    try:
        for ws in wb.worksheets:
            _rows(name, ws.title, [tuple(r) for r in ws.iter_rows()], out, fmt=_fmt)
    finally:
        wb.close()


def _xls(path, name, out):
    try:
        import xlrd
    except ImportError:
        return   # xlrd not installed: no text, the file is still scanned and stored
    book = xlrd.open_workbook(path, on_demand=True)
    for sheet in book.sheets():
        _rows(name, sheet.name, [sheet.row_values(i) for i in range(sheet.nrows)], out,
              fmt=lambda v: (str(int(v)) if isinstance(v, float) and v == int(v) else str(v).strip()) if v != "" else "")


def _csv(path, name, out, delimiter):
    rows = list(csv.reader(io.StringIO(_decode(path)), delimiter=delimiter))
    _rows(name, "", rows, out)


def _docx(path, name, out):
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(path) as zf:
        root = ET.fromstring(zf.read("word/document.xml"))
    paras = ["".join(t.text or "" for t in p.iter(w + "t")) for p in root.iter(w + "p")]
    _windows(name, enumerate(paras, 1), "para", out)


def _pdf(path, name, out):
    import pymupdf
    with pymupdf.open(path, filetype="pdf") as doc:
        for number, page in enumerate(doc, 1):
            text = re.sub(r"[ \t]+", " ", page.get_text()).strip()
            for start in range(0, len(text), MAX_CHUNK_CHARS):
                if len(out) >= MAX_CHUNKS:
                    return
                out.append({"text": text[start:start + MAX_CHUNK_CHARS], "label": f"{name} p.{number}"})


def chunks(path, display_name):
    ext = os.path.splitext(display_name)[1].lower()
    out = []
    if ext in (".xlsx", ".xlsm"):
        _xlsx(path, display_name, out)
    elif ext == ".xls":
        with open(path, "rb") as f:
            is_zip = f.read(2) == b"PK"
        (_xlsx if is_zip else _xls)(path, display_name, out)
    elif ext in (".csv", ".tsv"):
        _csv(path, display_name, out, "\t" if ext == ".tsv" else ",")
    elif ext in (".txt", ".md", ".json"):
        _windows(display_name, enumerate(_decode(path).splitlines(), 1), "lines", out)
    elif ext == ".docx":
        _docx(path, display_name, out)
    elif ext == ".pdf":
        _pdf(path, display_name, out)
    return out[:MAX_CHUNKS]
