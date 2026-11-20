"""SPEC-022: what a released workbook is, read from its contents. Fixtures mirror the four real Centum inputs."""
import os
import sys

import openpyxl
import pytest

FR_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "fastapi-router"))
sys.path.insert(0, FR_DIR)
import attachment_roles as ar  # noqa: E402


def book(path, sheets):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
    wb.save(path)
    return str(path)


def test_scrub_bom_workbook_is_recognised_by_its_sheet_name_ignoring_case_and_spaces(tmp_path):
    p = book(tmp_path / "a.xlsx", {" scrub bom ": [["FG", "CPN"], ["X", "Y"]], "Settings": [["FG", "V1 Qty"]], "Batch": [["FG"]]})
    r = ar.classify_file(p)
    assert r["role"] == "scrub_bom" and not r["problems"] and "Settings / Batch" in r["role_reason"]
    r2 = ar.classify_file(book(tmp_path / "b.xlsx", {"SCRUB BOM": [["FG"]]}))
    assert r2["role"] == "scrub_bom" and "QuoteWin awards" in r2["role_reason"] and r2["volume_source"] == "quotewin"


def test_plain_bom_is_recognised_but_flagged_because_the_first_step_would_reject_it(tmp_path):
    p = book(tmp_path / "bom.xlsx", {"BOM": [["CPN", "Description", "MPN", "Commodity", "Quantity", "UOM", "VL 1"], ["A", "B", "C", "D", 1, "NUM", 10]]})
    r = ar.classify_file(p)
    assert r["role"] == "bom"
    assert "SCRUB BOM" in r["problems"][0] and "invalid input" in r["problems"][0] and "sheets: BOM" in r["problems"][0]


def test_volume_file_has_part_and_volume_columns_only(tmp_path):
    r = ar.classify_file(book(tmp_path / "v.xlsx", {"Sheet1": [["CPN", "Description", "MPN", "Vl1"], ["U1", "H", "U1", 200]]}))
    assert r["role"] == "volume"


def test_quotewin_is_found_by_the_table_header_below_the_report_preamble(tmp_path):
    rows = [["Awards Part Number List"], ["Template:", "x"]] + [["k", "v"]] * 8 + [["*** Assembly Summary"], ["Part Number", "Mfg Part Number", "Commodity", "Cost #1"]]
    r = ar.classify_file(book(tmp_path / "q.xlsx", {"Sheet0": rows}))
    # The QuoteWin is a required input of RFQ creation (the intake buckets), so no "belongs to another step" problem any more.
    assert r["role"] == "quotewin" and r["problems"] == []


def test_a_costing_sheet_is_not_a_quotewin(tmp_path):
    """All 25 Centum costing sheets share Part Number / Mfg Part Number / Commodity with the QuoteWin, but carry Price Control and NRE
    Charge and no Awarded Volume. They were labelled QuoteWin (2026-11-19, batch-05 in the real UI)."""
    head = ["Project", "Part Number", "Description", "Commodity", "Mfg Name", "Mfg Part Number", "Unit", "Part Qty", "Price #1 (Original)",
            "Currency (Original)", "Supp Name", "Pkg Qty", "MOQ", "Lead Time", "NRE Charge", "NRE Charge (Conv.)", "NCNR", "Price Control"]
    r = ar.classify_file(book(tmp_path / "c.xlsx", {"Sheet3": [head, ["P", "A1", "d", "RES"] + [None] * 14]}))
    assert r["role"] == "costing" and r["role_label"] == "Costing sheet"
    qw = ["Part Number", "Mfg Part Number", "Commodity", "Cost #1 (Conv.)", "Awarded Volume #1", "Award #1", "Price Control"]
    assert ar.classify_file(book(tmp_path / "q2.xlsx", {"Sheet0": [qw]}))["role"] == "quotewin"


def test_a_scrub_bom_says_where_its_volumes_come_from(tmp_path):
    head = [["FG", "Level", "Assembly", "CPN", "MPN", "Quantity"]]
    with_settings = ar.classify_file(book(tmp_path / "a.xlsx", {"SCRUB BOM": head, "Settings": [["FG", "V1 Qty"]]}))
    without = ar.classify_file(book(tmp_path / "b.xlsx", {"SCRUB BOM": head, "Sheet1": [["x"]]}))
    assert with_settings["volume_source"] == "settings"
    assert without["volume_source"] == "quotewin" and "QuoteWin awards" in without["role_reason"]


def test_anything_else_is_unknown_and_never_guessed_as_costing_sheet(tmp_path):
    r = ar.classify_file(book(tmp_path / "x.xlsx", {"Costing": [["Item", "Rate", "Hours"], ["a", 1, 2]]}))
    assert r["role"] == "unknown" and "BOM, volume or QuoteWin" in r["role_reason"]


def test_csv_and_documents_and_unreadable_files_never_raise(tmp_path):
    c = tmp_path / "bom.csv"
    c.write_text("CPN,MPN,Quantity\nA,B,1\n", encoding="utf-8")
    assert ar.classify_file(str(c))["role"] == "bom"
    t = tmp_path / "notes.txt"
    t.write_text("hello", encoding="utf-8")
    assert ar.classify_file(str(t))["role"] == "document"
    bad = tmp_path / "broken.xlsx"
    bad.write_bytes(b"not a workbook")
    r = ar.classify_file(str(bad))
    assert r["role"] == "unknown" and "Could not read" in r["role_reason"]


REAL = "C:/CAM[3.4]-RFQ_centum/acceptance_evidence/test_inputs"


@pytest.mark.skipif(not os.path.isdir(REAL), reason="the real Centum test inputs are not on this machine")
@pytest.mark.parametrize("file,role", [("Centum_Scrub_BOM.xlsx", "scrub_bom"), ("Centum_BOM.xlsx", "bom"), ("Volume_File.xlsx", "volume"), ("QuoteWin_File.xlsx", "quotewin")])
def test_the_four_real_inputs(file, role):
    assert ar.classify_file(os.path.join(REAL, file))["role"] == role
