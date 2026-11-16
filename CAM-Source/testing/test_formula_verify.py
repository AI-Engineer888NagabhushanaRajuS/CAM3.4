"""The CAM Formula Engine as an independent check of a finished workbook (mcp-tools/shared/formula_verify.py).

The engine's own 540 tests live next to it (mcp-tools/shared/formula_engine/engine/tests); these cover the CAM glue: what is counted as
agreeing / different / lacking a stored value, and that correct() stores the engine's value without touching the formulas.
"""
import re
import time
import zipfile

import openpyxl
import pytest

import formula_verify as fv


def _book(path, stored):
    """C1 = A1+B1 (5), C2 = C1*10 (50), C3 = SUM(A1:C2) (60). `stored` sets the cached <v> per cell, as a report written by openpyxl and then cached by LibreOffice has."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "S"
    ws["A1"], ws["B1"] = 2, 3
    ws["C1"], ws["C2"], ws["C3"] = "=A1+B1", "=C1*10", "=SUM(A1:C2)"
    wb.save(path)
    with zipfile.ZipFile(path) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    xml = parts["xl/worksheets/sheet1.xml"].decode("utf-8")
    for ref, value in stored.items():
        xml = re.sub(rf'(<c r="{ref}"[^>]*>(?:<f>[^<]*</f>))(?:<v\s*/>|<v></v>)', rf"\g<1><v>{value}</v>", xml)
    parts["xl/worksheets/sheet1.xml"] = xml.encode("utf-8")
    with zipfile.ZipFile(path, "w") as z:
        for n, b in parts.items():
            z.writestr(n, b)


def test_a_workbook_whose_stored_values_are_right_is_all_exact(tmp_path):
    p = tmp_path / "ok.xlsx"
    _book(p, {"C1": 5, "C2": 50, "C3": 60})
    r = fv.verify(p)
    assert r["error"] is None and r["complete"] and r["release_ready"] is False
    assert r["totals"] == {"formulas": 3, "exact": 3, "different": 0, "no_stored_value": 0, "engine_error": 0}, r["totals"]


def test_a_wrong_stored_value_is_different_and_a_missing_one_is_counted_separately(tmp_path):
    p = tmp_path / "bad.xlsx"
    _book(p, {"C1": 5, "C2": 0})                      # C2 wrong (0, as LibreOffice stores a cell it cannot evaluate); C3 has no stored value
    r = fv.verify(p)
    assert r["totals"]["exact"] == 1 and r["totals"]["different"] == 1 and r["totals"]["no_stored_value"] == 1, r["totals"]
    assert r["sheets"]["S"]["samples"] == [{"row": 2, "col": 3, "engine": "50", "stored": "0"}] or r["sheets"]["S"]["samples"][0]["engine"] in ("50", "50.0")


def test_correct_stores_the_engines_values_keeps_the_formulas_and_leaves_nothing_different(tmp_path):
    p = tmp_path / "fix.xlsx"
    _book(p, {"C1": 5, "C2": 0})
    r = fv.correct(p)
    assert r["error"] is None and r["corrected"] == 2, r
    values = openpyxl.load_workbook(p, data_only=True)["S"]
    assert (values["C1"].value, values["C2"].value, values["C3"].value) == (5, 50, 60)
    forms = openpyxl.load_workbook(p)["S"]
    assert (forms["C2"].value, forms["C3"].value) == ("=C1*10", "=SUM(A1:C2)")
    again = fv.verify(p)
    assert again["totals"]["exact"] == 3 and again["totals"]["different"] == 0, again["totals"]
    assert not list(tmp_path.glob(".*.engine.xlsx"))  # no half-written file left behind


def test_a_workbook_the_engine_cannot_open_is_reported_not_raised(tmp_path):
    p = tmp_path / "junk.xlsx"
    p.write_bytes(b"not a workbook")
    r = fv.verify(p)
    assert r["error"] and r["complete"] is False
    assert fv.correct(p)["corrected"] == 0


def test_older_exports_get_their_values_stored_in_a_background_job_with_progress(tmp_path):
    paths = []
    for i in range(2):
        p = tmp_path / f"old{i}.xlsx"
        _book(p, {})                                   # an export made before the engine step: no stored values at all
        paths.append(p)
    fv.repair_many(paths)
    deadline = time.time() + 60
    # wait for the work itself (done or failed), not for the running flag: the job thread may not have set it yet
    while time.time() < deadline:
        st = fv.repair_status()
        if st["done"] + len(st["failed"]) >= st["total"] and not st["running"]:
            break
        time.sleep(0.1)
    st = fv.repair_status()
    assert not st["running"] and st["done"] == st["total"] == 2 and st["failed"] == [], st
    for p in paths:
        values = openpyxl.load_workbook(p, data_only=True)["S"]
        assert (values["C1"].value, values["C2"].value, values["C3"].value) == (5, 50, 60)


def test_the_check_runs_in_the_background_and_its_result_is_kept_next_to_the_workbook(tmp_path):
    p = tmp_path / "bg.xlsx"
    _book(p, {"C1": 5, "C2": 50, "C3": 60})
    assert fv.status(p)["status"] == "none"
    fv.start(p)
    deadline = time.time() + 30
    while fv.status(p)["status"] != "done" and time.time() < deadline:
        time.sleep(0.1)
    done = fv.status(p)
    assert done["status"] == "done" and done["result"]["totals"]["exact"] == 3
    assert (tmp_path / "bg.xlsx.verify.json").exists()
    assert "Not client approval" in done["result"]["label"]
