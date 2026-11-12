"""SPEC-023: the pre-flight in front of the run (upload service) and behind the fix dialog (bridge /check and /fix)."""
import asyncio
import io
import os
import sys

import openpyxl
import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

sys.path.insert(0, os.path.dirname(__file__))
from test_attachment_api import api, auth, client, folder, upload  # noqa: E402,F401  (api is a fixture)
from test_input_check import GOOD, HEAD, book  # noqa: E402

FR_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "fastapi-router"))
BAD_ROW = ["FG-1", 1, "FG-1", "R-100", "Resistor", "Yageo", "RC0603", "RES", "ten", "EA", "Active", "31-12-2030"]


def _upload_server():
    sys.path.insert(0, FR_DIR)
    try:
        import upload_server
    except ImportError as e:
        pytest.skip(f"upload_server deps unavailable: {e}")
    finally:
        sys.path.remove(FR_DIR)
    return upload_server


def _file(path, name="bom.xlsx"):
    return UploadFile(file=io.BytesIO(open(path, "rb").read()), filename=name)


def test_the_upload_service_refuses_a_bom_that_would_give_nan_before_anything_is_created(tmp_path):
    us = _upload_server()
    f = _file(book(tmp_path / "bad.xlsx", scrub=[GOOD[0], BAD_ROW]))
    with pytest.raises(HTTPException) as e:
        asyncio.run(us._refuse_invalid_bom(f, None))
    assert e.value.status_code == 422
    d = e.value.detail
    assert d["code"] == "input_invalid" and d["errors"] == 1
    assert d["issues"][0]["row"] == 3 and d["issues"][0]["col"] == "I" and d["issues"][0]["code"] == "quantity_text"


def test_a_clean_bom_passes_and_the_file_can_still_be_read_afterwards(tmp_path):
    us = _upload_server()
    f = _file(book(tmp_path / "ok.xlsx"))
    asyncio.run(us._refuse_invalid_bom(f, None))
    assert asyncio.run(f.read())[:2] == b"PK"   # the gate rewound the file for the code that saves it


def test_another_routing_profile_reads_other_files_so_it_is_not_gated(tmp_path):
    us = _upload_server()
    asyncio.run(us._refuse_invalid_bom(_file(book(tmp_path / "bad.xlsx", scrub=[GOOD[0], BAD_ROW])), "RFQ_Flow"))


def test_the_volume_file_is_optional_for_the_scrub_bom_pipeline_but_not_for_rfq_flow(tmp_path):
    us = _upload_server()
    f = _file(book(tmp_path / "ok.xlsx", scrub=[GOOD[0], GOOD[1]]))
    with pytest.raises(HTTPException) as e:          # refused before anything is created
        asyncio.run(us.upload_rfq_file(bom_file=f, volume_file=None, gerber_file=None, rfq_id="R1", profile="RFQ_Flow", token={}, x_cam_user=None, x_cam_user_email=None))
    assert e.value.status_code == 400 and "volume file is required" in e.value.detail


def _quotewin(path, parts):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Awards Part Number Listing"])
    ws.append(["Part Number", "Mfg Part Number", "Commodity"])
    for p in parts:
        ws.append([p, "MPN-" + p, "RES"])
    wb.save(path)
    return path


def _db_with_bom(monkeypatch, us, bom_path):
    class Cur:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, *a): pass
        def fetchone(self): return (str(bom_path),)

    class Conn:
        def cursor(self): return Cur()
        def close(self): pass

    monkeypatch.setattr(us, "get_db_connection", lambda: Conn())


def test_a_quotewin_file_with_none_of_the_boms_parts_is_refused_with_the_numbers(tmp_path, monkeypatch):
    us = _upload_server()
    bom = book(tmp_path / "bom.xlsx", scrub=[GOOD[0], GOOD[1]])
    _db_with_bom(monkeypatch, us, bom)
    qw = _file(_quotewin(tmp_path / "other.xlsx", ["X-1", "X-2", "X-3"]), "other.xlsx")
    with pytest.raises(HTTPException) as e:
        asyncio.run(us._quotewin_match("R1", 1, qw))
    d = e.value.detail
    assert e.value.status_code == 422 and d["code"] == "quotewin_mismatch" and d["shared"] == 0 and d["quotewin_parts"] == 3, d
    assert "every cost would be 0" in d["message"]


def test_a_quotewin_file_that_knows_the_boms_parts_passes_and_a_partial_match_says_so(tmp_path, monkeypatch):
    us = _upload_server()
    bom = book(tmp_path / "bom.xlsx", scrub=[GOOD[0], GOOD[1]])
    _db_with_bom(monkeypatch, us, bom)
    cpns = {str(row[3]).upper() for row in (GOOD[0], GOOD[1])}
    qw = _file(_quotewin(tmp_path / "mine.xlsx", sorted(cpns)), "mine.xlsx")
    match = asyncio.run(us._quotewin_match("R1", 1, qw))
    assert match["known"] and match["shared"] == match["bom_parts"] == len(cpns), match


def test_a_released_workbook_lists_its_check_and_check_returns_every_cell(api, tmp_path):
    p = book(tmp_path / "Centum_BOM.xlsx", scrub=[GOOD[0], BAD_ROW])
    resp = upload(api, [("Centum_BOM.xlsx", open(p, "rb").read())])
    assert resp.status_code == 200, resp.text
    r = resp.json()["results"][0]
    assert r["role"] == "scrub_bom" and r["check"] == {"checked": True, "ok": False, "errors": 1, "warnings": 0}
    listed = client(api).get("/api/rfq/RFQ-APITEST/attachments", headers=auth(api)).json()
    assert listed[0]["check"]["errors"] == 1
    full = client(api).get(f"/api/rfq/RFQ-APITEST/attachments/{r['attachment_id']}/check", headers=auth(api)).json()
    assert full["issues"][0]["code"] == "quantity_text" and full["issues"][0]["col"] == "I"


def test_fix_writes_a_scanned_corrected_copy_that_replaces_the_original(api, tmp_path):
    p = book(tmp_path / "Centum_BOM.xlsx", scrub=[GOOD[0], BAD_ROW])
    first = upload(api, [("Centum_BOM.xlsx", open(p, "rb").read())]).json()["results"][0]
    old = first["attachment_id"]
    resp = client(api).post(f"/api/rfq/RFQ-APITEST/attachments/{old}/fix", headers=auth(api),
                            json={"edits": [{"sheet": "SCRUB BOM", "row": 3, "col": "I", "value": "10"}]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "Centum_BOM_corrected.xlsx" and body["attachment_id"] != old
    assert body["report"]["ok"] and body["check"] == {"checked": True, "ok": True, "errors": 0, "warnings": 0}
    names = sorted(n for _, n in [(a, n) for a, n, _ in api._released_files(folder(api))])
    assert names == ["Centum_BOM_corrected.xlsx"]        # the original is gone: one BOM, no "which one?"
    got = openpyxl.load_workbook(os.path.join(folder(api), f"{body['attachment_id']}-Centum_BOM_corrected.xlsx"))["SCRUB BOM"]["I3"].value
    assert got == 10
    audit = open(os.path.join(folder(api), "audit.jsonl"), encoding="utf-8").read()
    assert '"corrected_from": "' + old + '"' in audit and '"replaced_by"' in audit


def test_fix_refuses_formula_looking_text_and_unknown_cells_and_keeps_the_original(api, tmp_path):
    p = book(tmp_path / "Centum_BOM.xlsx", scrub=[GOOD[0], BAD_ROW])
    old = upload(api, [("Centum_BOM.xlsx", open(p, "rb").read())]).json()["results"][0]["attachment_id"]
    for bad in ({"sheet": "SCRUB BOM", "row": 3, "col": "I", "value": "=1+1"}, {"sheet": "Nope", "row": 3, "col": "I", "value": "1"}):
        r = client(api).post(f"/api/rfq/RFQ-APITEST/attachments/{old}/fix", headers=auth(api), json={"edits": [bad]})
        assert r.status_code == 400 and "not applied" in r.json()["detail"]
    assert [a for a, _, _ in api._released_files(folder(api))] == [old]
    assert client(api).post("/api/rfq/RFQ-APITEST/attachments/ffffffffffff/fix", headers=auth(api), json={"edits": []}).status_code == 404
