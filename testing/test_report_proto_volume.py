"""
SPEC-017 bugs (reporting): RFQ rows carry volume_no "proto" alongside numbered volumes.
- price_control: int("proto") raised ValueError, aborting the report for any prototype RFQ.
- sum_and_count: "Proto" coverage was true when ANY RFQ (any volume) shared the CPN.
Modules are imported from the superset folder (their own config/db resolve there).
"""
import os
import sys

SUP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mcp-tools", "reporting", "superset"))


def _import(name):
    sys.path.insert(0, SUP)
    try:
        return __import__(f"reports.{name}", fromlist=["x"])
    finally:
        sys.path.remove(SUP)


def test_price_control_does_not_crash_on_proto_rfq():
    pc = _import("price_control")
    payload = {
        "rfqs": [
            {"cpn": "X1", "is_L1": True, "volume_no": "proto", "price_control": "Centum",
             "vol_pricing": 1.0, "currency": "USD"},
            {"cpn": "X1", "is_L1": True, "volume_no": "1", "price_control": "Centum",
             "vol_pricing": 1.0, "currency": "USD"},
        ],
        "fgcounts": [],
        "bom_data": [],
    }
    pc.price_control(payload)  # must not raise


def test_sum_and_count_proto_requires_a_proto_rfq_not_any_volume():
    sc = _import("sum_and_count")
    items = [{"Assembly": "A1", "CPN": "P1", "Quantity": 5}]
    rfqs = [{"cpn": "P1", "volume_no": "1"}]  # shares the CPN, but it is volume 1, not proto
    rows = sc.sum_and_count({"scrub_bom_items": items, "rfqs": rfqs})
    assert rows and rows[0]["Assembly"] == "A1"
    assert rows[0]["Proto Sum"] == 0 and rows[0]["Proto Count"] == 0, rows[0]



def test_price_control_json_puts_cnp_with_customer_like_the_sheet():
    """The sheet's CNP row sums CNP and CUSTOMER together, so the JSON must bucket CNP as Customer."""
    pc = _import("price_control")
    payload = {
        "rfqs": [{"cpn": "X1", "is_L1": True, "volume_no": "1", "price_control": "CNP",
                  "vol_pricing": 1.0, "currency": "USD"}],
        "fgcounts": [{"fg": "F1", "volume_no": "1", "count": 2}],
        "bom_data": [{"FG": "F1", "Assembly": "F1", "CPN": "X1", "Quantity": 2, "Commodity": "IC",
                      "Description": "d", "MPN": "m"}],
    }
    out = pc.price_control(payload)
    assert out["Customer"]["sum_ext_price"] > 0, out
    assert out["Centum"]["sum_ext_price"] == 0, out
