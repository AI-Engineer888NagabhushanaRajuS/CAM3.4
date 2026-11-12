"""Evidence for the RFQ assistant: the RFQ's own results, as citable text chunks.

The assistant must answer from what is actually in the RFQ's results, never from a model's memory. This module
turns the latest exported workbook (every tab, with the values the export stores) and the RFQ's live state into
small chunks, each carrying a citation that points at the sheet and cells it came from, and ranks them against a
question. No model is involved here: what comes out is exactly what is in the files.

Part numbers and the like are checked against the whole workbook, so the caller can say "that is not in the
results" for something that does not exist, instead of letting a model guess.

Known limits (told to the user by the caller, never hidden): the evidence for one question is the best-matching rows,
not a scan of every row, so a "list all ..." answer can be incomplete; a tab with several blocks gets the header of
its first block.
"""
import datetime
import math
import os
import re
from collections import Counter, OrderedDict

import openpyxl
from openpyxl.utils import get_column_letter

SMALL_SHEET_ROWS = 40        # a tab this small is shown whole when budget allows: summaries answer "how much / how many"
MAX_EVIDENCE_CHARS = 9000    # what one question may put in front of the model
MAX_ROW_CHARS = 1800         # one wide row (the CBOM has 77 columns) is cut here, and says so
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\-/]*")
_UNIT_VALUE = re.compile(r"^\d+(\.\d+)?[A-Za-z%]{0,3}$")   # 10uF, 3.3V, 0402, 25V: a value with a unit, not a part number
_STOP = frozenset("""a an and are as at be by can do does for from has have how i in is it its me my of on or our
please show tell than that the their there these this to us was we what when where which who why will with you
rfq results result about give list all any each per""".split())
_cache = OrderedDict()       # (path, mtime) -> index; the few newest workbooks (two users on different RFQs)
_CACHE_SIZE = 4


def _fmt(cell):
    """The value as a reader of the sheet would see it: percentages as percentages, dates as dates."""
    v = cell.value
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, datetime.datetime):
        return v.isoformat(sep=" ") if (v.hour or v.minute or v.second) else v.date().isoformat()
    if isinstance(v, datetime.date):
        return v.isoformat()
    if isinstance(v, (int, float)):
        if "%" in (cell.number_format or ""):
            return f"{v * 100:.10g}%"
        if isinstance(v, int):
            return str(v)
        return str(int(v)) if v == int(v) and abs(v) < 1e15 else f"{v:.10g}"
    return str(v).strip()


def _tokens(text):
    return [t for t in (w.lower().rstrip("._-/") for w in _WORD.findall(text)) if t]   # "UBR03225." ends a sentence, not the part


def _identifier_like(token):
    """A part number / code (UBR03225, AC0603FR-0762KL, MPN-123) or a long hyphenated number (1-104479-0).
    Not a plain number, a threshold such as 1.25, or a value with a unit such as 10uF, 3.3V, 0402."""
    if len(token) < 6 or not any(ch.isdigit() for ch in token) or _UNIT_VALUE.match(token):
        return False
    return any(ch.isalpha() for ch in token) or "-" in token


def _squash(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _header_index(rows):
    for i, row in enumerate(rows[:8]):
        cells = [c for c in row if c not in (None, "")]
        if len(cells) >= 2 and sum(isinstance(c, str) for c in cells) >= 0.6 * len(cells):
            return i
    return None


def _chunk(text, workbook, sheet, row, last_col, always=False):
    if len(text) > MAX_ROW_CHARS:
        text = text[:MAX_ROW_CHARS] + " ...[row truncated]"
    label = f"{sheet}!A{row}:{get_column_letter(max(last_col, 1))}{row}"
    return {
        "text": text,
        "citation": {"sourceType": "excel_export", "label": label,
                     "identifier": {"workbook": workbook, "sheet": sheet, "row": row}},
        "tokens": _tokens(text), "always": always, "pinned": False,
    }


def _uncached_formulas(path):
    """(formula cells with no stored value, all formula cells). A formula that evaluates to "" has no value either,
    so a few are normal; an export that was never recalculated has none at all."""
    formulas = openpyxl.load_workbook(path, read_only=True)
    values = openpyxl.load_workbook(path, data_only=True, read_only=True)
    missing = total = 0
    for ws in formulas.worksheets:
        rows_f, rows_v = ws.iter_rows(), values[ws.title].iter_rows()
        try:
            for row_f, row_v in zip(rows_f, rows_v):
                for f, v in zip(row_f, row_v):
                    if f.data_type == "f":
                        total += 1
                        missing += v.value is None
        finally:
            # zip stops at the first reader to end; a reader that was not run to its end keeps the file open, and on Windows that
            # locks it (the cache writer's os.replace then fails with "Access is denied"). Run both to the end, then close.
            for rest in (rows_f, rows_v):
                for _ in rest:
                    pass
                rest.close()
    formulas.close()
    values.close()
    return missing, total


def workbook_index(path):
    """Parse every tab of the export into row chunks (cached per file version)."""
    key = (path, os.path.getmtime(path))
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    name = os.path.basename(path)
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)  # the values the export stored
    chunks, sheets, full_text = [], [], []
    for ws in wb.worksheets:
        rows = [tuple(r) for r in ws.iter_rows()]
        values = [tuple(c.value for c in r) for r in rows]
        used = [i for i, r in enumerate(values) if any(c not in (None, "") for c in r)]
        sheets.append((ws.title, len(used), ws.max_column or 0))
        head_at = _header_index(values)
        header = [_fmt(c) for c in rows[head_at]] if head_at is not None else []
        small = len(used) <= SMALL_SHEET_ROWS
        for i in used:
            if head_at is not None and i <= head_at:
                continue
            parts = []
            for col, cell in enumerate(rows[i]):
                shown = _fmt(cell)
                if shown == "":
                    continue
                label = header[col] if col < len(header) and header[col] else get_column_letter(col + 1)
                parts.append(f"{label}={shown}")
            if parts:
                text = f"{ws.title}, row {i + 1}: " + "; ".join(parts)
                chunks.append(_chunk(text, name, ws.title, i + 1, len(rows[i]), always=small))
                full_text.append(text)
    wb.close()
    catalogue = (f"Workbook {name} has {len(sheets)} tabs: "
                 + "; ".join(f"{s} ({n} rows used, {c} columns)" for s, n, c in sheets) + ".")
    chunks.insert(0, {"text": catalogue, "citation": {"sourceType": "excel_export", "label": "Workbook tabs",
                                                      "identifier": {"workbook": name}},
                      "tokens": _tokens(catalogue), "always": False, "pinned": True})
    missing, total = _uncached_formulas(path)
    warning = (f"{missing} of {total} formula cells in this workbook have no stored value (it was exported without recalculation), "
               f"so figures that depend on them cannot be read from it."
               if total and missing >= 0.9 * total else None)
    index = {"chunks": chunks, "squashed": _squash("\n".join(full_text)), "sheets": sheets, "workbook": name,
             "warning": warning}
    _cache[key] = index
    while len(_cache) > _CACHE_SIZE:
        _cache.popitem(last=False)
    return index


def state_chunk(rfq_id, version, stage, hitl_required, files):
    """What the pipeline knows about this RFQ right now (from the database), as one citable chunk."""
    listed = "; ".join(f"{role}: {os.path.basename(path)} ({scan})" for role, path, scan in files) or "none"
    text = (f"RFQ {rfq_id}: active version {version}; pipeline stage {stage}; "
            f"waiting for a human review: {'yes' if hitl_required else 'no'}; files uploaded: {listed}.")
    return {"text": text, "citation": {"sourceType": "file_telemetry", "label": f"RFQ {rfq_id} status",
                                       "identifier": {"rfqId": rfq_id, "version": version}},
            "tokens": _tokens(text), "always": False, "pinned": True}


def _bm25(chunks, query_tokens, k1=1.4, b=0.75):
    n = len(chunks)
    lengths = [len(c["tokens"]) or 1 for c in chunks]
    avg = sum(lengths) / max(n, 1)
    df = Counter()
    for c in chunks:
        df.update(set(c["tokens"]))
    scores = []
    for c, length in zip(chunks, lengths):
        tf = Counter(c["tokens"])
        score = 0.0
        for t in set(query_tokens):
            if t in tf:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                score += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * length / avg))
                if _identifier_like(t):
                    score += 5.0   # naming a specific part number is the strongest signal there is
        scores.append(score)
    return scores


def _public(chunk, score=0.0):
    return {"text": chunk["text"], "citation": chunk["citation"], "score": round(score, 3)}


# Small tabs that answer "how much / how many / is it ready" go first when they are used as filler.
_PRIORITY = ["Summary", "Manifest", "Sum & Count", "Price Control", "Batchwise Cashflow", "Lead Time Consolidated",
             "PCB NRE & FAI Charge", "Mech & EM NRE", "Scrap Factor", "Batch Settings"]


def _sheet_rank(chunk):
    sheet = chunk["citation"]["identifier"].get("sheet", "")
    return _PRIORITY.index(sheet) if sheet in _PRIORITY else len(_PRIORITY)


def retrieve(index, question, extra=(), top_k=12, rfq_id=None, max_chars=MAX_EVIDENCE_CHARS):
    """Evidence for one question, in this order: the tab catalogue and RFQ state; the rows that match the question
    (a named part number first); then small tabs, whole, as filler for whatever budget is left. Matched rows must
    come before the filler: a real export has about 15 small tabs, enough to fill the whole budget by themselves
    and push out the row of a part number that exists.

    Returns {"chunks", "named_identifiers", "missing_identifiers", "matched_rows", "rows_in_results"}: the part
    numbers the question names (the RFQ's own id excluded), the ones among them that appear nowhere in the results,
    and how many rows matched out of how many the results hold (so a list can be called partial)."""
    query = [t for t in _tokens(question) if t not in _STOP]
    own_id = _squash(rfq_id or "")
    named = sorted({t for t in query if _identifier_like(t) and (not own_id or _squash(t) != own_id)})
    squashed = index.get("squashed", "") + "".join(_squash(c["text"]) for c in extra)  # attachments count as "in the results"
    missing = [t for t in named if _squash(t) not in squashed]
    candidates = list(extra) + index["chunks"]
    scores = _bm25(candidates, query) if query else [0.0] * len(candidates)
    pairs = list(zip(candidates, scores))
    pinned = [p for p in pairs if p[0].get("pinned")]
    matched = sorted((p for p in pairs if not p[0].get("pinned") and p[1] > 0), key=lambda p: -p[1])[:top_k]
    filler = sorted((p for p in pairs if p[0].get("always")), key=lambda p: (_sheet_rank(p[0]), -p[1]))
    picked, seen, used = [], set(), 0
    for c, s in pinned + matched + filler:
        if id(c) in seen or used + len(c["text"]) > max_chars:
            continue
        seen.add(id(c))
        picked.append(_public(c, s))
        used += len(c["text"])
    return {"chunks": picked, "missing_identifiers": missing, "named_identifiers": named,
            "matched_rows": sum(1 for p in pairs if not p[0].get("pinned") and p[1] > 0),
            "rows_in_results": sum(1 for c in index["chunks"] if not c.get("pinned"))}
