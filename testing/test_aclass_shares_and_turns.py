"""
SPEC-017 bugs (reports/aclass_parts.py):
- total_ext_price added a CPN once per assembly it appears in, so the shares over the sheet did
  not total 100%. The total must add each CPN once.
- MOQ turns used total part qty in the JSON, but the sheet's formula is Ext Vol / MOQ. The JSON
  follows the sheet (default chosen in SPEC-017).
"""
import os
import sys

SUP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mcp-tools", "reporting", "superset"))


def _aclass(scrub_items, rfqs):
    sys.path.insert(0, SUP)
    try:
        import reports.aclass_parts as ap
    finally:
        sys.path.remove(SUP)
    return ap.aclass_parts({"bom_details_json_data": scrub_items, "bom_data": [], "rfqs": rfqs, "suppliers": []})


def test_repeated_cpn_is_counted_once_in_the_total():
    items = [
        {"CPN": "Q1", "FG": "F1", "Assembly": "A", "Quantity": 1, "MPN": "m"},
        {"CPN": "Q1", "FG": "F1", "Assembly": "B", "Quantity": 1, "MPN": "m"},
    ]
    rfqs = [{"cpn": "Q1", "is_L1": True, "vol_pricing": 1.0, "total_part_qty": 10, "vol_qty": 10,
             "vol_moq": 1, "currency": "USD", "volume_no": "1"}]
    rows = _aclass(items, rfqs)
    assert rows, "no rows"
    assert "100.00%" in repr(rows[0]), rows[0]


def test_moq_turns_use_vol_qty_over_moq_like_the_sheet():
    items = [{"CPN": "Q2", "FG": "F1", "Assembly": "A", "Quantity": 1, "MPN": "m"}]
    rfqs = [{"cpn": "Q2", "is_L1": True, "vol_pricing": 1.0, "total_part_qty": 100, "vol_qty": 10,
             "vol_moq": 5, "currency": "USD", "volume_no": "1"}]
    rows = _aclass(items, rfqs)
    assert "2.00" in repr(rows[0]) and "20.00" not in repr(rows[0]), rows[0]
