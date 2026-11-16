"""The CBOM line model (mcp-tools/reporting/superset/reports/report_model.py): required fields, strict types, cross-field totals.
A bad line must be reported, never silently written: missing quantity, text where a number is needed, invalid price, wrong total."""
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mcp-tools", "reporting", "superset")))
from reports import report_model as rm  # noqa: E402


def good(**kw):
    line = {"rfq_id": "RFQ-1", "volume_no": "1", "fg": "FG", "cpn": "R1", "part_qty": 2.0, "volume_qty": 1500.0, "ext_vol_qty": 3000.0,
            "final_price_conv": 0.5, "final_price_original": 0.5, "final_currency_original": "USD"}
    line.update(kw)
    return line


def test_a_valid_line_passes():
    assert rm.violations(pd.DataFrame([good()])) == []


@pytest.mark.parametrize("bad, expect", [
    ({"part_qty": None}, "part_qty"),                       # missing quantity
    ({"part_qty": 0.0}, "part_qty"),                        # a part line with no quantity
    ({"final_price_conv": -1.0}, "final_price_conv"),       # invalid (negative) price
    ({"final_price_original": 0.5, "final_currency_original": None}, "currency"),   # a price with no currency
    ({"cpn": None}, "cpn"),                                 # no part number
])
def test_a_bad_line_is_reported_with_its_field(bad, expect):
    found = rm.violations(pd.DataFrame([good(**bad)]))
    assert found, bad
    assert any(expect in v["message"] for v in found), found


def test_strict_mode_refuses_text_where_a_number_is_needed():
    found = rm.violations(pd.DataFrame([good(part_qty="2")]))
    assert found and any("part_qty" in v["message"] for v in found)


def test_an_empty_cbom_is_a_violation_not_an_empty_success():
    found = rm.violations(pd.DataFrame([]))
    assert found and found[0]["message"] == "no CBOM lines to write"


def test_the_extended_volume_rule_is_not_enforced_until_its_approved_rule_is_known():
    """RFQ-000032's real rows follow packing / MOQ rounding, so part qty x volume qty is not the rule: it must not block a release."""
    assert rm.violations(pd.DataFrame([good(ext_vol_qty=3200.0, volume_qty=1500.0, part_qty=26.0)])) == []
