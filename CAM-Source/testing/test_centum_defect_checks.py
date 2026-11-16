"""Checks behind the Centum reported defects (testing/centum_case_register.json), run on the delivered workbook of RFQ-000032.

Each test names the Centum case IDs it covers in its docstring, and only the cases whose expected result it really states. The workbook is the
one the app delivers (acceptance_evidence/spec019/create-rfq/RFQ-000032-report.xlsx, a copy of the export); set CAM_CHECK_WORKBOOK to test another one.
Cases a check on this single RFQ cannot show (other RFQs, other volumes, proto input) stay not_tested in the register.
"""
import json
import os

import openpyxl
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT = os.path.join(HERE, "..", "..", "acceptance_evidence", "spec019", "create-rfq", "RFQ-000032-report.xlsx")
WORKBOOK = os.environ.get("CAM_CHECK_WORKBOOK", DEFAULT)
TOL = 1e-6
CBOM_TABS = ("7.0 CBOM VL-1", "7.0 CBOM VL-2")
# 7.0 CBOM columns (0-based): 2 part number, 5 mfg name, 8 part qty, 9 ext vol qty, 10 price conv, 11 price original, 12 currency, 13 ext price, 14 ext vol price
PART, MFR, QTY, EXT_QTY, PRICE, PRICE_ORIG, CURRENCY, EXT_PRICE, EXT_VOL_PRICE = 2, 5, 8, 9, 10, 11, 12, 13, 14


@pytest.fixture(scope="module")
def book():
    if not os.path.exists(WORKBOOK):
        pytest.skip(f"no workbook at {WORKBOOK}")
    return openpyxl.load_workbook(WORKBOOK, data_only=True)


def rows_of(ws, first=25):
    """The part lines of a CBOM tab: skips repeated header rows and the assembly lines (their part is the assembly code)."""
    for r in ws.iter_rows(min_row=first, values_only=True):
        if r[0] is None or r[PART] in (None, "Part Number") or r[PART] == r[1] or str(r[PART]).endswith("_PCBA"):
            continue   # an assembly line (its code ends in _PCBA, its price is the assembly total): it has no manufacturer of its own
        yield r


def test_extended_prices_are_quantity_times_price(book):
    """Covers CAM-006, CAM-010, CAM-027, CAM-197: an extended price is part qty x price (conv.), an extended volume price is ext volume qty x price."""
    for tab in CBOM_TABS:
        for r in rows_of(book[tab]):
            price = r[PRICE]
            if not isinstance(price, (int, float)):
                continue
            assert r[EXT_PRICE] == pytest.approx(r[QTY] * price, abs=TOL), (tab, r[PART])
            assert r[EXT_VOL_PRICE] == pytest.approx(r[EXT_QTY] * price, abs=TOL), (tab, r[PART])


def test_summary_cost_per_set_is_the_assembly_total_the_cbom_tab_shows(book):
    """Covers CAM-129, CAM-132, CAM-160, CAM-165: the Summary's cost per set for each assembly equals the assembly total on the 7.0 CBOM VL-1 tab
    (the Summary formula reads that cell), and the tab's TOTAL is the sum of its assemblies."""
    cbom = book["7.0 CBOM VL-1"]
    block = {}
    for r in cbom.iter_rows(min_row=1, max_row=24, values_only=True):
        if r[2] in ("HCV_BMS_MB", "HCV_BMS_SB") and isinstance(r[4], (int, float)):
            block[r[2]] = r[4]
        if r[2] == "TOTAL" and isinstance(r[4], (int, float)):
            total = r[4]
    summary = {r[2]: r[4] for r in book["Summary"].iter_rows(values_only=True) if r[2] in block and isinstance(r[4], (int, float))}
    assert set(summary) == set(block) == {"HCV_BMS_MB", "HCV_BMS_SB"}
    for assembly in block:
        assert summary[assembly] == pytest.approx(block[assembly], abs=1e-6), assembly
    assert total == pytest.approx(sum(block.values()), abs=1e-6)


def test_no_proto_is_shown_when_the_rfq_has_no_proto(book):
    """Covers CAM-001, CAM-031, CAM-035, CAM-052, CAM-061 for an RFQ with no proto volume (RFQ-000032 has none): no 'Proto' in the Summary or the CBOM tabs."""
    for name in ("Summary", "7.0 CBOM VL-1", "7.0 CBOM VL-2", "BOM MATRIX"):
        for row in book[name].iter_rows(values_only=True):
            for v in row:
                if isinstance(v, str):
                    assert "proto" not in v.lower(), (name, v[:60])


def test_every_costed_row_carries_its_manufacturer(book):
    """Covers CAM-003 for the RFQ's QuoteWin manufacturers: a costed row has a manufacturer name."""
    for r in rows_of(book["7.0 CBOM VL-1"]):
        if isinstance(r[PRICE], (int, float)):
            assert r[MFR] not in (None, ""), r[PART]


def test_an_original_price_has_its_currency(book):
    """Covers CAM-220: a price in the original currency always comes with its currency."""
    for tab in CBOM_TABS:
        for r in rows_of(book[tab]):
            if isinstance(r[PRICE_ORIG], (int, float)):
                assert r[CURRENCY] not in (None, ""), r[PART]


def test_the_workbook_has_no_error_cells(book):
    """Covers CAM-189: the Manifest counts Excel error values in every tab; the count must be zero."""
    manifest = book["Manifest"]
    count = next(r[1] for r in manifest.iter_rows(values_only=True) if r[0] == "Error cells (all tabs)")
    assert count == 0


def test_every_part_has_a_quantity_above_zero(book):
    """Covers CAM-181, CAM-182, CAM-183, CAM-184: a part in the inputs with a quantity is not carried as zero."""
    for tab in CBOM_TABS:
        for r in rows_of(book[tab]):
            assert isinstance(r[QTY], (int, float)) and r[QTY] > 0, (tab, r[PART])


def test_the_summary_volumes_are_the_volumes_of_the_cbom(book):
    """Covers CAM-002, CAM-026, CAM-168, CAM-210 for this RFQ: the Summary's volume figure is the volume the CBOM was built on (ext volume qty / part qty)."""
    summary = book["Summary"]
    head = next(r for r in summary.iter_rows(values_only=True) if r[2] == "Assembly")
    assert head[3] == "Volume-1" and head[5] == "Volume-2"
    shown = {r[2]: (r[3], r[5]) for r in summary.iter_rows(values_only=True) if r[2] in ("HCV_BMS_SB", "HCV_BMS_MB")}
    assert shown
    for assembly, (vol1, vol2) in shown.items():
        for tab, shown_volume in (("7.0 CBOM VL-1", vol1), ("7.0 CBOM VL-2", vol2)):
            for r in rows_of(book[tab]):
                if r[0] == assembly:
                    assert r[EXT_QTY] == pytest.approx(r[QTY] * shown_volume, abs=TOL), (tab, assembly, r[PART])
