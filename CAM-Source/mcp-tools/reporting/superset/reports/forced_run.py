"""Hover comments on the error cells of a forced run ("Force Run Anyway").

When the upload pre-check finds problems in the BOM and the user runs anyway, the output still has the cells those problems reach.
Each such error cell keeps its formula and gets a comment: the input problem for its part (or the run's problems when the row names no
flagged part). Nothing is filled in; the comment is the only addition.
"""
import json
import os

import openpyxl
from openpyxl.cell.cell import MergedCell
from openpyxl.comments import Comment

import config

ERROR_VALUES = ("#N/A", "#REF!", "#VALUE!", "#DIV/0!", "#NAME?", "#NUM!", "#NULL!")
AUTHOR = "CAM"
MESSAGES_PER_PART = 3


def load_run(rfq_id):
    """The forced run's record written by the upload service, or None when the run was not forced."""
    path = os.path.join(config.PROJECT_DATABASE_DIR, "forced_runs", f"{rfq_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _comment_text(part, issues, run_total):
    if part:
        own = issues[:MESSAGES_PER_PART]
        detail = "; ".join(f"{i['sheet']} row {i['row']} {i['column']}: {i['message']}" for i in own)
        more = f" (+{len(issues) - len(own)} more)" if len(issues) > len(own) else ""
        return f"Forced run. Input problem for part {part}: {detail}{more}"
    return (f"Forced run: the uploaded BOM had {run_total} input problem(s). This cell is in error because its input is incomplete; "
            "the run went ahead anyway.")


def annotate_error_cells(path, rfq_id):
    """Adds a comment to each error cell of the workbook at path. Returns what it did (a skipped run changes nothing)."""
    run = load_run(rfq_id)
    if not run:
        return {"status": "skipped", "reason": "not a forced run"}
    issues = [i for i in run.get("issues", []) if i.get("severity", "error") == "error"]
    by_part = {}
    for issue in issues:
        if issue.get("part"):
            by_part.setdefault(issue["part"].upper(), []).append(issue)
    values = openpyxl.load_workbook(path, data_only=True)
    book = openpyxl.load_workbook(path)
    commented = blanks = 0
    for ws in book.worksheets:
        rows = list(values[ws.title].iter_rows())
        filled = _normally_filled_columns(rows)
        for row in rows:
            errors = [c for c in row if isinstance(c.value, str) and c.value in ERROR_VALUES]
            part = next((str(c.value).strip().upper() for c in row if isinstance(c.value, str) and str(c.value).strip().upper() in by_part), None)
            if not errors and not part:
                continue
            text = _comment_text(part, by_part.get(part, []), len(issues))
            # Blank where the column is normally filled, in a row of a flagged part: the input problem left it empty.
            gaps = [c for c in row if part and c.column in filled and _blank(c.value)] if part else []
            for c in errors + gaps:
                target = ws[c.coordinate]
                if isinstance(target, MergedCell):  # a merged block carries its comment on its top-left cell only
                    continue
                comment = Comment(text, AUTHOR)
                comment.width, comment.height = 340, 140
                target.comment = comment
                commented += 1
                blanks += 0 if c in errors else 1
    if commented:
        book.save(path)
    return {"status": "ok", "forced_issues": len(issues), "error_cells_commented": commented - blanks, "blank_cells_commented": blanks}


def _blank(value):
    return value is None or (isinstance(value, str) and value.strip() == "")


def _normally_filled_columns(rows):
    """Column indexes that hold a value in most of the sheet's data rows (rows with at least three values): a blank there is a gap."""
    data_rows = [r for r in rows if sum(1 for c in r if not _blank(c.value)) >= 3]
    if len(data_rows) < 2:
        return set()
    have = {}
    for r in data_rows:
        for c in r:
            if not _blank(c.value):
                have[c.column] = have.get(c.column, 0) + 1
    return {col for col, n in have.items() if n >= 0.5 * len(data_rows)}
