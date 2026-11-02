"""
SPEC-017 bug (reports/revision_history.py): max_volume was the COUNT of volumes per revision,
not the highest volume number. A CPN whose only volume is 2 got max_volume 1, so V2 never
appeared. The sheet header must include a V2 column for it.
"""
import os
import sys

from openpyxl import Workbook

SUP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mcp-tools", "reporting", "superset"))


def test_volume_two_only_gets_a_v2_column():
    sys.path.insert(0, SUP)
    try:
        import reports.revision_history as rh
    finally:
        sys.path.remove(SUP)
    bom = [{"CPN": "A", "Assembly": "F1", "FG": "F1", "Commodity": "IC", "Description": "d",
            "MFR": "m", "MPN": "m", "Quantity": 1}]
    rfqs = [
        {"cpn": "A", "MPN": "m", "revision_no": 1, "volume_no": "2", "vol_qty": 100, "vol_pricing": 5.0,
         "currency": "USD", "is_L1": True},
        {"cpn": "A", "MPN": "m", "revision_no": 2, "volume_no": "2", "vol_qty": 200, "vol_pricing": 6.0,
         "currency": "USD", "is_L1": True},
    ]
    rows = rh.revision_history_rows({"centum_id": "C", "bom_data": bom, "rfqs": rfqs})
    wb = Workbook()
    rh.build_revision_history_sheet(wb, rows, {2: (1, 2)}, {"Ex Inv VL-2": 2})
    ws = wb[wb.sheetnames[-1]]
    headers = {str(c.value) for row in ws.iter_rows() for c in row if c.value}
    assert "V2 OLD System QTY" in headers, sorted(h for h in headers if h.startswith("V"))
