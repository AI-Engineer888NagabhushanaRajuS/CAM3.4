"""Exported workbooks store each formula's value, so viewers that do not recalculate (Excel Protected View,
Outlook/Windows previews, phones, scripts) show numbers instead of blanks.

Found on the real export of RFQ-CENTUM-PROOF-23: 34,095 formula cells, 0 with a stored value.
"""
import os
import subprocess
import sys
import zipfile
from xml.sax.saxutils import escape

import openpyxl
import pytest
from openpyxl.styles import Font

SUP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mcp-tools", "reporting", "superset"))
sys.path.insert(0, SUP)
try:
    import cached_values as cv
finally:
    sys.path.remove(SUP)

needs_libreoffice = pytest.mark.skipif(cv.find_libreoffice() is None, reason="LibreOffice not installed (LIBREOFFICE_BIN)")

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def make_workbook(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Calc"
    ws["A1"], ws["B1"] = 2, 3
    ws["C1"] = "=A1*B1"
    ws["D1"] = '=IF(C1>5,"big","small")'
    ws["E1"] = "=C1>5"
    ws["F1"] = "=1/0"
    ws["G1"] = '=""'
    ws["A1"].font = Font(bold=True)
    ws["C1"].number_format = "0.00"
    other = wb.create_sheet("Sum & Count")  # "&" is XML-escaped in workbook.xml
    other["A1"] = "=SUM(Calc!A1:B1)+Calc!C1"
    other["A2"] = '=COUNTIFS(Calc!A1:B1,">1")'
    wb.save(path)
    return path


def fake_libreoffice_copy(path, sheets):
    """A zip shaped like LibreOffice's output (relative sheet targets, t= and aca= attributes) with chosen results.
    sheets: {sheet name: {cell: (type, text)}}"""
    names = list(sheets)
    workbook = (f'<workbook xmlns="{MAIN}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                + "".join(f'<sheet name="{escape(n, {chr(34): "&quot;"})}" sheetId="{i}" state="visible" r:id="rId{i}"/>'
                          for i, n in enumerate(names, 1)) + "</sheets></workbook>")
    rels = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(f'<Relationship Id="rId{i}" Type="worksheet" Target="worksheets/sheet{i}.xml"/>'
                      for i in range(1, len(names) + 1)) + "</Relationships>")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        for i, n in enumerate(names, 1):
            cells = "".join(f'<c r="{ref}" s="1" t="{t}"><f aca="false">X</f><v>{escape(text)}</v></c>'
                            for ref, (t, text) in sheets[n].items())
            z.writestr(f"xl/worksheets/sheet{i}.xml",
                       f'<worksheet xmlns="{MAIN}"><sheetData><row r="1">{cells}</row></sheetData></worksheet>')
    return path


def test_the_defect_is_real_openpyxl_stores_no_value(tmp_path):
    wb = openpyxl.load_workbook(make_workbook(tmp_path / "book.xlsx"), data_only=True)
    assert wb["Calc"]["C1"].value is None and wb["Sum & Count"]["A1"].value is None


def test_results_are_copied_into_the_original_cells_by_sheet_name_and_type(tmp_path):
    original = make_workbook(tmp_path / "book.xlsx")
    fake = fake_libreoffice_copy(tmp_path / "lo.xlsx", {
        "Calc": {"C1": ("n", "6"), "D1": ("str", "A&B <big>"), "E1": ("b", "1"), "F1": ("e", "#DIV/0!"), "G1": ("str", "")},
        "Sum & Count": {"A1": ("n", "11"), "A2": ("s", "7")},  # a shared-string type must never be copied
    })
    stats = cv._inject(original, fake, tmp_path / "out.xlsx")
    assert stats == {"formulas": 7, "cached": 6}
    values = openpyxl.load_workbook(tmp_path / "out.xlsx", data_only=True)
    assert values["Calc"]["C1"].value == 6
    assert values["Calc"]["D1"].value == "A&B <big>"
    assert values["Calc"]["E1"].value is True
    assert values["Calc"]["F1"].value == "#DIV/0!"
    assert values["Sum & Count"]["A1"].value == 11
    assert values["Sum & Count"]["A2"].value is None


@needs_libreoffice
def test_every_formula_gets_its_value_stays_a_formula_and_keeps_its_styling(tmp_path):
    path = make_workbook(tmp_path / "book.xlsx")
    with zipfile.ZipFile(path) as z:
        styles_before = z.read("xl/styles.xml")
        parts_before = set(z.namelist())

    result = cv.add_cached_values(path)
    assert result["status"] == "ok" and result["formulas"] == result["cached"] == 7, result

    values = openpyxl.load_workbook(path, data_only=True)
    assert values["Calc"]["C1"].value == 6
    assert values["Calc"]["D1"].value == "big"
    assert values["Calc"]["E1"].value is True
    assert values["Calc"]["F1"].value == "#DIV/0!"
    assert values["Calc"]["G1"].value in (None, "")
    assert values["Sum & Count"]["A1"].value == 11
    assert values["Sum & Count"]["A2"].value == 2

    formulas = openpyxl.load_workbook(path)  # still live formulas
    assert formulas["Calc"]["C1"].value == "=A1*B1"
    assert formulas["Sum & Count"]["A2"].value == '=COUNTIFS(Calc!A1:B1,">1")'
    assert formulas["Calc"]["A1"].font.bold is True and formulas["Calc"]["C1"].number_format == "0.00"
    with zipfile.ZipFile(path) as z:
        assert set(z.namelist()) == parts_before
        assert z.read("xl/styles.xml") == styles_before  # no collateral change
        assert 'fullCalcOnLoad="1"' in z.read("xl/workbook.xml").decode()  # Excel still recalculates when it may


def test_without_libreoffice_the_export_is_left_untouched(tmp_path, monkeypatch):
    path = make_workbook(tmp_path / "book.xlsx")
    before = path.read_bytes()
    monkeypatch.setattr(cv, "find_libreoffice", lambda: None)
    assert cv.add_cached_values(path)["status"] == "skipped"
    assert path.read_bytes() == before


def test_a_libreoffice_failure_never_breaks_the_export(tmp_path, monkeypatch):
    path = make_workbook(tmp_path / "book.xlsx")
    before = path.read_bytes()
    monkeypatch.setattr(cv, "find_libreoffice", lambda: "soffice")

    def hang(*args, **kwargs):
        raise subprocess.TimeoutExpired("soffice", 1)

    monkeypatch.setattr(cv, "_recalculate", hang)
    result = cv.add_cached_values(path)
    assert result["status"] == "failed" and "TimeoutExpired" in result["reason"], result
    assert path.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["book.xlsx"]  # no staging file left behind


def test_it_can_be_switched_off(tmp_path, monkeypatch):
    path = make_workbook(tmp_path / "book.xlsx")
    monkeypatch.setenv("CAM_CACHE_VALUES", "0")
    assert cv.add_cached_values(path)["status"] == "skipped"
