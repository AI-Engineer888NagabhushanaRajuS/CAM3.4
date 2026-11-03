"""Intake tools (scan_local_file, import_bom) in the 3.4 compose stack.

Each case below was found by running the tool against the real intake container:
 1. scan_local_file ran a hard-coded Windows ClamAV path, so in a Linux container every file FAILED.
 2. its telemetry write used `ON CONFLICT (rfq_id)`; the versioned rfq_process_tracking table (PK
    rfq_id+version, partial unique index) cannot match it, Postgres raised, the error was swallowed,
    and every scan_status stayed PENDING.
 3. import_bom wrote to the reporting input DB, which has no processed_bom_items table. In 3.3 the
    intake, distributor and gerber servers shared one bom_storage.duckdb (shared.db_config.DB_PATH).
"""
import contextlib
import importlib.util
import json
import os
import subprocess
import sys
import types

import duckdb
import pandas as pd
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
INTAKE = os.path.join(ROOT, "mcp-tools", "intake")
WINDOWS_CLAMSCAN = "C:\\Program Files\\ClamAV\\clamscan.exe"


@contextlib.contextmanager
def _overlay(mods):
    saved = {k: sys.modules.get(k) for k in mods}
    sys.modules.update(mods)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def _load(name, path, overlay=None):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    with _overlay(overlay or {}):
        spec.loader.exec_module(mod)
    return mod


class FakeFileMetadataDb:
    """Stands in for call_tool(): serves the PENDING rows, and rejects the statement Postgres rejects."""

    def __init__(self, files):
        self.files, self.sql = files, []

    def __call__(self, tool_name, arguments):
        sql = arguments["sql"]
        self.sql.append(sql)
        if "scan_status = 'PENDING'" in sql:
            return {"result": {"content": [{"text": repr(self.files)}]}}
        if "ON CONFLICT (rfq_id)" in sql:
            raise RuntimeError("there is no unique or exclusion constraint matching the ON CONFLICT specification")
        return {"result": {"content": [{"text": "[]"}]}}


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    mod.__dict__.update(attrs)
    return mod


def _intake_server():
    stubs = {  # the server's sibling modules; scan_local_file needs none of their behaviour
        "magic": _stub("magic", from_file=lambda path, mime=True: "application/vnd.ms-excel"),
        "bom_to_database": _stub("bom_to_database", process_bom_to_database=None,
                                 process_bom_structure_to_database=None),
        "bom_processing": _stub("bom_processing", process_bom=None),
        "tool_calling": _stub("tool_calling", call_tool=None),
    }
    return _load("intake_mcp_server_under_test", os.path.join(INTAKE, "mcp_server.py"), stubs)


def _scan(mod, monkeypatch, tmp_path, returncode=0):
    target = tmp_path / "bom.xlsx"
    target.write_bytes(b"x")
    mod.call_tool = FakeFileMetadataDb([{"file_id": "11", "file_path": str(target)}])
    argv_seen = []

    def fake_run(argv, **kwargs):
        argv_seen.append(argv)
        return subprocess.CompletedProcess(argv, returncode, "", "")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    out = json.loads(mod.scan_local_file("RFQ-T"))
    return out, mod.call_tool.sql, argv_seen


def test_scan_runs_the_scanner_named_by_the_environment(tmp_path, monkeypatch):
    mod = _intake_server()
    monkeypatch.setenv("CLAMSCAN_PATH", "/usr/bin/clamscan")
    _, _, argv_seen = _scan(mod, monkeypatch, tmp_path)
    assert argv_seen[0][0] == "/usr/bin/clamscan"


def test_scan_default_scanner_is_still_the_3_3_windows_path(tmp_path, monkeypatch):
    mod = _intake_server()
    monkeypatch.delenv("CLAMSCAN_PATH", raising=False)
    _, _, argv_seen = _scan(mod, monkeypatch, tmp_path)
    assert argv_seen[0][0] == WINDOWS_CLAMSCAN


def test_scan_results_reach_rfq_file_telemetry(tmp_path, monkeypatch):
    mod = _intake_server()
    monkeypatch.setenv("CLAMSCAN_PATH", "/usr/bin/clamscan")
    out, sql, _ = _scan(mod, monkeypatch, tmp_path)
    assert out["file_records"][0]["scan_status"] == "CLEAN"
    updates = [s for s in sql if s.lstrip().startswith("UPDATE rfq_file_telemetry")]
    assert len(updates) == 1 and "scan_status = 'CLEAN'" in updates[0], sql
    assert not any("ON CONFLICT (rfq_id)" in s for s in sql), "needs a key the versioned table has"


def test_scan_leaves_the_stage_to_the_router(tmp_path, monkeypatch):
    # fastapi_router advances rfq_process_stage after a tool succeeds; a second advance here would
    # skip a step when the run is resumed from skill_index.
    mod = _intake_server()
    monkeypatch.setenv("CLAMSCAN_PATH", "/usr/bin/clamscan")
    _, sql, _ = _scan(mod, monkeypatch, tmp_path)
    assert not any("rfq_process_stage" in s for s in sql if "rfq_process_tracking" in s), sql


@pytest.mark.parametrize("server", ["intake", "distributor-pricing", "gerber-integration"])
def test_rfq_flow_servers_share_bom_storage_db(server, monkeypatch):
    path = os.path.join(ROOT, "mcp-tools", server, "config.py")
    monkeypatch.delenv("BOM_STORAGE_DB", raising=False)
    assert os.path.basename(_load(f"cfg_{server}", path).DB_PATH) == "bom_storage.duckdb"
    monkeypatch.setenv("BOM_STORAGE_DB", "/data/other.duckdb")
    assert _load(f"cfg_{server}_env", path).DB_PATH == "/data/other.duckdb"


def test_process_bom_to_database_creates_the_table_it_writes(tmp_path):
    cfg = _load("intake_config_under_test", os.path.join(INTAKE, "config.py"))
    b2d = _load("intake_bom_to_database_under_test", os.path.join(INTAKE, "bom_to_database.py"), {"config": cfg})
    b2d.DB_PATH = str(tmp_path / "bom_storage.duckdb")  # a fresh file: no setup script has run
    df = pd.DataFrame([{
        "fg": "F1", "cpn": "C-1", "description": "cap", "mfr": "M", "mpn": "P-1", "commodity": "cap",
        "bom_qty": 2.0, "volume": 10.0, "required_qty": 20.0, "uom": "EA",
    }])
    out = b2d.process_bom_to_database("RFQ-T", str(tmp_path / "bom.xlsx"), df)
    assert out == {"status": "success", "rows_inserted": 1}
    with duckdb.connect(b2d.DB_PATH) as conn:
        assert conn.execute("SELECT COUNT(*) FROM processed_bom_items WHERE rfq_id = 'RFQ-T'").fetchone()[0] == 1
