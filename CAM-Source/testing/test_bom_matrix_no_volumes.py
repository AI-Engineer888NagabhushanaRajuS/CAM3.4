"""
SPEC-017 bug (reports/bom_matrix.py): an RFQ with FG counts but no volume entries (a proto-only
BOM) raised KeyError (fg_price_cols[(fi, 0)]) while merging FG price headers. Nothing to build
without volume columns, so the sheet must come out without raising.
"""
import os
import sys

from openpyxl import Workbook

SUP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mcp-tools", "reporting", "superset"))


def test_bom_matrix_with_no_volume_entries_does_not_raise():
    sys.path.insert(0, SUP)
    try:
        import reports.bom_matrix as bm
    finally:
        sys.path.remove(SUP)
    rows = [{"Part Number": "P1", "FG Counts": {"F1": 10}, "EAU Volumes": {}, "Proto Qty": 5}]
    wb = Workbook()
    bm.build_bom_matrix_sheet(wb, rows, {}, {})  # must not raise
