"""
SPEC-013: manifest importer, registry writer, tool->server routing.

Modules are loaded by file path under unique names (several packages here ship
a module called `config`). The registry writer is tested against a throwaway
local PostgreSQL cluster (initdb/pg_ctl in a temp dir, trust auth, loopback only);
those tests skip when the binaries are missing. The registry DDL is NOT available
locally; the schema below follows Reference[KT] docs/Database/logic-database.md (not re-verified live).
"""
import copy
import glob
import importlib.util
import json
import os
import shutil
import socket
import subprocess

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
MANIFESTS = os.path.join(ROOT, "manifests")


def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, relpath))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _manifest_paths():
    # os.listdir, not glob: this repo's path contains "[3.4]", a glob character class.
    paths = sorted(os.path.join(MANIFESTS, f) for f in os.listdir(MANIFESTS) if f.endswith(".json"))
    assert len(paths) >= 6, f"expected the 6 shipped manifests, found {paths}"
    return paths


def _manifest(mid):
    with open(os.path.join(MANIFESTS, f"{mid}.json"), encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def cfg():
    return _load("cam_router_config", "fastapi-router/config.py")


@pytest.fixture(scope="module")
def im():
    return _load("cam_import_manifest", "scripts/import_manifest.py")


# --- routing: a manifest owns its tools ------------------------------------

def test_every_manifest_tool_routes_to_its_own_server(cfg):
    wrong = []
    for path in _manifest_paths():
        m = json.load(open(path, encoding="utf-8"))
        for t in m["tools"]:
            if f":{m['port']}/mcp" not in cfg.get_mcp_url(t["name"]):
                wrong.append((m["id"], t["name"]))
    assert not wrong, f"tools routed to another manifest's server: {wrong}"


def test_tool_not_in_any_manifest_raises(cfg):
    with pytest.raises(ValueError):
        cfg.get_mcp_url("Production_Logic_DB-execute_sql")


def test_manifest_stored_after_startup_resolves_without_restart(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "_MANIFESTS_DIR", tmp_path)
    with pytest.raises(ValueError):
        cfg.get_mcp_url("late_tool__run")
    (tmp_path / "late.json").write_text(json.dumps(
        {"id": "late", "port": 8999, "tools": [{"name": "late_tool__run"}]}), encoding="utf-8")
    assert cfg.get_mcp_url("late_tool__run").endswith(":8999/mcp")


def test_repeated_miss_does_not_reparse_when_manifests_unchanged(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "_MANIFESTS_DIR", tmp_path)
    calls = []
    real = cfg._load_manifests
    monkeypatch.setattr(cfg, "_load_manifests", lambda: (calls.append(1), real())[1])
    for _ in range(3):
        with pytest.raises(ValueError):
            cfg.get_mcp_url("nope__x")
    assert len(calls) == 1


# --- strict shape ----------------------------------------------------------

def test_shipped_manifests_pass_strict_shape(im):
    for path in _manifest_paths():
        m = json.load(open(path, encoding="utf-8"))
        assert im.check_shape(m) == [], os.path.basename(path)


def _mut(fn):
    def apply(m):
        fn(m)
        return m
    return apply


BAD = {
    "missing port": _mut(lambda m: m.pop("port")),
    "no tools and no planned_tools": _mut(lambda m: m.update(tools=[])),
    "path-ish id": _mut(lambda m: m.update(id="../x")),
    "port zero": _mut(lambda m: m.update(port=0)),
    "port as string": _mut(lambda m: m.update(port="8002")),
    "bad version": _mut(lambda m: m.update(version="v3")),
    "tool without prefix": _mut(lambda m: m["tools"][0].update(name="scan_local_file")),
    "duplicate tool": _mut(lambda m: m["tools"].append(copy.deepcopy(m["tools"][0]))),
    "server escapes repo": _mut(lambda m: m.update(mcp_server="../../etc/passwd")),
    "absolute server": _mut(lambda m: m.update(mcp_server="C:/Windows/win.ini")),
    "tool not in server": _mut(lambda m: m["tools"][0].update(name="centum_intake__nope")),
    "tool owned by another manifest": _mut(
        lambda m: m["tools"][0].update(name=_manifest("centum_reporting")["tools"][0]["name"])),
    "port owned by another manifest": _mut(lambda m: m.update(port=_manifest("centum_reporting")["port"])),
}


@pytest.mark.parametrize("label", sorted(BAD))
def test_bad_manifest_rejected(im, label):
    m = BAD[label](copy.deepcopy(_manifest("centum_intake")))
    assert im.check_shape(m), label


# --- hash + store ----------------------------------------------------------

def test_hash_ignores_key_order(im):
    m = _manifest("centum_intake")
    shuffled = dict(reversed(list(m.items())))
    assert im.canonical_hash(m) == im.canonical_hash(shuffled)


def test_store_created_unchanged_updated(im, tmp_path):
    m = copy.deepcopy(_manifest("centum_intake"))
    first = im.store_manifest(m, tmp_path)
    assert first["status"] == "created" and (tmp_path / "centum_intake.json").exists()
    assert im.store_manifest(m, tmp_path)["status"] == "unchanged"
    m["description"] = "changed"
    third = im.store_manifest(m, tmp_path)
    assert third["status"] == "updated" and third["sha256"] != first["sha256"]


# --- jungle command (never executed here) ----------------------------------

def test_jungle_argv_uses_tool_prefix_not_manifest_id(im):
    argv = im.jungle_register_argv(_manifest("centum_scrub_intake"), "http://reg:8080", "10.0.0.5")
    assert argv == ["mcpjungle", "--registry", "http://reg:8080", "register", "--name", "centum_intake",
                    "--transport", "streamable_http", "--url", "http://10.0.0.5:8004/mcp"]


def test_jungle_argv_refuses_mixed_prefixes(im):
    m = copy.deepcopy(_manifest("centum_intake"))
    m["tools"][0]["name"] = "other__scan_local_file"
    with pytest.raises(ValueError):
        im.jungle_register_argv(m, "http://reg:8080", "h")


# --- registry writer on a real (scratch) Postgres ---------------------------

def _pg_bin():
    for d in sorted(glob.glob(r"C:\Program Files\PostgreSQL\*\bin"), reverse=True):
        if os.path.exists(os.path.join(d, "initdb.exe")):
            return d
    exe = shutil.which("initdb")
    return os.path.dirname(exe) if exe else None


@pytest.fixture(scope="module")
def pg_dsn(tmp_path_factory):
    bindir = _pg_bin()
    if not bindir:
        pytest.skip("PostgreSQL binaries not found")
    data = str(tmp_path_factory.mktemp("pgdata"))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    run = lambda exe, *a: subprocess.run([os.path.join(bindir, exe), *a], check=True,
                                         capture_output=True, text=True, timeout=120)
    run("initdb", "-D", data, "-U", "postgres", "-A", "trust", "-E", "UTF8", "--no-sync")
    # No pipes for `start`: the postgres child inherits them and subprocess.run would wait forever.
    subprocess.run([os.path.join(bindir, "pg_ctl"), "-D", data, "-o", f"-p {port} -c listen_addresses=127.0.0.1",
                    "-w", "-l", os.path.join(data, "log.txt"), "start"], check=True, timeout=120,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    yield f"host=127.0.0.1 port={port} user=postgres dbname=postgres"
    subprocess.run([os.path.join(bindir, "pg_ctl"), "-D", data, "-m", "immediate", "stop"],
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)


NEW = [{"name": "centum_reporting__new_tool", "description": "Does a thing. More text.", "skill_code": "M03.11_NewTool",
        "skill_index": 5, "macro_category_name": "reportingAnalytics"}]


@pytest.fixture
def conn(pg_dsn):
    import psycopg2
    c = psycopg2.connect(pg_dsn)
    with c, c.cursor() as cur:
        cur.execute("""
            DROP TABLE IF EXISTS system_skills_registry, quote_routing_profiles;
            CREATE TABLE quote_routing_profiles (
                profile_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), profile_name varchar NOT NULL UNIQUE,
                routing_sequence jsonb NOT NULL, created_at timestamp DEFAULT CURRENT_TIMESTAMP,
                updated_at timestamp DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE system_skills_registry (
                skill_code varchar PRIMARY KEY, skill_index integer NOT NULL UNIQUE, skill_name varchar NOT NULL,
                macro_category_name varchar NOT NULL, mcp_tool_name varchar NOT NULL,
                input_template jsonb NOT NULL DEFAULT '{}'::jsonb, requires_llm boolean DEFAULT false,
                is_active boolean DEFAULT true, created_at timestamp DEFAULT CURRENT_TIMESTAMP, macro_category integer);
            INSERT INTO quote_routing_profiles (profile_name, routing_sequence) VALUES
              ('Standard_BOM_Flow', '["centum_intake__standardize_scrub_bom","centum_reporting__cbom"]'),
              ('RFQ_Flow', '["other__x"]');
            -- like the documented live data: inactive skills sit at the indexes right after the live sequence
            INSERT INTO system_skills_registry (skill_code, skill_index, skill_name, macro_category_name, mcp_tool_name, is_active) VALUES
              ('M03.1_Scrub', 1, 'Scrub', 'intake', 'centum_intake__standardize_scrub_bom', true),
              ('M03.4_Cbom', 2, 'CBOM', 'pricingConsolidation', 'centum_reporting__cbom', true),
              ('M03.9_Erp', 3, 'ERP', 'erpDataSync', 'centum_intake__standardize_erp', false),
              ('X_Other', 99, 'Other', 'other', 'other__x', true);
        """)
    yield c
    c.close()


def _state(conn):
    with conn, conn.cursor() as cur:
        cur.execute("SELECT routing_sequence FROM quote_routing_profiles WHERE profile_name='Standard_BOM_Flow'")
        seq = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM system_skills_registry")
        return seq, cur.fetchone()[0]


def test_apply_adds_once_and_is_idempotent(im, conn, tmp_path):
    r = im.register_tools(conn, "Standard_BOM_Flow", NEW, apply=True, receipt_dir=tmp_path)
    assert r["changed"] and r["added_registry"] == ["centum_reporting__new_tool"]
    seq, n = _state(conn)
    assert seq[-1] == "centum_reporting__new_tool" and n == 5
    with conn, conn.cursor() as cur:  # stored exactly as given, documented columns filled
        cur.execute("SELECT skill_code, skill_index, skill_name, macro_category_name, is_active "
                    "FROM system_skills_registry WHERE mcp_tool_name=%s", ("centum_reporting__new_tool",))
        assert cur.fetchone() == ("M03.11_NewTool", 5, "Does a thing", "reportingAnalytics", True)
    assert os.listdir(tmp_path), "receipt must be written when something changed"
    again = im.register_tools(conn, "Standard_BOM_Flow", NEW, apply=True, receipt_dir=tmp_path)
    assert not again["changed"] and _state(conn) == (seq, n)


def test_dry_run_changes_nothing_but_reports_the_plan(im, conn, tmp_path):
    before = _state(conn)
    r = im.register_tools(conn, "Standard_BOM_Flow", NEW, apply=False, receipt_dir=tmp_path)
    assert r["changed"] and r["dry_run"] and _state(conn) == before
    assert not os.listdir(tmp_path)


def test_index_held_by_inactive_skill_refused_and_nothing_written(im, conn, tmp_path):
    before = _state(conn)
    with pytest.raises(ValueError, match="skill_index 3"):  # the documented live case: skills 9-10 are inactive ERP
        im.register_tools(conn, "Standard_BOM_Flow", [dict(NEW[0], skill_index=3)], apply=True, receipt_dir=tmp_path)
    assert _state(conn) == before


@pytest.mark.parametrize("field", ["skill_code", "skill_index", "macro_category_name"])
def test_missing_registry_field_rejected_before_any_write(im, conn, tmp_path, field):
    before = _state(conn)
    bad = {k: v for k, v in NEW[0].items() if k != field}
    with pytest.raises(ValueError, match=field):
        im.register_tools(conn, "Standard_BOM_Flow", [bad], apply=True, receipt_dir=tmp_path)
    assert _state(conn) == before


def test_failure_on_second_tool_rolls_back_the_first(im, conn, tmp_path):
    before = _state(conn)
    second = {"name": "centum_reporting__second", "skill_code": "M03.12_Second", "skill_index": 3,
              "macro_category_name": "reportingAnalytics"}  # index 3 is taken -> fails after the first insert
    with pytest.raises(ValueError):
        im.register_tools(conn, "Standard_BOM_Flow", NEW + [second], apply=True, receipt_dir=tmp_path)
    assert _state(conn) == before and not os.listdir(tmp_path)


def test_unknown_profile_and_hostile_names_rejected(im, conn, tmp_path):
    with pytest.raises(ValueError):
        im.register_tools(conn, "No_Such_Profile", NEW, apply=True, receipt_dir=tmp_path)
    evil = [{"name": "x__y'; DROP TABLE system_skills_registry;--"}]
    with pytest.raises(ValueError):
        im.register_tools(conn, "Standard_BOM_Flow", evil, apply=True, receipt_dir=tmp_path)
    assert _state(conn)[1] == 4


def test_rollback_removes_only_what_was_added(im, conn, tmp_path):
    r = im.register_tools(conn, "Standard_BOM_Flow", NEW, apply=True, receipt_dir=tmp_path)
    with conn, conn.cursor() as cur:  # a concurrent edit (e.g. Skills Settings) after our apply
        cur.execute("""UPDATE quote_routing_profiles SET routing_sequence = routing_sequence || '"late__edit"'::jsonb
                       WHERE profile_name='Standard_BOM_Flow'""")
    im.rollback_receipt(conn, r)
    seq, n = _state(conn)
    assert seq == r["previous_routing_sequence"] + ["late__edit"] and n == 4
    im.rollback_receipt(conn, r)  # idempotent
    assert _state(conn) == (seq, n)


def test_verify_reports_missing_and_passes_after_apply(im, conn, tmp_path):
    names = ["centum_reporting__new_tool"]
    assert len(im.verify_registration(conn, "Standard_BOM_Flow", names)) == 2  # no row, not in sequence
    im.register_tools(conn, "Standard_BOM_Flow", NEW, apply=True, receipt_dir=tmp_path)
    assert im.verify_registration(conn, "Standard_BOM_Flow", names) == []


def test_rollback_keeps_registry_row_another_profile_uses(im, conn, tmp_path):
    r = im.register_tools(conn, "Standard_BOM_Flow", NEW, apply=True, receipt_dir=tmp_path)
    with conn, conn.cursor() as cur:  # RFQ_Flow adopts the same tool after our apply
        cur.execute("""UPDATE quote_routing_profiles SET routing_sequence = routing_sequence || '"centum_reporting__new_tool"'::jsonb
                       WHERE profile_name='RFQ_Flow'""")
    im.rollback_receipt(conn, r)
    assert im.verify_registration(conn, "RFQ_Flow", ["centum_reporting__new_tool"]) == []
