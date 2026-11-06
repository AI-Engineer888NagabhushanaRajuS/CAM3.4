"""
SPEC-017 bug (reports/sum_and_count_detailed.py vs sum_and_count.py): the detail rows skipped
nothing and took only the FIRST row's quantity for a repeated CPN, while the summary skipped
null quantities and summed every row. Sum & Count's SUMIFS reads the detail sheet, so the sheet
and the JSON disagreed. The detail must match the summary: skip null quantity, sum repeats.
"""
import os
import sys

SUP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mcp-tools", "reporting", "superset"))


def _detail(items):
    sys.path.insert(0, SUP)
    try:
        import reports.sum_and_count_detailed as d
    finally:
        sys.path.remove(SUP)
    return d.sum_and_count_detail({"scrub_bom_items": items, "rfqs": []})


def test_repeated_cpn_quantity_is_summed_like_the_summary():
    rows = _detail([
        {"Assembly": "A1", "CPN": "C1", "Quantity": 5, "FG": "F1"},
        {"Assembly": "A1", "CPN": "C1", "Quantity": 3, "FG": "F1"},
    ])
    assert rows and rows[0]["Scrub Bom Sum"] == 8.0, rows


def test_null_quantity_row_is_skipped_like_the_summary():
    rows = _detail([
        {"Assembly": "A1", "CPN": "C1", "Quantity": None, "FG": "F1"},
        {"Assembly": "A1", "CPN": "C2", "Quantity": 5, "FG": "F1"},
    ])
    assert [r["CPN"] for r in rows] == ["C2"], rows
