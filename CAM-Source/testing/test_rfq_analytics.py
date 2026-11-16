"""The Reports & Analytics numbers come from the delivered workbook, in the exporter's fixed layouts (mcp-tools/shared/rfq_analytics.py)."""
import openpyxl

import rfq_analytics


def _book(path, final_buy=100.0, buy=80.0, currency="USD", with_notes=True):
    wb = openpyxl.Workbook()
    s = wb.active
    s.title = "Summary"
    s.append(["CBOM Summary"])
    s.append([None, None, None, "RFQ-1, Rev-0"])
    s.append([None, None, "Assembly", "Volume-1", "CBOM Cost VL-1", "Volume-2", "CBOM Cost VL-2"])
    s.append([None, None, "FG_A", 100, 66.5, 200, 65.5])
    s.append([None, None, "FG_B", 100, 60.0, 200, 61.0])
    s.append([None, None, None, None, 126.5, None, 126.5])
    s.append([None, None, "Ext Vol Conv Price", None, 1000.0, None, 2000.0])
    s.append([None, None, "MOQ Cost", None, 50.0, None, 60.0])
    pc = wb.create_sheet("Price Control")
    pc.append(["Price Control", "Sum of Ext Price", "Sum of Ext Vol Cost", "In %"])
    pc.append(["Centum", 80.0, 800.0, 0.8])
    pc.append(["CONTRACT", 20.0, 200.0, 0.2])
    pc.append(["Grand Total", 100.0, 1000.0, None])
    if with_notes:
        mn = wb.create_sheet("Missing Notes")
        mn.append(["1. Uncosted Parts"])
        mn.append(["Sl.no", "Part Number"])
        mn.append([1, "P1"])
        mn.append([2, "P2"])
        mn.append([None, None])
        mn.append(["2. MPN Mismatch with BOM"])
        mn.append(["Sl.no", "Part Number"])
        mn.append([1, "P3"])
        mn.append([None, None])
        mn.append(["5. EOL"])
        mn.append(["Sl.no", "Part Number"])
        mn.append([1, "P9"])
        mn.append([2, "P10"])
        mn.append([3, "P11"])
    mf = wb.create_sheet("Manifest")
    mf.append(["Error cells (all tabs)", 0])
    mf.append(["Go / no-go", "GO"])
    cf = wb.create_sheet("Batchwise Cashflow")
    for _ in range(2):                                # one block per volume; the last volume is the one the portfolio uses
        cf.append(["Payment term detail"])
        cf.append(["Supplier Type", "Sum of Buy value", "Sum of Final buy value"])
        cf.append(["30 Days", buy, final_buy])
        cf.append(["Grand Total", buy, final_buy])
    lt = wb.create_sheet("Lead Time Consolidated")
    lt.append(["LT in weeks", "Count of Part Number", "In %"])
    lt.append([None, 5, 0.1])                         # no lead time
    lt.append([6, 10, 0.2])
    lt.append([12, 20, 0.4])
    lt.append([30, 15, 0.3])
    lt.append(["Grand Total", 50, 1])
    cb = wb.create_sheet("7.0 CBOM VL-2")
    cb.append([None, None, "Awards Costed BOM", None, None, None, None, None, None, "Currency", "Value", None, "Quote Currency", currency])
    ex = wb.create_sheet("Ex Inv VL-2")
    ex.append(["Excess Cost #2"])
    ex.append([42.5])
    wb.save(path)


def test_the_numbers_are_read_from_the_workbook_in_the_exporters_layout(tmp_path):
    p = tmp_path / "r.xlsx"
    _book(p)
    a = rfq_analytics.analytics(p)
    assert a["summary"]["volumes"] == ["VL-1", "VL-2"]
    assert a["summary"]["fgs"] == [{"assembly": "FG_A", "VL-1": 66.5, "VL-2": 65.5}, {"assembly": "FG_B", "VL-1": 60.0, "VL-2": 61.0}]
    assert a["summary"]["totals"] == {"VL-1": 126.5, "VL-2": 126.5}
    assert a["summary"]["ext_vol_conv_price"] == {"VL-1": 1000.0, "VL-2": 2000.0}
    assert [(x["label"], x["pct"]) for x in a["price_control"]] == [("Centum", 0.8), ("CONTRACT", 0.2)]
    assert a["uncosted_parts"] == 2
    assert a["exceptions"] == {"uncosted": 2, "mpn_mismatch": 1, "eol": 3}
    assert a["currency"] == "USD" and a["cashflow_totals"] == [{"buy": 80.0, "final_buy": 100.0}] * 2
    assert a["manifest"] == {"error_cells": 0.0, "go_no_go": "GO"}


def test_a_tab_that_is_not_there_is_none_never_a_guess(tmp_path):
    p = tmp_path / "r.xlsx"
    _book(p, with_notes=False)
    a = rfq_analytics.analytics(p)
    assert a["exceptions"] is None and a["uncosted_parts"] is None and a["cbom"] is None


def test_the_portfolio_totals_equal_the_sum_of_the_per_rfq_figures(tmp_path):
    items = []
    for i, (final, buy) in enumerate([(100.0, 80.0), (300.0, 200.0), (50.0, 50.0)], start=1):
        p = tmp_path / f"r{i}.xlsx"
        _book(p, final_buy=final, buy=buy)
        items.append({"rfq_id": f"RFQ-{i}", "customer": "C", "project": "P", "path": str(p), "generated": "2026-11-11T00:00:00"})
    out = rfq_analytics.portfolio(items)
    t, rows = out["totals"], out["rfqs"]
    assert t["total_rfqs"] == 3 and t["cash_rfqs"] == 3 and [r["rfq_id"] for r in rows] == ["RFQ-3", "RFQ-2", "RFQ-1"]
    assert t["final_buy"] == sum(r["final_buy"] for r in rows) == 450.0 and t["buy"] == sum(r["buy"] for r in rows) == 330.0
    assert t["buy_variance"] == (450.0 - 330.0) / 330.0
    assert t["critical_exceptions"] == sum(r["critical"] for r in rows) == 18          # 2 + 1 + 3 per RFQ
    assert t["excess_cost"] == 3 * 42.5
    assert t["lead_time"] == {"up to 8 weeks": 30, "9 to 16 weeks": 60, "17 to 26 weeks": 0, "over 26 weeks": 45, "no lead time": 15}
    assert all(r["volume"] == "VL-2" and r["currency"] == "USD" for r in rows)


def test_rfqs_in_another_currency_are_counted_apart_never_added_in(tmp_path):
    items = []
    for i, cur in enumerate(["USD", "USD", "EUR"], start=1):
        p = tmp_path / f"r{i}.xlsx"
        _book(p, currency=cur)
        items.append({"rfq_id": f"RFQ-{i}", "path": str(p)})
    t = rfq_analytics.portfolio(items)["totals"]
    assert t["currency"] == "USD" and t["counted_rfqs"] == 2 and t["other_currency_rfqs"] == 1 and t["final_buy"] == 200.0


def test_an_old_export_without_stored_cash_values_is_flagged_not_counted_as_zero(tmp_path):
    p = tmp_path / "old.xlsx"
    _book(p)
    wb = openpyxl.load_workbook(p)
    ws = wb["Batchwise Cashflow"]
    for row in ws.iter_rows():
        for c in row:
            if isinstance(c.value, (int, float)):
                c.value = None                           # what an export looks like when its formulas never had a stored value
    cb = wb.create_sheet("CBOM")
    cb.append(["final_price_conv"])
    cb.append([1.0])
    wb.save(p)
    out = rfq_analytics.portfolio([{"rfq_id": "RFQ-OLD", "path": str(p)}])
    assert out["rfqs"][0]["needs_values"] is True and out["rfqs"][0]["final_buy"] is None
    assert out["totals"]["without_stored_values"] == 1 and out["totals"]["final_buy"] == 0


def test_a_report_with_stored_cash_values_but_no_go_no_go_row_is_not_asked_for_repair(tmp_path):
    p = tmp_path / "nov5.xlsx"
    _book(p)                                                 # stored cash values, and a Manifest tab without the "Go / no-go" row (exports before 5 Nov)
    wb = openpyxl.load_workbook(p)
    if "Manifest" in wb.sheetnames:
        del wb["Manifest"]
    wb.create_sheet("Manifest").append(["Field", "Value"])
    cb = wb.create_sheet("CBOM")
    cb.append(["final_price_conv"])
    cb.append([1.0])
    wb.save(p)
    out = rfq_analytics.portfolio([{"rfq_id": "RFQ-N5", "path": str(p)}])
    assert out["rfqs"][0]["go_no_go"] is None and out["rfqs"][0]["needs_values"] is False
    assert out["totals"]["without_stored_values"] == 0


def test_a_workbook_that_cannot_be_read_is_listed_with_its_error(tmp_path):
    bad = tmp_path / "bad.xlsx"
    bad.write_bytes(b"not a workbook")
    out = rfq_analytics.portfolio([{"rfq_id": "RFQ-X", "path": str(bad)}])
    assert out["rfqs"][0]["error"] and out["totals"]["errors"] == 1 and out["totals"]["total_rfqs"] == 0


def test_commodity_excess_adds_up_to_the_ex_inv_tab_total(tmp_path):
    """Net Excess Cost per commodity (last volume's Ex Inv tab) must sum to that tab's own Excess Cost total; each volume reads its own column."""
    wb = openpyxl.Workbook()
    wb.active.title = "Summary"
    for n, rows in ((1, [("PASSIVE", 6.0), ("ACTIVE", 4.0)]), (2, [("PASSIVE", 5.0), ("", 0.0), ("ACTIVE", 9.0)])):
        ws = wb.create_sheet(f"Ex Inv VL-{n}")
        ws.append([f"Excess Cost #{n}"])
        ws.append([sum(v for _, v in rows if _)])
        ws.append([])
        ws.append(["Part Number", "Commodity", f"Net Excess Cost #{n}"])
        for i, (commodity, value) in enumerate(rows):
            ws.append([f"P{i}", commodity or None, value])
    path = str(tmp_path / "book.xlsx")
    wb.save(path)
    got = rfq_analytics._commodity_excess(openpyxl.load_workbook(path, data_only=True, read_only=True))
    assert got["VL-1"] == {"PASSIVE": 6.0, "ACTIVE": 4.0}
    assert sum(got["VL-2"].values()) == 14.0
    assert got["VL-2"]["ACTIVE"] == 9.0
