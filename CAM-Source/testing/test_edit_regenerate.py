"""SPEC-020 edit-and-regenerate: allow-list, limits, event/call order, cell diff, revert, no-previous-export.

No docker, no real database or export: the database and the export are fakes handed in as `Ports`; the two tiny
workbooks are real .xlsx files built with openpyxl (stored values stand in for LibreOffice's cached results).
"""
import json
import os
import sys
import time

import duckdb
import openpyxl
import pytest
from fastapi.testclient import TestClient

FR_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "fastapi-router"))
RFQ = "RFQ-EDIT-1"


@pytest.fixture
def api():
    sys.path.insert(0, FR_DIR)
    try:
        import duck_db_api
    finally:
        sys.path.remove(FR_DIR)
    yield duck_db_api
    duck_db_api.app.dependency_overrides.clear()


@pytest.fixture
def er(api):
    return api.edit_regenerate


def make_book(path, price, total, generated, formula_total=False, extra_rows=0):
    wb = openpyxl.Workbook()
    cbom = wb.active
    cbom.title = "CBOM"
    cbom.append(["part", "price"])
    cbom.append(["R1", price])
    for i in range(extra_rows):
        cbom.append([f"X{i}", price + i])
    summary = wb.create_sheet("Summary")
    summary.append(["label", "value"])
    summary.append(["Total", "=SUM(CBOM!B2:B2)" if formula_total else total])  # stored value stands in for a cached result
    manifest = wb.create_sheet("Manifest")
    manifest.append(["Field", "Value"])
    manifest.append(["RFQ ID", RFQ])
    manifest.append(["Workbook", os.path.basename(str(path))])
    manifest.append(["Generated (UTC)", generated])
    wb.save(path)
    return str(path)


class Fake:
    """Fake database + export + relay. `log` records every call in order."""

    def __init__(self, tmp_path, er, with_before=True, export_error=None, revert_error=False, export_sleep=0):
        self.er, self.dir, self.log, self.events = er, tmp_path, [], []
        self.export_error, self.revert_error, self.export_sleep = export_error, revert_error, export_sleep
        self.applied = []
        self.before = make_book(tmp_path / "CBOM_Report_X_20260101_000000.xlsx", 1.0, 10.0, "2026-01-01T00:00:00") if with_before else None
        if self.before:
            os.utime(self.before, (1000, 1000))
        self.ports = er.Ports(self.read_rows, self.apply, self.list_exports, self.export, self.emit)

    def read_rows(self, specs):
        self.log.append("read_rows")
        return [[{"bom_item_id": b, "volume_no": 1, **{f: 1.0 if f == "final_price_conv" else "old" for f in fields}}]
                for b, v, fields in specs if b != "MISSING"] + [[] for b, v, f in specs if b == "MISSING"]

    def apply(self, rows):
        self.log.append("apply")
        self.applied.append(rows)
        if len(self.applied) > 1 and self.revert_error:
            raise RuntimeError("revert broke")

    def list_exports(self):
        self.log.append("list_exports")
        return [os.path.join(self.dir, n) for n in os.listdir(self.dir) if n.endswith(".xlsx")]

    def export(self):
        self.log.append("export")
        time.sleep(self.export_sleep)
        if self.export_error:
            raise RuntimeError(self.export_error)
        after = make_book(self.dir / "CBOM_Report_X_20260102_000000_abcd1234.xlsx", 2.0, 20.0, "2026-01-02T09:09:09")
        os.utime(after, (2000, 2000))
        return {"status": "success", "workbook_name": os.path.basename(after), "cached_values": {"status": "ok"}}

    def emit(self, event, payload):
        self.log.append("emit " + event)
        self.events.append((event, payload))


EDIT = [{"bom_item_id": "B1", "set": {"final_price_conv": 2.0}}]
FIELDS = ["final_mfg_name", "final_unit_of_measure", "final_price_conv", "final_price_original",
          "final_currency_original", "final_supp_name", "final_pkg_qty", "final_moq", "final_lead_time"]


def run(er, fake, edits=EDIT, **kw):
    return er.edit_and_regenerate(RFQ, edits, "why", FIELDS, fake.ports, **kw)


def test_field_types_cover_exactly_the_batch_update_allow_list(api, er):
    assert set(er.FIELD_TYPES) == set(api.EDITABLE_FIELDS)


@pytest.mark.parametrize("edits", [
    [{"bom_item_id": "B1", "set": {"cpn": "X"}}],                      # not an editable field
    [{"bom_item_id": "B1", "set": {"final_price_conv": "abc"}}],       # text for a number
    [{"bom_item_id": "B1", "set": {"final_moq": True}}],               # bool is not a number
    [{"bom_item_id": "B1", "set": {"final_moq": -1}}],
    [{"bom_item_id": "B1", "set": {"final_lead_time": 1.5}}],
    [{"bom_item_id": "B1", "set": {"final_supp_name": None}}],         # null refused
    [{"bom_item_id": "B1", "set": {}}],
    [{"bom_item_id": "", "set": {"final_moq": 1}}],
    [{"bom_item_id": "B1", "set": {"final_moq": 1}}, {"bom_item_id": "B1", "set": {"final_moq": 2}}],  # duplicate
])
def test_refused_before_anything_runs(tmp_path, er, edits):
    fake = Fake(tmp_path, er)
    with pytest.raises(er.EditError) as e:
        run(er, fake, edits)
    assert e.value.status in (400, 422)
    assert fake.log == [] and fake.events == []


def test_row_limit(tmp_path, er):
    fake = Fake(tmp_path, er)
    many = [{"bom_item_id": f"B{i}", "set": {"final_moq": 1}} for i in range(201)]
    with pytest.raises(er.EditError) as e:
        run(er, fake, many)
    assert e.value.status == 422 and "200" in e.value.message and fake.log == []
    assert run(er, Fake(tmp_path, er), many[:200])["ok"]


def test_unknown_bom_item_is_404_and_nothing_applied(tmp_path, er):
    fake = Fake(tmp_path, er)
    with pytest.raises(er.EditError) as e:
        run(er, fake, [{"bom_item_id": "MISSING", "set": {"final_moq": 1}}])
    assert e.value.status == 404 and fake.applied == []


def test_success_order_events_and_response(tmp_path, er):
    fake = Fake(tmp_path, er)
    out = run(er, fake)
    assert fake.log == ["list_exports", "read_rows", "apply", "emit rfq:value-changed",
                        "emit rfq:reports-regenerating", "export", "list_exports", "emit rfq:reports-ready"]
    assert fake.applied == [[{"bom_item_id": "B1", "volume_no": 1, "final_price_conv": 2.0}]]
    changed, regenerating, ready = (p for _, p in fake.events)
    assert changed["fields"] == ["final_price_conv"] and changed["rfqId"] == RFQ
    assert changed["items"] == [{"bomItemId": "B1", "volumeNo": 1, "field": "final_price_conv", "before": 1.0, "after": 2.0}]
    assert regenerating == {"rfqId": RFQ}
    assert ready == {"rfqId": RFQ, "filename": "CBOM_Report_X_20260102_000000_abcd1234.xlsx",
                     "totalChangedCells": 2, "sheets": 2}
    assert out["before"] == {"filename": "CBOM_Report_X_20260101_000000.xlsx"}
    assert out["after"]["filename"] == ready["filename"] and out["after"]["generated_at"]
    assert out["applied"] == 1 and out["diff"]["total_changed_cells"] == 2
    saved = json.load(open(os.path.join(tmp_path, ready["filename"] + ".diff.json")))
    assert saved["total_changed_cells"] == 2 and saved["note"] == "why"


def test_diff_counts_edit_and_dependent_cell_in_other_sheet_and_ignores_volatile_cells(tmp_path, er):
    b = make_book(tmp_path / "b.xlsx", 1.0, 10.0, "2026-01-01T00:00:00")
    a = make_book(tmp_path / "a.xlsx", 2.0, 20.0, "2026-02-02T02:02:02")  # Workbook name and Generated also differ
    diff = er.diff_workbooks(b, a)
    assert diff["total_changed_cells"] == 2
    by = {s["sheet"]: s for s in diff["sheets"]}
    assert set(by) == {"CBOM", "Summary"}                                # Manifest differs only in volatile cells
    assert by["CBOM"]["examples"] == [{"cell": "B2", "before": 1.0, "after": 2.0}]
    assert by["Summary"]["examples"] == [{"cell": "B2", "before": 10.0, "after": 20.0}]
    assert er.IGNORED_NOTE in diff["ignored"]


def _book_with_notes(path, rows):
    make_book(path, 1.0, 10.0, "2026-01-01T00:00:00")
    wb = openpyxl.load_workbook(path)
    ws = wb.create_sheet("Missing Notes")
    ws.append(["1. Uncosted Parts"])
    ws.append(["Sl.no", "Part Number", "Remarks"])
    for i, (part, note) in enumerate(rows, 1):
        ws.append([i, part, note])
    ws.append([None])
    ws.append(["2. Other"])
    ws.append(["Sl.no", "Part Number"])
    ws.append([1, "ZZ"])
    wb.save(path)
    return str(path)


def test_a_stored_zero_and_a_stored_false_are_different_values(er):
    assert er._same(0, False) is False and er._same(False, 0) is False
    assert er._same(0, 0.0) is True and er._same(False, False) is True and er._same("a", "a") is True


def test_diff_compares_the_unordered_missing_notes_sheet_as_a_set_of_rows(tmp_path, er):
    rows = [("A1", "x"), ("B2", None), ("C3", "y")]
    b = _book_with_notes(tmp_path / "b.xlsx", rows)
    shuffled = _book_with_notes(tmp_path / "s.xlsx", [rows[2], rows[0], rows[1]])  # same rows, other order and serials
    assert er.diff_workbooks(b, shuffled)["total_changed_cells"] == 0
    changed = _book_with_notes(tmp_path / "c.xlsx", [rows[2], ("B2", "now noted"), rows[0]])
    d = er.diff_workbooks(b, changed)
    assert [s["sheet"] for s in d["sheets"]] == ["Missing Notes"]                    # a real change is still found
    assert d["total_changed_cells"] == 1
    assert d["sheets"][0]["examples"] == [{"cell": "C4", "before": None, "after": "now noted"}]
    assert er.ORDER_FREE_NOTE in d["ignored"]


def test_diff_examples_capped_per_sheet_and_uncached_formulas_not_counted(tmp_path, er):
    b = make_book(tmp_path / "b.xlsx", 1.0, 10.0, "t", extra_rows=25)
    a = make_book(tmp_path / "a.xlsx", 5.0, 10.0, "t", extra_rows=25)
    d = er.diff_workbooks(b, a)
    cbom = next(s for s in d["sheets"] if s["sheet"] == "CBOM")
    assert cbom["changed"] == 26 and len(cbom["examples"]) == 20
    # a formula without a stored result (export made without LibreOffice) is skipped, never a "change"
    f = make_book(tmp_path / "f.xlsx", 1.0, 10.0, "t", formula_total=True)
    g = make_book(tmp_path / "g.xlsx", 1.0, 99.0, "t")
    d2 = er.diff_workbooks(f, g)
    assert d2["total_changed_cells"] == 0 and d2["uncached_formula_cells_skipped"] == 1


@pytest.mark.parametrize("error,status", [("boom", 502)])
def test_export_failure_reverts_and_reports(tmp_path, er, error, status):
    fake = Fake(tmp_path, er, export_error=error)
    with pytest.raises(er.EditError) as e:
        run(er, fake)
    assert e.value.status == status and "reverted" in e.value.message and "boom" in e.value.message
    assert fake.applied[1] == [{"bom_item_id": "B1", "volume_no": 1, "final_price_conv": 1.0}]   # the previous value
    assert [ev for ev, _ in fake.events] == ["rfq:value-changed", "rfq:reports-regenerating", "rfq:reports-failed"]
    assert "reverted" in fake.events[-1][1]["message"]


def test_export_status_failed_and_missing_workbook_also_revert(tmp_path, er):
    fake = Fake(tmp_path, er)
    fake.export = lambda: {"status": "failed", "error": "no cbom rows"}
    fake.ports.export = fake.export
    with pytest.raises(er.EditError):
        run(er, fake)
    assert len(fake.applied) == 2


def test_timeout_reverts_with_504(tmp_path, er):
    fake = Fake(tmp_path, er, export_sleep=0.5)
    with pytest.raises(er.EditError) as e:
        run(er, fake, export_timeout=0.05)
    assert e.value.status == 504 and len(fake.applied) == 2


def test_revert_failure_is_loud(tmp_path, er):
    fake = Fake(tmp_path, er, export_error="boom", revert_error=True)
    with pytest.raises(er.EditError) as e:
        run(er, fake)
    assert e.value.status == 500 and "REVERTING THE EDITS FAILED" in e.value.message


def test_no_previous_export(tmp_path, er):
    fake = Fake(tmp_path, er, with_before=False)
    out = run(er, fake)
    assert out["before"] is None and out["diff"] is None and "nothing to compare" in out["diff_note"]
    ready = fake.events[-1][1]
    assert ready["totalChangedCells"] is None and ready["sheets"] is None
    assert not any(n.endswith(".diff.json") for n in os.listdir(tmp_path))


def test_diff_failure_does_not_revert(tmp_path, er, monkeypatch):
    fake = Fake(tmp_path, er)
    monkeypatch.setattr(er, "diff_workbooks", lambda *a: 1 / 0)
    out = run(er, fake)
    assert out["ok"] and out["diff"] is None and "ZeroDivisionError" in out["diff_error"] and len(fake.applied) == 1


def test_relay_failure_does_not_fail_the_edit(tmp_path, er):
    fake = Fake(tmp_path, er)
    fake.ports.emit = lambda *a: (_ for _ in ()).throw(ConnectionError("daemon down"))
    assert run(er, fake)["ok"]


def test_concurrent_edit_for_same_rfq_is_409(tmp_path, er):
    lock = er._rfq_lock(RFQ)
    lock.acquire()
    try:
        with pytest.raises(er.EditError) as e:
            run(er, Fake(tmp_path, er))
        assert e.value.status == 409
    finally:
        lock.release()


def test_emit_event_posts_to_daemon_relay_and_swallows_errors(er, monkeypatch):
    import httpx
    calls = []
    monkeypatch.setenv("CAM_DAEMON_URL", "http://daemon.test:9334/")
    monkeypatch.setattr(httpx, "post", lambda url, json, timeout: calls.append((url, json)))
    er.emit_event("rfq:reports-ready", {"rfqId": RFQ, "filename": "f.xlsx"})
    assert calls == [("http://daemon.test:9334/api/internal/emit-rfq-event",
                      {"event": "rfq:reports-ready", "rfqId": RFQ, "filename": "f.xlsx"})]
    monkeypatch.setattr(httpx, "post", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("down")))
    er.emit_event("rfq:reports-ready", {"rfqId": RFQ})  # no raise


def test_exports_listing_strict_names_newest_first_with_summary(tmp_path, api, er, monkeypatch):
    monkeypatch.setattr(api.reporting_config, "EXPORTS_DIR", str(tmp_path), raising=False)  # config may be another package's in a full run
    for n, t in [("CBOM_Report_RFQ_1_20260101_000000_aaaaaaaa.xlsx", 1000), ("CBOM_Report_RFQ_1_20260102_000000_bbbbbbbb.xlsx", 2000),
                 ("CBOM_Report_RFQ_1_v2_20260103_000000_cccccccc.xlsx", 3000), ("CBOM_Report_RFQ_1_20260104_000000_dddddddd.xlsx.part", 4000)]:
        p = tmp_path / n
        p.write_bytes(b"x")
        os.utime(p, (t, t))
    (tmp_path / "CBOM_Report_RFQ_1_20260102_000000_bbbbbbbb.xlsx.diff.json").write_text(
        json.dumps({"total_changed_cells": 7, "sheets": [{}, {}, {}]}))
    out = er.describe_exports(api._list_cbom_exports("RFQ-1"))
    assert [o["filename"] for o in out] == ["CBOM_Report_RFQ_1_20260102_000000_bbbbbbbb.xlsx", "CBOM_Report_RFQ_1_20260101_000000_aaaaaaaa.xlsx"]
    assert out[0]["diff_summary"] == {"total_changed_cells": 7, "sheets": 3} and out[1]["diff_summary"] is None
    assert api._find_latest_export("RFQ-1").endswith("bbbbbbbb.xlsx")


def test_a_kept_version_downloads_only_by_its_own_exact_name(tmp_path, api, monkeypatch):
    """The 'Versions' list downloads one kept workbook: the name must be one of THIS RFQ's exports, no path tricks."""
    monkeypatch.setattr(api.reporting_config, "EXPORTS_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(api, "_resolve_cbom_key", lambda r: r)
    mine = "CBOM_Report_RFQ_1_20260101_000000_aaaaaaaa.xlsx"
    (tmp_path / mine).write_bytes(b"PK-mine")
    (tmp_path / "CBOM_Report_RFQ_2_20260101_000000_bbbbbbbb.xlsx").write_bytes(b"PK-other-rfq")
    (tmp_path / "secret.txt").write_text("nope")
    client = TestClient(api.app)
    h = {"Authorization": f"Bearer {api.auth.create_token('RFQ-1')}"}
    ok = client.get(f"/api/rfq/RFQ-1/exports/{mine}/download", headers=h)
    assert ok.status_code == 200 and ok.content == b"PK-mine"
    for bad in ["CBOM_Report_RFQ_2_20260101_000000_bbbbbbbb.xlsx", "secret.txt", "..%2Fsecret.txt", "CBOM_Report_RFQ_1_v2_20260101_000000_cccccccc.xlsx"]:
        assert client.get(f"/api/rfq/RFQ-1/exports/{bad}/download", headers=h).status_code == 404
    assert client.get(f"/api/rfq/RFQ-1/exports/{mine}/download").status_code == 401


def test_routes_token_bound_to_rfq_and_response_shape(tmp_path, api, er, monkeypatch):
    fake = Fake(tmp_path, er)
    monkeypatch.setattr(api, "_resolve_cbom_key", lambda r: r)
    monkeypatch.setattr(api, "_read_edit_rows", lambda key, specs: fake.read_rows(specs))
    monkeypatch.setattr(api, "apply_bom_updates", lambda key, rows: fake.apply(rows))
    monkeypatch.setattr(api, "_list_cbom_exports", lambda key: fake.list_exports())
    monkeypatch.setattr(er, "call_reporting_export", lambda key: fake.export())
    monkeypatch.setattr(er, "emit_event", fake.emit)
    client = TestClient(api.app)
    url = f"/api/rfq/{RFQ}/edit-and-regenerate"
    body = {"edits": EDIT, "note": "why"}
    assert client.post(url, json=body).status_code == 401
    other = {"Authorization": f"Bearer {api.auth.create_token('RFQ-OTHER')}"}
    assert client.post(url, json=body, headers=other).status_code == 401
    ok = {"Authorization": f"Bearer {api.auth.create_token(RFQ)}"}
    bad = client.post(url, json={"edits": [{"bom_item_id": "B1", "set": {"cpn": "x"}}]}, headers=ok)
    assert bad.status_code == 422 and "not an editable field" in bad.json()["detail"]
    r = client.post(url, json=body, headers=ok)
    assert r.status_code == 200 and r.json()["ok"] and r.json()["diff"]["total_changed_cells"] == 2
    listing = client.get(f"/api/rfq/{RFQ}/exports", headers={"Authorization": f"Bearer {api.auth.create_token(RFQ)}"})
    assert listing.status_code == 200 and listing.json()[0]["diff_summary"]["total_changed_cells"] == 2


class _KeepOpen:
    """DuckDB connection whose close() is a no-op so the test can read back after the helper closed it."""
    def __init__(self, con):
        self.con = con

    def execute(self, *a):
        self.con.execute(*a)
        return self.con

    @property
    def description(self):
        return self.con.description

    def close(self):
        pass


def test_shared_helper_and_snapshot_on_real_duckdb(api, monkeypatch):
    """batch-update's body, moved into apply_bom_updates, keeps its behaviour; the snapshot reads per (id, volume)."""
    import contextlib
    con = duckdb.connect(":memory:")
    con.execute("ATTACH ':memory:' AS cbom_db")
    con.execute("CREATE TABLE cbom_db.cbom (rfq_id VARCHAR, bom_item_id VARCHAR, volume_no INTEGER, cpn VARCHAR, "
                "final_price_conv DOUBLE, final_moq DOUBLE)")
    con.execute("INSERT INTO cbom_db.cbom VALUES ('K','B1',1,'C',1.0,5), ('K','B1',2,'C',1.0,5), ('K','B2',1,'C',1.0,5)")
    recomputed = []
    monkeypatch.setattr(api.reporting_database, "connect", lambda: _KeepOpen(con))
    monkeypatch.setattr(api, "duckdb_file_lock", lambda *a: contextlib.nullcontext())
    monkeypatch.setattr(api.final_selection, "recompute_derived_columns", lambda c, key: recomputed.append(key))
    snap = api._read_edit_rows("K", [("B1", None, ["final_price_conv"]), ("NOPE", None, ["final_moq"])])
    assert [r["volume_no"] for r in snap[0]] == [1, 2] and snap[1] == []
    n = api.apply_bom_updates("K", [{"bom_item_id": "B1", "volume_no": 1, "final_price_conv": 9.0, "cpn": "HACK"}])
    assert n == 1 and recomputed == ["K"]
    rows = con.execute("SELECT volume_no, final_price_conv, cpn FROM cbom_db.cbom WHERE bom_item_id='B1' ORDER BY 1").fetchall()
    assert rows == [(1, 9.0, "C"), (2, 1.0, "C")]   # only the named volume, and cpn is not editable
    with pytest.raises(ValueError):
        api._read_edit_rows("K", [("B1", None, ["cpn"])])


def test_export_call_reaches_reporting_mcp_with_versioned_key_without_clobbering_config(api, er, monkeypatch):
    """The bridge's `config` is the reporting package's; loading tool_calling must not break or replace it."""
    import requests
    monkeypatch.setenv("CAM_MCP_HOST_CENTUM_REPORTING", "reporting.test")
    monkeypatch.setattr(er, "_call_tool", None)
    config_before = sys.modules.get("config")
    sent = []

    class Resp:
        status_code, headers, text = 200, {"mcp-session-id": "s1", "Content-Type": "application/json"}, ""
        def __init__(self, payload=None): self.payload = payload
        def raise_for_status(self): pass
        def json(self): return self.payload

    def post(url, json=None, **kw):
        sent.append((url, json))
        if json.get("method") == "tools/call":
            return Resp({"result": {"content": [{"type": "text", "text": '{"status": "success", "workbook_name": "w.xlsx"}'}]}})
        return Resp({})
    monkeypatch.setattr(requests, "post", post)
    assert er.call_reporting_export("RFQ-1__v2") == {"status": "success", "workbook_name": "w.xlsx"}
    url, payload = sent[-1]
    assert url == "http://reporting.test:8105/mcp"
    assert payload["params"] == {"name": "export_reports", "arguments": {"rfq_id": "RFQ-1__v2"}}
    assert sys.modules.get("config") is config_before
