"""SPEC-023: the pre-flight finds the cells that would be NaN / error in the output, and agrees with the real SCRUB BOM step."""
import os
import sys
import types

import openpyxl
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "fastapi-router"))
import input_check as ic  # noqa: E402

HEAD = ["FG", "Level", "Assembly", "CPN", "Description", "Manufacturer", "MPN", "Commodity", "Quantity", "Unit of measure", "Part Status", "LTB Date"]
GOOD = [
    ["FG-1", 0, "FG-1", "FG-1", "Board", "Acme", "A-1", "PCB", 1, "EA", "Active", "31-12-2030"],
    ["FG-1", 1, "FG-1", "R-100", "Resistor", "Yageo", "RC0603", "RES", 10, "EA", "Active", "31-12-2030"],
]


def book(path, scrub=None, settings=None, batch=None, drop=()):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in (("SCRUB BOM", [HEAD] + (GOOD if scrub is None else scrub)),
                       ("Settings", [["FG", "V1 Qty", "V2 Qty"]] + ([["FG-1", 100, 500]] if settings is None else settings)),
                       ("Batch", [["FG", "V1 Batch Qty"]] + ([["FG-1", 50]] if batch is None else batch))):
        if name not in drop:
            ws = wb.create_sheet(name)
            for r in rows:
                ws.append(r)
    wb.save(path)
    return str(path)


def codes(rep, severity=None):
    return sorted({i["code"] for i in rep["issues"] if severity in (None, i["severity"])})


def test_a_clean_workbook_passes_with_no_flags(tmp_path):
    rep = ic.check(book(tmp_path / "ok.xlsx"))
    assert rep["checked"] and rep["ok"] and rep["errors"] == 0 and rep["warnings"] == 0 and rep["rows"] == 2


def test_the_real_centum_sample_has_no_errors():
    sample = os.path.join(ROOT, "..", "acceptance_evidence", "test_inputs", "Centum_Scrub_BOM.xlsx")
    if not os.path.exists(sample):
        pytest.skip("sample not on this machine")
    rep = ic.check(sample)
    assert rep["ok"], rep["issues"][:5]


def test_it_flags_text_quantity_blank_cpn_and_excel_errors_with_cell_addresses(tmp_path):
    bad = [
        ["FG-1", 0, "FG-1", "FG-1", "Board", "Acme", "A-1", "PCB", 1, "EA", "Active", "31-12-2030"],
        ["FG-1", 1, "FG-1", "R-100", "Resistor", "Yageo", "RC0603", "RES", "ten", "EA", "Active", "31-12-2030"],   # row 3: text quantity
        ["FG-1", 1, "FG-1", None, "Cap", "TDK", "C1", "CAP", 5, "EA", "Active", "31-12-2030"],                      # row 4: blank CPN
        ["FG-1", 1, "FG-1", "C-200", "Cap", "TDK", "C2", "CAP", "#REF!", "EA", "Active", "not a date"],             # row 5: error value + bad date
        ["FG-1", 1, "FG-1", "C-300", "Cap", "TDK", "C3", "CAP", "N/A", "EA", "Active", "31-12-2030"],               # row 6: N/A is read as empty
    ]
    rep = ic.check(book(tmp_path / "bad.xlsx", scrub=bad))
    assert not rep["ok"]
    at = {(i["code"], i["row"], i["col"]) for i in rep["issues"]}
    assert ("quantity_text", 3, "I") in at
    assert ("cpn_blank", 4, "D") in at
    assert ("cell_error", 5, "I") in at
    assert ("quantity_blank", 6, "I") in at          # "N/A" in a cell pandas reads as NaN
    assert ("ltb_date_unreadable", 5, "L") in at
    assert {i["severity"] for i in rep["issues"] if i["code"] == "ltb_date_unreadable"} == {"warning"}


def test_text_that_is_a_number_is_flagged_with_the_number_as_the_suggestion(tmp_path):
    bad = [GOOD[0], ["FG-1", 1, "FG-1", "R-100", "Resistor", "Yageo", "RC0603", "RES", "12", "EA", "Active", "31-12-2030"]]
    rep = ic.check(book(tmp_path / "t.xlsx", scrub=bad))
    one = [i for i in rep["issues"] if i["code"] == "quantity_text"]
    assert len(one) == 1 and one[0]["suggestion"] == "12"


def test_volumes_blank_text_and_missing_fg_are_errors_a_blank_batch_is_a_warning(tmp_path):
    rep = ic.check(book(tmp_path / "v.xlsx", settings=[["FG-1", None, "lots"]], batch=[["FG-1", None]]))
    assert {"volume_blank", "volume_not_number"} <= set(codes(rep, "error"))
    assert codes(rep, "warning") == ["batch_blank"]
    rep2 = ic.check(book(tmp_path / "v2.xlsx", settings=[["FG-9", 1, 2]]))
    miss = [i for i in rep2["issues"] if i["code"] == "fg_not_in_settings"]
    assert miss and miss[0]["fixable"] is False and miss[0]["value"] == "FG-1"


def test_missing_sheet_and_missing_required_column_are_errors_that_cannot_be_fixed_in_a_cell(tmp_path):
    rep = ic.check(book(tmp_path / "n.xlsx", drop=("SCRUB BOM",)))
    assert codes(rep, "error") == ["sheet_missing"] and not rep["issues"][0]["fixable"]
    wb = openpyxl.Workbook()
    wb.active.title = "SCRUB BOM"
    wb.active.append(["FG", "CPN", "Description"])
    wb.active.append(["FG-1", "X", "y"])
    wb.save(tmp_path / "c.xlsx")
    rep2 = ic.check(str(tmp_path / "c.xlsx"))
    miss = [i for i in rep2["issues"] if i["code"] == "column_missing"]
    assert {"MPN", "Quantity"} <= {w for i in miss for w in ("MPN", "Quantity") if f"'{w}'" in i["message"]}


def test_a_formula_with_no_saved_result_is_flagged(tmp_path):
    p = book(tmp_path / "f.xlsx", scrub=[GOOD[0], ["FG-1", 1, "FG-1", "R-100", "Resistor", "Yageo", "RC0603", "RES", "=1+2", "EA", "Active", "31-12-2030"]])
    rep = ic.check(p)   # openpyxl wrote the formula without a cached value, exactly like a file never calculated
    assert "formula_unsaved" in codes(rep, "error")


def test_other_formats_are_not_blocked_and_unreadable_files_are(tmp_path):
    csv = tmp_path / "a.csv"
    csv.write_text("a,b\n1,2\n")
    assert ic.check(str(csv)) == {**ic.check(str(csv)), "checked": False, "ok": True}
    junk = tmp_path / "junk.xlsx"
    junk.write_bytes(b"not a zip")
    rep = ic.check(str(junk))
    assert not rep["ok"] and codes(rep) == ["unreadable"]


def test_edits_are_typed_validated_and_never_formulas(tmp_path):
    src = book(tmp_path / "s.xlsx", scrub=[GOOD[0], ["FG-1", 1, "FG-1", "R-100", "Resistor", "Yageo", "RC0603", "RES", "ten", "EA", "Active", "31-12-2030"]])
    dst = str(tmp_path / "d.xlsx")
    assert ic.apply_edits(src, dst, [{"sheet": "SCRUB BOM", "row": 3, "col": "I", "value": "10"}, {"sheet": "SCRUB BOM", "row": 3, "col": "F", "value": "  "}]) == 2
    ws = openpyxl.load_workbook(dst)["SCRUB BOM"]
    assert ws["I3"].value == 10 and ws["F3"].value is None
    assert ic.check(dst)["errors"] == 0
    for bad in ({"sheet": "SCRUB BOM", "row": 3, "col": "I", "value": "=cmd|' /c calc'!A1"}, {"sheet": "Nope", "row": 3, "col": "I", "value": "1"},
                {"sheet": "SCRUB BOM", "row": 0, "col": "I", "value": "1"}, {"sheet": "SCRUB BOM", "row": 3, "col": "../x", "value": "1"}):
        with pytest.raises(ValueError):
            ic.apply_edits(src, dst, [bad])
    with pytest.raises(ValueError):
        ic.apply_edits(src, dst, [])
    assert src != dst and openpyxl.load_workbook(src)["SCRUB BOM"]["I3"].value == "ten"   # the original is untouched


# ---- parity with the real step -------------------------------------------------------------------------------------------

def _real_step():
    scrub_dir = os.path.join(ROOT, "mcp-tools", "scrub-intake")
    if not os.path.isdir(scrub_dir):
        pytest.skip("mcp-tools not present")
    pd = pytest.importorskip("pandas")
    sys.modules.setdefault("ollama", types.SimpleNamespace(chat=lambda **k: (_ for _ in ()).throw(RuntimeError("no LLM in tests"))))
    sys.path.insert(0, scrub_dir)
    import importlib
    return pd, importlib.import_module("scrub_bom_processing")


def test_every_cell_that_is_nan_in_the_real_volume_output_was_flagged(tmp_path):
    pd, real = _real_step()
    settings = [["FG-1", 100, None], ["FG-2", "lots", " 750 "], ["FG-3", "N/A", 5]]
    scrub = GOOD + [["FG-2", 0, "FG-2", "FG-2", "B", "A", "B-1", "X", 1, "EA", "Active", None], ["FG-3", 0, "FG-3", "FG-3", "B", "A", "B-2", "X", 1, "EA", "Active", None]]
    p = book(tmp_path / "p.xlsx", scrub=scrub, settings=settings)
    flagged = {(i["row"], i["col"]) for i in ic.check(p)["issues"] if i["sheet"] == "Settings"}
    out = real.process_volume_sheet(pd.read_excel(p, sheet_name="Settings"))
    nan_cells = set()
    for k, row in enumerate(settings, start=2):
        for j, name in enumerate(("V1 Qty", "V2 Qty")):
            val = out[(out["fg"] == row[0]) & (out["volume_name"] == name.replace(" Qty", ""))]["batch_qty"].iloc[0]
            if pd.isna(val):
                nan_cells.add((k, "BC"[j]))
    assert nan_cells == {(2, "C"), (3, "B"), (4, "B")}
    assert nan_cells <= flagged


def test_the_real_step_breaks_on_text_quantity_exactly_where_the_check_says(tmp_path):
    pd, real = _real_step()
    scrub = [GOOD[0], ["FG-1", 1, "FG-1", "SUB-1", "Sub", "A", "S1", "X", 2, "EA", "Active", None],
             ["FG-1", 2, "SUB-1", "R-1", "Res", "A", "R1", "X", "three", "EA", "Active", None]]
    p = book(tmp_path / "q.xlsx", scrub=scrub)
    flagged = {(i["row"], i["code"]) for i in ic.check(p)["issues"]}
    assert (4, "quantity_text") in flagged
    header = list(pd.read_excel(p, sheet_name="SCRUB BOM").columns)
    mapping = {t: next((h for h in header if ic._norm(h) in ic._ALIASES.get(t, set())), None) for t in real.SCRUB_BOM_TEMPLATE_HEADERS}
    df = real.standardize_scrub_bom(pd.read_excel(p, sheet_name="SCRUB BOM"), mapping)
    # the text quantity reaches the output untouched (not a number): the check is the only thing standing in front of it
    assert df["quantity"].map(lambda v: isinstance(v, str)).sum() == 1
