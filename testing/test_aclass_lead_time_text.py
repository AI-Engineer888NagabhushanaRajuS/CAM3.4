"""
SPEC-017 bug (reports/aclass_parts.py): lead_times passed straight to float(), so a range such
as "4-6 weeks" raised ValueError and aborted the A CLASS PARTS sheet. A non-numeric lead time
must come through as its text.
"""
import os
import sys

SUP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mcp-tools", "reporting", "superset"))


def _aclass(lead_times):
    sys.path.insert(0, SUP)
    try:
        import reports.aclass_parts as ap
    finally:
        sys.path.remove(SUP)
    payload = {
        "bom_details_json_data": [{"CPN": "C1", "FG": "F1", "Assembly": "A1", "Quantity": 2, "MPN": "m"}],
        "bom_data": [],
        "rfqs": [{"cpn": "C1", "is_L1": True, "vol_pricing": 5.0, "vol_moq": 1, "vol_qty": 10,
                  "lead_times": lead_times, "currency": "USD", "volume_no": "1"}],
        "suppliers": [],
    }
    return ap.aclass_parts(payload)


def test_numeric_lead_time_is_formatted():
    rows = _aclass(4)
    assert rows and "4.00" in repr(rows[0]), rows


def test_range_lead_time_does_not_crash_and_keeps_its_text():
    rows = _aclass("4-6 weeks")
    assert rows and "4-6 weeks" in repr(rows[0]), rows
