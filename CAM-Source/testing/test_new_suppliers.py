"""The New Suppliers rule: an awarded supplier missing from the supplier master is new (RE 4 Domain 1/3)."""
import os
import sys

import openpyxl

NS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mcp-tools", "reporting", "superset"))
sys.path.insert(0, NS_DIR)
from reports.new_suppliers import load_supplier_master, new_supplier_rows, build_new_suppliers_sheet  # noqa: E402

CBOM = [
    {"final_supp_name": "Avnet", "cpn": "C1", "volume_no": "1", "ext_part_vol_price_conv": 10.0},
    {"final_supp_name": "Avnet", "cpn": "C2", "volume_no": "1", "ext_part_vol_price_conv": 5.0},
    {"final_supp_name": "Acme New Co", "cpn": "C3", "volume_no": "2", "ext_part_vol_price_conv": 7.5},
    {"final_supp_name": None, "cpn": "C4", "volume_no": "1", "ext_part_vol_price_conv": 99.0},
    {"final_supp_name": float("nan"), "cpn": "C5", "volume_no": "1", "ext_part_vol_price_conv": 1.0},
]


def test_a_supplier_missing_from_the_master_is_new(tmp_path):
    master_file = tmp_path / "master.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Supplier"
    ws.append(["Supplier ID", "Name"])
    ws.append(["S1", "AVNET"])
    wb.save(master_file)
    names = load_supplier_master(str(master_file))
    rows = {r["supplier"]: r for r in new_supplier_rows(CBOM, ["1", "2"], names)}
    assert rows["Avnet"]["status"] == "In master"
    assert rows["Acme New Co"]["status"] == "New"
    assert rows["Avnet"]["spend"]["1"] == 15.0 and rows["Acme New Co"]["spend"]["2"] == 7.5
    assert set(rows) == {"Avnet", "Acme New Co"}, "blank and NaN suppliers are skipped"


def test_without_a_master_nothing_is_confirmed_new(tmp_path):
    assert load_supplier_master(str(tmp_path / "missing.xlsx")) is None
    rows = new_supplier_rows(CBOM, ["1", "2"], None)
    assert {r["status"] for r in rows} == {"No master"}
    wb = openpyxl.Workbook()
    build_new_suppliers_sheet(wb, rows, ["1", "2"], master_provided=False)
    assert wb["New Suppliers"]["A1"].value == "Supplier"
