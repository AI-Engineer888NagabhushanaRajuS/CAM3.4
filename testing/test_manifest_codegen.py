"""SPEC-020 manifest lint + Jinja2/AST codegen preview, on the REAL copied manifests (no docker, nothing executed)."""
import ast
import copy
import glob
import json
import os
import sys

import pytest
from jinja2.exceptions import SecurityError, UndefinedError
from jinja2.sandbox import SandboxedEnvironment

FR_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "fastapi-router"))
MANIFESTS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "manifests"))
sys.path.insert(0, FR_DIR)
try:
    import manifest_codegen as mc
finally:
    sys.path.remove(FR_DIR)

# glob.escape: this repo's path contains "[3.4]", which glob would read as a character class
SKILL_FILES = sorted(glob.glob(os.path.join(glob.escape(MANIFESTS), "skills", "*.json")))


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def skill1():
    return load(SKILL_FILES[0])


def errors(res):
    return [f for f in res["findings"] if f["level"] == "error"]


# ---- lint on the real manifests ----

def test_ten_skill_manifests_lint_without_errors():
    assert len(SKILL_FILES) == 10
    for p in SKILL_FILES:
        assert errors(mc.lint_manifest(load(p), "skill")) == [], p


@pytest.mark.parametrize("folder,kind", [("agent", "agent"), ("reporting", "reporting"), ("repo-approved", "approved")])
def test_other_manifest_kinds_lint_without_errors(folder, kind):
    paths = glob.glob(os.path.join(glob.escape(MANIFESTS), folder, "*.json"))
    assert paths
    for p in paths:
        assert errors(mc.lint_manifest(load(p), kind)) == [], p


@pytest.mark.parametrize("bad", ["abc", 0, -1, True, 2.5])
def test_bad_max_iterations_is_an_error(skill1, bad):
    skill1["isatvon_definition"]["v_variables"]["max_iterations"] = bad
    res = mc.lint_manifest(skill1, "skill")
    assert not res["ok"]
    assert any(f["path"].endswith("max_iterations") for f in errors(res))


def test_high_iterations_warn_and_bad_budget_errors(skill1):
    v = skill1["isatvon_definition"]["v_variables"]
    v["max_iterations"] = 11
    res = mc.lint_manifest(skill1, "skill")
    assert res["ok"] and any(f["level"] == "warning" and f["path"].endswith("max_iterations") for f in res["findings"])
    v["budget_limit"] = "soon"
    assert not mc.lint_manifest(skill1, "skill")["ok"]


def test_missing_fields_are_errors(skill1):
    isat = skill1["isatvon_definition"]
    isat["i_instructions"] = "too short"
    isat["s_source"]["required_inputs"] = []
    isat["a_automation"]["action_step"] = " "
    isat["o_outcome"]["json_schema"] = ""
    del isat["n_next"]
    skill1["sub_skills"][0]["steps"][0]["mode"] = "Maybe"
    paths = {f["path"] for f in errors(mc.lint_manifest(skill1, "skill"))}
    assert {"isatvon_definition.i_instructions", "isatvon_definition.s_source.required_inputs",
            "isatvon_definition.a_automation.action_step", "isatvon_definition.o_outcome.json_schema",
            "isatvon_definition.n_next", "sub_skills[0].steps[0].mode"} <= paths


def test_placeholders_and_unknown_tech_are_warnings_with_path(skill1):
    skill1["isatvon_definition"]["i_instructions"] = "Do the thing, details TBD from the customer"
    skill1["isatvon_definition"]["t_tech_stack"]["gateway"] = "Acme Magic Gateway"
    res = mc.lint_manifest(skill1, "skill")
    assert res["ok"]
    warn = {f["path"] for f in res["findings"] if f["level"] == "warning"}
    assert "isatvon_definition.i_instructions" in warn and "isatvon_definition.t_tech_stack.gateway" in warn


@pytest.mark.parametrize("text", ["TBD", "todo", "TBC", "Lorem ipsum", "xxx", "to be decided", "n/a", "??"])
def test_every_bam_placeholder_word_is_flagged(skill1, text):
    skill1["isatvon_definition"]["n_next"] = {"next_step": text}
    res = mc.lint_manifest(skill1, "skill")
    assert any(f["path"] == "isatvon_definition.n_next.next_step" and f["level"] == "warning" for f in res["findings"])


def test_computed_on_save_hash_is_allowed_and_garbage_is_not(skill1):
    assert skill1["governance"]["deterministic_hash"] == "sha256:COMPUTED_ON_SAVE"
    assert not [f for f in mc.lint_manifest(skill1, "skill")["findings"] if "hash" in f["message"]]
    skill1["governance"]["deterministic_hash"] = "md5:nope"
    assert any("hash" in f["message"] for f in mc.lint_manifest(skill1, "skill")["findings"])


def test_lint_rejects_non_object_and_unknown_kind():
    assert not mc.lint_manifest([], "skill")["ok"]
    assert not mc.lint_manifest({}, "wat")["ok"]


# ---- codegen on the real manifests ----

def test_all_forty_sub_skills_pass_the_ast_gate():
    n = 0
    for p in SKILL_FILES:
        doc = load(p)
        for sub in doc["sub_skills"]:
            prev = mc.build_preview(doc, sub["sub_skill_id"])
            assert prev["ok"] and prev["ast"] == {"ok": True, "errors": []}, (p, sub["sub_skill_id"], prev["ast"])
            assert len(prev["files"]) == 1
            n += 1
    assert n == 40


def test_preview_without_sub_skill_builds_every_sub_skill(skill1):
    prev = mc.build_preview(skill1)
    assert len(prev["files"]) == 4 and all(p.startswith("skills/") and p.endswith(".py") for p in prev["files"])
    assert len(prev["bundle_sha256"]) == 64


def test_generated_source_carries_the_manifest_loop(skill1):
    src = mc.render_skill_tool(skill1, "1.1")
    for needle in ("SKILL_ID = 'SKILL_01'", "SUB_SKILL_ID = '1.1'", "MAX_ITERATIONS = 3", "BUDGET_MS = 60000",
                   "class Outcome(BaseModel)", "TODO(business-logic)", "def run_loop", "while iterations < MAX_ITERATIONS",
                   "budget_exceeded", "'1.1.1'"):
        assert needle in src


def test_approved_and_reporting_manifests_render_one_tool_each():
    for folder, kind in (("repo-approved", "approved"), ("reporting", "reporting")):
        for p in glob.glob(os.path.join(glob.escape(MANIFESTS), folder, "*.json")):
            prev = mc.build_preview(load(p))
            assert prev["ok"] and len(prev["files"]) == 1, p


def test_agent_manifest_is_refused_for_codegen():
    prev = mc.build_preview(load(os.path.join(MANIFESTS, "agent", "agent_manifest.json")))
    assert not prev["ok"] and prev["files"] == {}


def test_unknown_sub_skill_is_a_finding_not_a_crash(skill1):
    prev = mc.build_preview(skill1, "99.9")
    assert not prev["ok"] and any(f["path"] == "sub_skill_id" for f in prev["findings"])


def test_lint_errors_block_codegen(skill1):
    skill1["isatvon_definition"]["v_variables"]["max_iterations"] = 0
    prev = mc.build_preview(skill1)
    assert not prev["ok"] and prev["files"] == {} and prev["bundle_sha256"] is None


# ---- determinism ----

def test_same_input_same_hash_and_changed_instruction_changes_it(skill1):
    a = mc.build_preview(copy.deepcopy(skill1))["bundle_sha256"]
    assert a == mc.build_preview(copy.deepcopy(skill1))["bundle_sha256"]
    skill1["isatvon_definition"]["i_instructions"] += " Also log every retry."
    assert mc.build_preview(skill1)["bundle_sha256"] != a


# ---- self-heal ----

def test_formula_variable_is_healed_and_reported(skill1):
    skill1["isatvon_definition"]["v_variables"]["markup"] = "=B2*1.1"
    prev = mc.build_preview(skill1, "1.1")
    assert prev["ok"] and prev["ast"]["ok"]
    assert len(prev["repairs"]) == 1 and prev["repairs"][0]["rule"] == "quote_spreadsheet_formula"
    assert prev["repairs"][0]["variables"] == ["markup"]
    assert "'markup': '=B2*1.1'" in next(iter(prev["files"].values()))


def test_the_raw_formula_pass_really_fails_the_gate(skill1):
    skill1["isatvon_definition"]["v_variables"]["markup"] = "=B2*1.1"
    raw = mc.render_skill_tool(skill1, "1.1", quote_formulas=False)
    gate = mc.ast_gate(raw)
    assert not gate["ok"] and gate["errors"][0]["message"].startswith("SyntaxError")


def test_clean_manifest_needs_no_repair(skill1):
    assert mc.build_preview(skill1, "1.1")["repairs"] == []


# ---- injection ----

NASTY = ["{{ 7*7 }}", "{% for x in y %}", "{# c #}", "it's \"quoted\"", "line1\nline2\r\nx = 1", '"""triple"""',
         "'''triple'''", "\\", "\\n\\'", "#\nimport os", "= 1\n__import__('os').system('x')", "é 漢字 \U0001F600"]


@pytest.mark.parametrize("nasty", NASTY)
def test_manifest_strings_render_as_inert_text(skill1, nasty):
    isat = skill1["isatvon_definition"]
    isat["i_instructions"] = "Real instructions long enough. " + nasty
    isat["v_variables"]["success_gate"] = nasty
    isat["v_variables"]["extra"] = nasty
    skill1["skill_metadata"]["skill_name"] = nasty
    skill1["sub_skills"][0]["sub_skill_name"] = nasty
    skill1["sub_skills"][0]["steps"][0]["action"] = nasty
    prev = mc.build_preview(skill1, "1.1")
    assert prev["ok"], prev["ast"]
    src = next(iter(prev["files"].values()))
    # the text survives verbatim as data: it is in the parsed constants, not executed
    gate = [ast.literal_eval(n.value) for n in ast.parse(src).body
            if isinstance(n, ast.Assign) and n.targets[0].id == "SUCCESS_GATE"]
    assert gate == [nasty]


def test_template_expression_is_not_evaluated(skill1):
    skill1["isatvon_definition"]["v_variables"]["success_gate"] = "{{ 7*7 }}"
    src = mc.render_skill_tool(skill1, "1.1")
    assert "SUCCESS_GATE = '{{ 7*7 }}'" in src


def test_formula_with_newline_is_never_emitted_raw(skill1):
    skill1["isatvon_definition"]["v_variables"]["evil"] = "=1\n__import__('os').system('x')"
    prev = mc.build_preview(skill1, "1.1")
    assert prev["ok"] and mc.ast_gate(next(iter(prev["files"].values())))["ok"]


# ---- the gate ----

@pytest.mark.parametrize("code", [
    "eval('1')", "exec('x=1')", "compile('x','f','exec')", "__import__('os')", "import os\nos.system('ls')",
    "import subprocess", "import socket", "from os import path", "import requests", "from . import x",
    "x = getattr(object, 'a')", "print(__builtins__)", "from fastmcp import FastMCP\nimport subprocess",
])
def test_gate_refuses_forbidden_code(code):
    res = mc.ast_gate(code)
    assert not res["ok"] and res["errors"] and all("line" in e and "message" in e for e in res["errors"])


def test_gate_accepts_allowed_code_and_reports_syntax_errors():
    assert mc.ast_gate("import json, time\nfrom pydantic import BaseModel\nfrom typing import Any\n")["ok"]
    bad = mc.ast_gate("x = (\n")
    assert not bad["ok"] and bad["errors"][0]["message"].startswith("SyntaxError")
    assert not mc.ast_gate("x = 1\x00")["ok"]


# ---- the Jinja environment ----

def test_environment_is_sandboxed_strict_and_not_autoescaped():
    assert isinstance(mc.ENV, SandboxedEnvironment)
    assert mc.ENV.autoescape is False
    with pytest.raises(SecurityError):
        mc.ENV.from_string("{{ ''.__class__.__mro__ }}").render()
    with pytest.raises(UndefinedError):
        mc.ENV.from_string("{{ nope }}").render()


def test_template_file_ships_next_to_the_module():
    assert os.path.isfile(os.path.join(FR_DIR, "templates", "skill_tool.py.j2"))


# ---- routes ----

@pytest.fixture
def api():
    from fastapi.testclient import TestClient
    sys.path.insert(0, FR_DIR)
    try:
        import duck_db_api
    finally:
        sys.path.remove(FR_DIR)
    c = TestClient(duck_db_api.app)
    h = {"Authorization": "Bearer " + duck_db_api.auth.create_token("RFQ-X")}
    return c, h, duck_db_api


def test_routes_need_a_token(api):
    c, _, _ = api
    assert c.post("/api/manifests/lint", json={"text": "{}"}).status_code == 401
    assert c.post("/api/manifests/codegen", json={"text": "{}"}).status_code == 401


def test_lint_route_on_a_real_manifest(api):
    c, h, _ = api
    text = open(SKILL_FILES[0], encoding="utf-8").read()
    r = c.post("/api/manifests/lint", json={"kind": "skill", "text": text}, headers=h)
    assert r.status_code == 200 and r.json()["ok"] is True


def test_codegen_route_returns_a_hashed_preview(api):
    c, h, _ = api
    text = open(SKILL_FILES[0], encoding="utf-8").read()
    r = c.post("/api/manifests/codegen", json={"text": text, "sub_skill_id": "1.2"}, headers=h)
    body = r.json()
    assert r.status_code == 200 and body["ok"] and len(body["files"]) == 1 and len(body["bundle_sha256"]) == 64
    assert r.json() == c.post("/api/manifests/codegen", json={"text": text, "sub_skill_id": "1.2"}, headers=h).json()


BAD_BOTH = [b"not json", b"[1]", b'{"text": 5}', b'{"text": "{bad"}', b'{"text": "NaN"}']


@pytest.mark.parametrize("payload", BAD_BOTH + [b'{"kind": "wat", "text": "{}"}'])
def test_lint_route_answers_400_for_invalid_input(api, payload):
    c, h, _ = api
    r = c.post("/api/manifests/lint", content=payload, headers={**h, "Content-Type": "application/json"})
    assert r.status_code == 400 and "detail" in r.json(), r.text


@pytest.mark.parametrize("payload", BAD_BOTH + [b'{"text": "[1]"}'])
def test_codegen_route_answers_400_for_invalid_input(api, payload):
    c, h, _ = api
    r = c.post("/api/manifests/codegen", content=payload, headers={**h, "Content-Type": "application/json"})
    assert r.status_code == 400 and "detail" in r.json(), r.text


def test_routes_answer_413_for_oversize_body(api):
    c, h, _ = api
    big = json.dumps({"text": "x" * (512 * 1024 + 1)})
    for path in ("/api/manifests/lint", "/api/manifests/codegen"):
        assert c.post(path, content=big, headers={**h, "Content-Type": "application/json"}).status_code == 413


def test_deeply_nested_json_is_a_400_not_a_trace(api):
    c, h, _ = api
    deep = "[" * 100_000 + "]" * 100_000
    r = c.post("/api/manifests/codegen", json={"text": deep}, headers=h)
    assert r.status_code == 400
