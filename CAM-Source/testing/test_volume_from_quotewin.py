"""Volumes for a SCRUB BOM workbook without a Settings sheet, from the QuoteWin awards (7 of the 25 Centum batches, 2026-11-18).

The numbers below are batch-05's: its own Sheet1 states 3000 for 681H33201 and 3700 for the parts both FGs share, i.e. 700 for 681H31201.
"""
import os
import sys

import duckdb
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_INTAKE = os.path.join(ROOT, "mcp-tools", "scrub-intake")
sys.path.insert(0, _INTAKE)
try:
    import volume_from_quotewin as vq  # noqa: E402
finally:
    sys.path.remove(_INTAKE)  # the intake folder has its own db.py: left first on the path it shadows fastapi-router's for later tests

KEY = "B05-CE-005580__v3"


def _db(tmp_path, scrub, quotes, volumes=()):
    path = str(tmp_path / "input.duckdb")
    con = duckdb.connect(path)
    con.execute("""CREATE TABLE scrub_bom_items (bom_item_id UUID, rfq_id VARCHAR, fg VARCHAR, level VARCHAR, assembly VARCHAR,
                   cpn VARCHAR, quantity DOUBLE, hierarchy_multiplier DOUBLE)""")
    con.execute("CREATE TABLE quote_win (rfq_id VARCHAR, part_number VARCHAR, awarded_volume_1 DOUBLE, awarded_volume_2 DOUBLE)")
    for fg, level, cpn, qty in scrub:
        con.execute("INSERT INTO scrub_bom_items VALUES (uuid(), ?, ?, ?, ?, ?, ?, 1)", [KEY, fg, level, fg, cpn, qty])
    for pn, a1, a2 in quotes:
        con.execute("INSERT INTO quote_win VALUES (?, ?, ?, ?)", [KEY, pn, a1, a2])
    if volumes:
        con.execute("CREATE TABLE volume (fg VARCHAR, volume_name VARCHAR, batch_qty DOUBLE, rfq_id VARCHAR)")
        for fg, name, qty in volumes:
            con.execute("INSERT INTO volume VALUES (?, ?, ?, ?)", [fg, name, qty, KEY])
    con.close()
    return path


def _rows(path, sql):
    con = duckdb.connect(path, read_only=True)
    try:
        return con.execute(sql, [KEY]).fetchall()
    finally:
        con.close()


def test_two_fgs_one_from_its_own_parts_one_from_the_shared_remainder(tmp_path):
    scrub = [("FG-A", "0", "FG-A", 1), ("FG-B", "0", "FG-B", 1)]
    scrub += [("FG-B", "1", f"ONLY-B-{i}", 1) for i in range(4)]                       # used under FG-B alone
    scrub += [(fg, "2", f"SHARED-{i}", 1) for i in range(5) for fg in ("FG-A", "FG-B")]  # used under both
    quotes = [(f"ONLY-B-{i}", 3000, None) for i in range(4)] + [(f"SHARED-{i}", 3700, None) for i in range(5)]
    path = _db(tmp_path, scrub, quotes)
    r = vq.derive(KEY, db_path=path)
    got = {(v["fg"], v["volume"]): v["qty"] for v in r["volumes"]}
    assert r["derived"] and got == {("FG-B", "V1"): 3000.0, ("FG-A", "V1"): 700.0}
    assert sorted(_rows(path, "SELECT fg, volume_name, batch_qty FROM volume WHERE rfq_id = ?")) == [("FG-A", "V1", 700.0), ("FG-B", "V1", 3000.0)]
    assert sorted(_rows(path, "SELECT fg, volume, batch_qty FROM batch WHERE rfq_id = ?")) == [("FG-A", "V1", 700.0), ("FG-B", "V1", 3000.0)]
    note = _rows(path, "SELECT status, detail FROM input_notes WHERE rfq_id = ?")
    assert note and note[0][0] == "DERIVED from QuoteWin" and "FG-A V1 = 700" in note[0][1]


def test_a_second_volume_slot_and_a_line_quantity_of_two(tmp_path):
    scrub = [("FG-1", "1", f"P{i}", 2) for i in range(5)]
    quotes = [(f"P{i}", 60, 200) for i in range(5)]
    r = vq.derive(KEY, db_path=_db(tmp_path, scrub, quotes))
    assert {(v["volume"], v["qty"]) for v in r["volumes"]} == {("V1", 30.0), ("V2", 100.0)}


def test_nothing_is_invented_without_a_dominant_value(tmp_path):
    scrub = [("FG-1", "1", f"P{i}", 1) for i in range(4)]
    quotes = [("P0", 10, None), ("P1", 20, None), ("P2", 30, None), ("P3", 40, None)]
    path = _db(tmp_path, scrub, quotes)
    r = vq.derive(KEY, db_path=path)
    assert not r["derived"]
    assert _rows(path, "SELECT count(*) FROM volume WHERE rfq_id = ?") == [(0,)]


def test_volumes_given_by_the_workbook_are_never_replaced(tmp_path):
    scrub = [("FG-1", "1", f"P{i}", 1) for i in range(5)]
    quotes = [(f"P{i}", 500, None) for i in range(5)]
    path = _db(tmp_path, scrub, quotes, volumes=[("FG-1", "V1", 250)])
    r = vq.derive(KEY, db_path=path)
    assert not r["derived"] and "gives the volumes" in r["reason"]
    assert _rows(path, "SELECT batch_qty FROM volume WHERE rfq_id = ?") == [(250.0,)]


@pytest.mark.parametrize("ratios,expected", [([30] * 5, 30), ([30, 30, 30, 40], 30), ([3000, 3000], 3000), ([1, 2, 3], None), ([], None)])
def test_dominant(ratios, expected):
    got = vq.dominant(ratios)
    assert (got[0] if got else None) == expected
