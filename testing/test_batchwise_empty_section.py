"""
SPEC-017 bug (reports/batchwise_cashflow.py): a volume section with no supplier types gave the
Grand Total the reversed range SUM(B{h+1}:B{h}), which covers the total cell itself (a
circular reference once Excel normalises the range). An empty section must total to 0.
Checked with openpyxl (no Excel needed to see the formula text).
"""
import os
import sys

from openpyxl import Workbook

SUP = os.path.join(os.path.dirname(__file__), "..", "mcp-tools", "reporting", "superset")


def test_empty_section_total_does_not_reference_itself():
    sys.path.insert(0, os.path.abspath(SUP))
    try:
        import reports.batchwise_cashflow as bc
    finally:
        sys.path.remove(os.path.abspath(SUP))
    wb = Workbook()
    bc.build_batchwise_cashflow_sheet(wb, {"1": {}}, {"Ex Inv VL-1": 200}, include_proto=False)
    ws = wb[wb.sheetnames[-1]]
    totals = [c.value for row in ws.iter_rows() for c in row if isinstance(c.value, str) and c.value.startswith("=SUM(")]
    for formula in totals:
        start, end = formula[len("=SUM("):-1].split(":")
        assert int("".join(ch for ch in start if ch.isdigit())) <= int("".join(ch for ch in end if ch.isdigit())), formula
