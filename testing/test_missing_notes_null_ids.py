"""
SPEC-017 bug (reports/missing_notes.py _section_price_validity): rows without an id were all
deduped into one (None is a single key). Only real duplicate ids may be collapsed.
"""
import datetime as dt
import os
import sys

SUP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mcp-tools", "reporting", "superset"))


def test_rows_without_ids_are_not_collapsed():
    sys.path.insert(0, SUP)
    try:
        import reports.missing_notes as mn
    finally:
        sys.path.remove(SUP)
    as_of = dt.datetime(2026, 1, 1)
    expiry = (as_of + dt.timedelta(days=5)).strftime("%Y-%m-%d")
    rows = [{"id": None, "expiry_date": expiry, "cpn": f"C{i}", "mpn": f"M{i}"} for i in range(3)]
    out = mn._section_price_validity(rows, {}, as_of)
    assert len(out) == 3, out
