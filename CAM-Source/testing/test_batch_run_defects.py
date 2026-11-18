"""Defects found by the 25-batch run on 2026-11-18, each with the input that showed it.

1. B07, B10: an empty price-source confirm posted while the run waited at the EARLIER intake gate advanced the stage past the
   review, the resume started at generate_reports, and CBOM, enrichment and the review were skipped ("No cbom rows found").
2. B07: Idemia's numeric CPNs read as 143608336.0 from the BOM and '143608336' from the QuoteWin, so a QuoteWin sharing
   175 of 208 parts was refused as having none of them, and the run stopped waiting for a QuoteWin.
3. B10: 'Could not set lock on file input_db.duckdb: Conflicting lock is held' failed the SCRUB BOM step at once instead of
   waiting for the other reader.
"""
import os
import sys
import types

import openpyxl
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FR = os.path.join(ROOT, "fastapi-router")
SEQ = ["centum_intake__standardize_scrub_bom", "centum_intake__standardize_quote_win", "centum_intake__standardize_costing_sheet",
       "centum_reporting__feasibility_risk", "centum_reporting__cbom", "centum_reporting__enrich_costing_sheet",
       "centum_reporting__resolve_final_selection", "centum_reporting__generate_reports", "centum_reporting__export_reports"]


# ---- 1. the price-source review only accepts a decision while the run is AT it -------------------------------------------

def _hitl(monkeypatch, stage):
    sys.path.insert(0, FR)
    try:
        import hitl_router as hr
    except ImportError as e:
        pytest.skip(f"hitl_router deps unavailable: {e}")
    finally:
        sys.path.remove(FR)
    monkeypatch.setenv("CAM_USE_TEMPORAL", "false")
    monkeypatch.setattr(hr, "get_routing_sequence", lambda profile="Standard_BOM_Flow": SEQ)
    if isinstance(stage, Exception):
        def boom(rfq_id):
            raise stage
        monkeypatch.setattr(hr, "get_current_skill_index", boom)
    else:
        monkeypatch.setattr(hr, "get_current_skill_index", lambda rfq_id: stage)
    advanced = []
    monkeypatch.setattr(hr, "_advance_past_resolve_final_selection", lambda rfq_id: advanced.append(rfq_id) or 7)
    monkeypatch.setattr(hr, "_resolve_cbom_key", lambda rfq_id: rfq_id)

    class Cur:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, *a, **k): pass
        def fetchone(self): return (0,)

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def cursor(self): return Cur()
        def commit(self): pass

    monkeypatch.setattr(hr, "get_logic_connection", lambda: Conn())
    hr.app.dependency_overrides[hr.auth.verify_token] = lambda: {"rfq_id": "B07-CE-005600"}
    from fastapi.testclient import TestClient
    return hr, TestClient(hr.app), advanced


@pytest.mark.parametrize("stage", [0, 1, 5])
def test_a_confirm_before_the_review_records_nothing(monkeypatch, stage):
    hr, client, advanced = _hitl(monkeypatch, stage)
    try:
        r = client.post("/api/rfq/B07-CE-005600/final-selection", json={"resolutions": []})
        assert r.status_code == 409, r.text
        assert SEQ[stage] in r.json()["detail"]
        assert advanced == []          # the stage did not move: nothing can be skipped
    finally:
        hr.app.dependency_overrides.clear()


def test_a_confirm_at_the_review_still_advances(monkeypatch):
    hr, client, advanced = _hitl(monkeypatch, 6)
    try:
        r = client.post("/api/rfq/B07-CE-005600/final-selection", json={"resolutions": []})
        assert r.status_code == 200 and r.json()["fully_approved"] is True
        assert advanced == ["B07-CE-005600"]
    finally:
        hr.app.dependency_overrides.clear()


def test_a_repeated_confirm_after_the_review_is_a_no_op(monkeypatch):
    hr, client, advanced = _hitl(monkeypatch, 8)
    try:
        r = client.post("/api/rfq/B07-CE-005600/final-selection", json={"resolutions": []})
        assert r.status_code == 200 and r.json()["resolved_count"] == 0 and r.json()["signal_delivered"] is None
        assert advanced == []
    finally:
        hr.app.dependency_overrides.clear()


def test_an_unknown_position_keeps_the_old_behaviour(monkeypatch):
    hr, client, advanced = _hitl(monkeypatch, RuntimeError("database down"))
    try:
        r = client.post("/api/rfq/B07-CE-005600/final-selection", json={"resolutions": []})
        assert r.status_code == 200 and advanced == ["B07-CE-005600"]
    finally:
        hr.app.dependency_overrides.clear()


# ---- 2. part numbers compare the way the pipeline stores them --------------------------------------------------------------

def _ic():
    sys.path.insert(0, FR)
    try:
        import input_check
        return input_check
    finally:
        sys.path.remove(FR)


def test_numeric_part_numbers_match_their_text_form(tmp_path):
    ic = _ic()
    bom = tmp_path / "bom.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "SCRUB BOM"
    ws.append(["FG", "Level", "CPN", "MPN", "Quantity"])
    for cpn in (143608336, 179078129.0, "R-100"):
        ws.append(["FG-1", 1, cpn, "X", 1])
    wb.save(bom)
    qw = tmp_path / "qw.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Part Number", "Mfg Part Number", "Commodity"])
    ws.append(["143608336", "A1", "RES"])
    ws.append(["179078129", "A2", "CAP"])
    ws.append(["OTHER-9", "A3", "CAP"])
    wb.save(qw)
    m = ic.quotewin_match(str(bom), str(qw))
    assert m["known"] and m["shared"] == 2 and m["bom_parts"] == 3


@pytest.mark.parametrize("value,text", [(143608336.0, "143608336"), (12, "12"), (1.5, "1.5"), (" ab-1 ", "AB-1"), ("0012", "0012")])
def test_part_text(value, text):
    assert _ic()._part_text(value) == text


# ---- 3. a DuckDB file lock held by another process is waited out ----------------------------------------------------------

def test_connect_db_waits_for_a_lock_then_connects(monkeypatch, tmp_path):
    sys.path.insert(0, os.path.join(ROOT, "mcp-tools", "scrub-intake"))
    try:
        import scrub_bom_to_database as sb
    finally:
        sys.path.pop(0)
    import duckdb
    calls = {"n": 0}
    real = duckdb.connect

    def flaky(path, read_only=False):
        calls["n"] += 1
        if calls["n"] < 3:
            raise duckdb.IOException('Could not set lock on file "input_db.duckdb": Conflicting lock is held in PID 0')
        return real(path, read_only=read_only)

    monkeypatch.setattr(sb.duckdb, "connect", flaky)
    monkeypatch.setattr("time.sleep", lambda s: None)
    con = sb.connect_db(tmp_path / "x.duckdb")
    assert calls["n"] == 3
    con.close()


def test_connect_db_raises_other_errors_at_once(monkeypatch, tmp_path):
    sys.path.insert(0, os.path.join(ROOT, "mcp-tools", "scrub-intake"))
    try:
        import scrub_bom_to_database as sb
    finally:
        sys.path.pop(0)
    import duckdb

    def broken(path, read_only=False):
        raise duckdb.IOException("Cannot open file: permission denied")

    monkeypatch.setattr(sb.duckdb, "connect", broken)
    with pytest.raises(duckdb.IOException):
        sb.connect_db(tmp_path / "x.duckdb")


# ---- 4. the worker waits longer for a tool than the router does, and less than the workflow allows ----------------------

def test_tool_timeouts_are_ordered(monkeypatch):
    import importlib
    import re
    monkeypatch.delenv("CAM_TOOL_HTTP_TIMEOUT", raising=False)
    monkeypatch.delenv("TOOL_CALL_TIMEOUT", raising=False)
    sys.path.insert(0, os.path.join(ROOT, "temporal_worker"))
    try:
        import config
        worker_wait = importlib.reload(config).TOOL_HTTP_TIMEOUT
    finally:
        sys.path.pop(0)
    router = open(os.path.join(FR, "tool_calling.py"), encoding="utf-8").read()
    router_limit = int(re.search(r'TOOL_CALL_TIMEOUT", "(\d+)"', router).group(1))
    wf = open(os.path.join(ROOT, "temporal_worker", "workflow.py"), encoding="utf-8").read()
    activity_limit = int(re.search(r"execute_tool,.*?start_to_close_timeout=timedelta\(minutes=(\d+)\)", wf, re.S).group(1)) * 60
    assert router_limit < worker_wait < activity_limit, (router_limit, worker_wait, activity_limit)
    acts = open(os.path.join(ROOT, "temporal_worker", "activities.py"), encoding="utf-8").read()
    assert "timeout=config.TOOL_HTTP_TIMEOUT" in acts


# ---- 5. delivered values agree with native Excel (B17, checked against Excel's own full recalculation) --------------------

def test_empty_text_is_not_zero_in_the_engine_check():
    sys.path.insert(0, os.path.join(ROOT, "mcp-tools", "shared"))
    try:
        import formula_verify as fv
        fe, _ = fv._engine()
    finally:
        sys.path.pop(0)
    assert not fv.same(fe, "", 0)          # LibreOffice's 0 for an empty-text result is replaced by ""
    assert not fv.same(fe, "", 0.0)
    assert fv.same(fe, "", None) and fv.same(fe, "", "")
    assert fv.same(fe, fe.BLANK, 0)        # a reference to an EMPTY cell still shows 0 in Excel


def test_is_mpn_same_compares_exactly():
    src = open(os.path.join(ROOT, "mcp-tools", "reporting", "superset", "reports", "cbom_vl.py"), encoding="utf-8").read()
    assert 'COUNTIFS($G$' not in src       # a "<>"&G criterion is date-coerced by Excel ("3-1953" -> March 1953)
    assert src.count("SUMPRODUCT(($C${first_data_row}:$C${last_data_row}=$C") == 2


# ---- 6. a Settings / Batch sheet column without a header is not a volume ---------------------------------------------------

def test_blank_header_columns_and_rows_without_fg_are_ignored():
    import pandas as pd
    sys.path.insert(0, os.path.join(ROOT, "mcp-tools", "scrub-intake"))
    try:
        sys.modules.setdefault("ollama", types.ModuleType("ollama"))
        import scrub_bom_processing as sp
    finally:
        sys.path.pop(0)
    # batch-04's Settings sheet: FG / V1 Qty, plus a stray 21.33 in E3 with no header and no FG
    vol = pd.DataFrame({"FG": ["681H33271", None], "V1 Qty": [256.0, None], "Unnamed: 2": [None, None], "Unnamed: 4": [None, 21.33]})
    out = sp.process_volume_sheet(vol)
    assert out.to_dict("records") == [{"fg": "681H33271", "volume_name": "V1", "batch_qty": 256.0}]
    bat = pd.DataFrame({"FG": ["681H33271", ""], "V1 Batch Qty": [256.0, 9], "Unnamed: 3": [None, 5]})
    assert sp.process_batch_sheet(bat).to_dict("records") == [{"fg": "681H33271", "volume": "V1", "batch_qty": 256.0}]


# ---- 7. an export that raises closes its DuckDB connection ----------------------------------------------------------------

def test_export_closes_its_connection_when_it_raises(monkeypatch):
    src = open(os.path.join(ROOT, "mcp-tools", "reporting", "superset", "exporter.py"), encoding="utf-8").read()
    head = src.split("def export_excel(rfq_id):", 1)[1].split("\ndef ", 1)[0]
    assert "try:" in head and "finally:" in head and "con.close()" in head
    db = open(os.path.join(ROOT, "mcp-tools", "reporting", "superset", "database.py"), encoding="utf-8").read()
    assert db.count("ATTACH IF NOT EXISTS") == 2
