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
