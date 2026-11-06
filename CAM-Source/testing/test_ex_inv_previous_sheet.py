"""
SPEC-017 bug (reports/ex_inv_vl.py): the previous-volume delta formulas (AH/AI) always assumed
the previous sheet exists. For volume 2 of an RFQ with no volume 1, they referenced 'Ex Inv VL-1',
a sheet that is not in the workbook. The exporter now says whether the previous sheet exists, and
the delta formulas are left out when it does not.
"""
import os
import sys

from openpyxl import Workbook

SUP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mcp-tools", "reporting", "superset"))


def test_no_delta_formula_when_previous_volume_sheet_is_absent():
    sys.path.insert(0, SUP)
    try:
        import reports.ex_inv_vl as ex
    finally:
        sys.path.remove(SUP)
    payload = [{"CPN": "CPN-2001", "commodity": "Passive", "part_description": "R", "part_qty": 1,
                "volumes": [{"volume": 2, "excess_in_stk": 30}]}]
    wb = Workbook()
    ws = ex.build_ex_inv_vl_sheet(wb, payload, 2, cbom_bounds=(18, 400), has_proto=False,
                                  previous_sheet_exists=False)
    assert not str(ws["AH5"].value or "").startswith("="), ws["AH5"].value  # no formula to a missing sheet
