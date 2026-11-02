"""
SPEC-017 bug (reports/summary.py): the price lookup was keyed cpn|volume with no revision, so
every revision read the last RFQ row written for that key. Revision 0 must not change when a
later revision exists.
"""
import os
import sys

SUP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mcp-tools", "reporting", "superset"))


def _summary(rfqs):
    sys.path.insert(0, SUP)
    try:
        import reports.summary as sm
    finally:
        sys.path.remove(SUP)
    bom = [{"FG": "F1", "Assembly": "F1", "CPN": "A", "Quantity": 10, "inventory_stock": 0}]
    return sm.summary({"centum_id": "C", "bom_data": bom, "rfqs": rfqs, "fgcounts": []})


def _rfq(rev, price, moq):
    return {"cpn": "A", "revision_no": rev, "volume_no": "1", "currency": "USD",
            "vol_pricing": price, "vol_moq": moq, "vol_qty": 10, "proto_pricing": 0, "package_qty": 1}


def test_revision_zero_is_unaffected_by_revision_one():
    rev0 = _rfq(0, 1.0, 100)
    rev1 = _rfq(1, 2.0, 500)
    alone = _summary([rev0])
    both = _summary([rev0, rev1])
    assert alone and both
    assert both[0] == alone[0], "revision 0 changed when revision 1 was added"


def test_assembly_rows_are_matched_by_name_across_revisions():
    """Revision 1 contains only F2. The F1 row must not show F2's quantity (99) in revision 1."""
    sys.path.insert(0, SUP)
    try:
        import reports.summary as sm
        from openpyxl import Workbook
    finally:
        sys.path.remove(SUP)
    bom = [
        {"FG": "F1", "Assembly": "F1", "CPN": "A", "Quantity": 10, "inventory_stock": 0},
        {"FG": "F2", "Assembly": "F2", "CPN": "B", "Quantity": 99, "inventory_stock": 0},
    ]
    rfqs = [
        {"cpn": "A", "revision_no": 0, "volume_no": "1", "currency": "USD", "vol_pricing": 1.0,
         "vol_moq": 1, "vol_qty": 10, "proto_pricing": 0, "package_qty": 1},
        {"cpn": "B", "revision_no": 0, "volume_no": "1", "currency": "USD", "vol_pricing": 1.0,
         "vol_moq": 1, "vol_qty": 99, "proto_pricing": 0, "package_qty": 1},
        {"cpn": "B", "revision_no": 1, "volume_no": "1", "currency": "USD", "vol_pricing": 1.0,
         "vol_moq": 1, "vol_qty": 99, "proto_pricing": 0, "package_qty": 1},
    ]
    json_data = sm.summary({"centum_id": "C", "bom_data": bom, "rfqs": rfqs, "fgcounts": []})
    wb = Workbook()
    sm.build_summary_sheet(wb, json_data, {}, include_proto=False)
    ws = wb[wb.sheetnames[-1]]
    f1_values = [c.value for row in ws.iter_rows() for c in row if row and row[2].value == "F1" for c in row]
    assert 99 not in f1_values, f1_values
