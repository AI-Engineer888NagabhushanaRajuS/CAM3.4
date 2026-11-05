"""ISATVON manifest lint + manifest -> FastMCP skeleton codegen (SPEC-020, port of BAM's rules).

Pipeline: lint_manifest -> render_skill_tool (sandboxed Jinja2) -> ast_gate -> self-heal -> hashed bundle.
Preview only: nothing here executes generated code or writes to disk.
Ported from BAM-full-ui Frontend/src/api/mock.ts (validateField, REGISTRY, renderSkill shape, activity D) and
tests/test_isatvon_edge_cases.py (PLACEHOLDER_PATTERN). BAM's own versions are stand-ins; this is the real thing.
"""
import ast
import hashlib
import json
import keyword
import re
from pathlib import Path

from jinja2 import FileSystemLoader, StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

KINDS = ("agent", "skill", "reporting", "approved")

# BAM's REGISTRY plus what this repo really runs (read from the manifests and requirements.txt).
REGISTRY = ["fastmcp", "dbhub", "apache superset", "superset", "openpyxl", "duckdb", "postgresql", "pydantic",
            "jinja2", "cognee", "bifrost", "temporal", "promptfoo", "pandas", "cadquery", "opencascade",
            "bullm dmr", "repel", "clamav", "posthog", "paddleocr", "uppy", "tusd", "mcp jungle", "dify",
            "refine", "ag grid"]

# BAM's PLACEHOLDER_PATTERN, unchanged.
PLACEHOLDER = re.compile(r"\b(TBD|TODO|TBC|lorem|xxx|to be (decided|confirmed)|n/a)\b|\?\?", re.IGNORECASE)
HASH_OK = re.compile(r"^sha256:(COMPUTED_ON_SAVE|TO_BE_COMPUTED_ON_SAVE|[0-9a-f]{64})$")
BUDGET = re.compile(r"^\s*(\d+)\s*(ms|s|m|h)\b")
BUDGET_UNIT_MS = {"ms": 1, "s": 1000, "m": 60_000, "h": 3_600_000}
MAX_ITERATIONS_WARN = 10  # BAM's SRI bound

ALLOWED_IMPORTS = {"fastmcp", "pydantic", "typing", "json", "time", "dataclasses", "hashlib", "datetime", "re",
                   "duckdb", "openpyxl"}
# Names that reach code execution, processes, the network or interpreter internals.
FORBIDDEN_NAMES = {"eval", "exec", "compile", "__import__", "__builtins__", "subprocess", "socket", "os",
                   "globals", "locals", "getattr", "setattr", "delattr", "breakpoint"}

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def pystr(value):
    """repr() is always a valid single-line Python literal: quotes, newlines and triple quotes cannot break out."""
    return repr(str(value))


def pyval(value, quote_formulas=True):
    # BAM's template emits a '=...' spreadsheet formula raw; that is the SyntaxError the self-heal below repairs.
    if isinstance(value, str) and value.startswith("=") and not quote_formulas and "\n" not in value and "\r" not in value:
        return value
    return repr(value)


# Sandboxed: a template (or a manifest value) cannot reach __class__, os, etc. Strict: a missing key is an error.
ENV = SandboxedEnvironment(loader=FileSystemLoader(str(TEMPLATE_DIR)), undefined=StrictUndefined,
                           autoescape=False, trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True)
ENV.filters["pystr"] = pystr
ENV.filters["pyval"] = pyval


# ---------------------------------------------------------------- lint

def _norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _known_tech(entry):
    n = _norm(entry)
    return any(_norm(r) in n for r in REGISTRY)


def _text(v):
    return isinstance(v, str) and bool(v.strip())


def _strings(node, path=""):
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from _strings(v, f"{path}.{k}" if path else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _strings(v, f"{path}[{i}]")


def _budget_ms(s):
    m = BUDGET.match(s) if isinstance(s, str) else None
    return int(m.group(1)) * BUDGET_UNIT_MS[m.group(2)] if m else None


def lint_manifest(doc, kind):
    findings = []

    def add(level, path, message):
        findings.append({"level": level, "path": path, "message": message})

    def need_text(obj, key, path, label=None):
        if not isinstance(obj, dict) or not _text(obj.get(key)):
            add("error", path, f"{label or key} is required (non-empty text)")

    if kind not in KINDS:
        add("error", "", f"kind must be one of {', '.join(KINDS)}")
    elif not isinstance(doc, dict):
        add("error", "", "manifest must be a JSON object")
    elif kind == "agent":
        meta = doc.get("agent_metadata")
        for k in ("agent_id", "version", "status"):
            need_text(meta, k, f"agent_metadata.{k}")
        seq = doc.get("skill_sequence")
        if not isinstance(seq, list) or not seq:
            add("error", "skill_sequence", "skill_sequence must be a non-empty list")
        else:
            for i, s in enumerate(seq):
                need_text(s, "skill_id", f"skill_sequence[{i}].skill_id")
        if not isinstance(doc.get("runtime_routing"), dict):
            add("warning", "runtime_routing", "runtime_routing is missing")
    else:
        _lint_skill(doc, kind, add, need_text)

    if isinstance(doc, dict) and kind in KINDS:
        h = (doc.get("governance") or {}).get("deterministic_hash") if isinstance(doc.get("governance"), dict) else None
        if h is not None and not (isinstance(h, str) and HASH_OK.match(h)):
            add("warning", "governance.deterministic_hash", "hash is neither a sha256 digest nor COMPUTED_ON_SAVE")
        for path, s in _strings(doc):
            if path != "governance.deterministic_hash" and PLACEHOLDER.search(s):
                add("warning", path, f"placeholder text ({PLACEHOLDER.search(s).group(0)!r})")
    return {"ok": not any(f["level"] == "error" for f in findings), "findings": findings}


def _lint_skill(doc, kind, add, need_text):
    meta = doc.get("skill_metadata")
    for k in ("skill_id", "skill_name", "version", "status"):
        need_text(meta, k, f"skill_metadata.{k}")
    isat = doc.get("isatvon_definition")
    if not isinstance(isat, dict):
        add("error", "isatvon_definition", "isatvon_definition is required")
        return

    # I - instructions (BAM: >= 15 characters of business logic)
    ins = isat.get("i_instructions")
    if not (isinstance(ins, str) and len(ins.strip()) >= 15):
        add("error", "isatvon_definition.i_instructions", "at least 15 characters of real instructions required")

    # S - source (BAM: sourceData required; ours: required_inputs non-empty list)
    ri = (isat.get("s_source") or {}).get("required_inputs") if isinstance(isat.get("s_source"), dict) else None
    if not (isinstance(ri, list) and ri and all(_text(x) for x in ri)):
        add("error", "isatvon_definition.s_source.required_inputs", "required_inputs must be a non-empty list of text")

    # A - automation (BAM: automation enum; ours: the three fields non-empty)
    for k in ("orchestration_layer", "action_step", "acceptance_check"):
        need_text(isat.get("a_automation"), k, f"isatvon_definition.a_automation.{k}")

    # T - tech stack (BAM: non-empty + REGISTRY; unknown is a warning)
    t = isat.get("t_tech_stack")
    base = "isatvon_definition.t_tech_stack"
    for k in ("execution_layer", "action_tool", "fixed_check_tool"):
        need_text(t, k, f"{base}.{k}")
    if isinstance(t, dict):
        libs = [(k, t.get(k)) for k in ("execution_layer", "gateway", "telemetry_observer") if t.get(k) is not None]
        libs += [(f"supporting_services[{i}]", x) for i, x in enumerate(t.get("supporting_services") or [])]
        for k, v in libs:
            if _text(v) and not _known_tech(v):
                add("warning", f"{base}.{k}", f"{v!r} is not in the known tech registry")

    # V - variables (BAM: key: value pairs; ours: the SRI bounds)
    v = isat.get("v_variables")
    vp = "isatvon_definition.v_variables"
    if not isinstance(v, dict):
        if kind == "reporting" and isinstance(doc.get("v_variables"), dict):
            add("warning", "v_variables", "variables are hoisted to top level; no max_iterations/budget_limit bound")
        else:
            add("error", vp, "v_variables is required")
    else:
        mi = v.get("max_iterations")
        if isinstance(mi, bool) or not isinstance(mi, int) or mi < 1:
            add("error", f"{vp}.max_iterations", "max_iterations must be a positive integer")
        elif mi > MAX_ITERATIONS_WARN:
            add("warning", f"{vp}.max_iterations", f"above the SRI bound of {MAX_ITERATIONS_WARN}")
        if _budget_ms(v.get("budget_limit")) is None:
            add("error", f"{vp}.budget_limit", "budget_limit must start with a duration such as '60000ms'")
        need_text(v, "success_gate", f"{vp}.success_gate")

    # O - outcome (BAM: outcome schema required)
    # (a schema name, or an inline schema object as the approved/reporting manifests write it)
    js = (isat.get("o_outcome") or {}).get("json_schema") if isinstance(isat.get("o_outcome"), dict) else None
    if not (_text(js) or (isinstance(js, dict) and js)):
        add("error", "isatvon_definition.o_outcome.json_schema", "outcome schema is required (name or non-empty object)")

    # N - next (skills say n_next, approved/reporting say n_notification)
    n = isat.get("n_next", isat.get("n_notification"))
    if not n:
        add("error", "isatvon_definition.n_next", "n_next (or n_notification) must be non-empty")

    # sub-skills: steps, and a Human/Auto marker on every step when the file uses one
    subs = doc.get("sub_skills")
    if subs is not None and not (isinstance(subs, list) and subs):
        add("error", "sub_skills", "sub_skills must be a non-empty list when present")
    for i, s in enumerate(subs if isinstance(subs, list) else []):
        p = f"sub_skills[{i}]"
        need_text(s, "sub_skill_id", f"{p}.sub_skill_id")
        steps = s.get("steps") if isinstance(s, dict) else None
        if not (isinstance(steps, list) and steps):
            add("error", f"{p}.steps", "every sub-skill needs steps")
            continue
        uses_mode = any(isinstance(x, dict) and "mode" in x for x in steps)
        for j, x in enumerate(steps):
            need_text(x, "action", f"{p}.steps[{j}].action")
            if uses_mode and (not isinstance(x, dict) or x.get("mode") not in ("Human", "Auto")):
                add("error", f"{p}.steps[{j}].mode", "mode must be 'Human' or 'Auto'")


# ---------------------------------------------------------------- AST gate

def ast_gate(source):
    errors = []
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return {"ok": False, "errors": [{"line": e.lineno or 0, "message": f"SyntaxError: {e.msg}"}]}
    except (ValueError, RecursionError, MemoryError) as e:
        return {"ok": False, "errors": [{"line": 0, "message": f"unparseable source: {type(e).__name__}"}]}

    def bad(node, message):
        errors.append({"line": getattr(node, "lineno", 0), "message": message})

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in ALLOWED_IMPORTS:
                    bad(node, f"import of '{a.name}' is not allowed")
        elif isinstance(node, ast.ImportFrom):
            if node.level or (node.module or "").split(".")[0] not in ALLOWED_IMPORTS:
                bad(node, f"import from '{'.' * node.level}{node.module or ''}' is not allowed")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            bad(node, f"use of '{node.id}' is forbidden")
        elif isinstance(node, ast.Attribute) and (node.attr == "system" or node.attr in FORBIDDEN_NAMES):
            bad(node, f"use of '.{node.attr}' is forbidden")
    return {"ok": not errors, "errors": errors}


# ---------------------------------------------------------------- render

_PYTYPE = {"string": "str", "number": "float", "integer": "int", "boolean": "bool", "array": "list", "object": "dict"}
_RESERVED = {"status", "reason", "iterations", "awaiting_human"}


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "_", str(s).lower()).strip("_") or "x"


def _field_name(name, seen):
    s = re.sub(r"\W", "_", str(name))
    if not s or s[0].isdigit() or s.startswith("_") or keyword.iskeyword(s) or s.startswith("model_") or s in _RESERVED:
        s = "f_" + s.lstrip("_")
    while s in seen:
        s += "_"
    seen.add(s)
    return s


def _subs(doc, sub_skill_id):
    """The sub-skills to build. A manifest without sub_skills (approved, reporting) is one tool for the whole skill."""
    isat = doc.get("isatvon_definition") or {}
    subs = doc.get("sub_skills")
    if not subs:
        meta = doc.get("skill_metadata") or {}
        step = {"step_id": "1", "action": (isat.get("a_automation") or {}).get("action_step", ""), "mode": "Auto"}
        subs = [{"sub_skill_id": meta.get("skill_id", "1"), "sub_skill_name": meta.get("skill_name", ""), "steps": [step]}]
    if sub_skill_id is not None:
        subs = [s for s in subs if str(s.get("sub_skill_id")) == str(sub_skill_id)]
        if not subs:
            raise ValueError(f"sub_skill_id {sub_skill_id!r} not found in this manifest")
    return subs


def _stem(doc, sub):
    meta = doc.get("skill_metadata") or {}
    stem = _slug(f"{meta.get('skill_id', '')}_{sub.get('sub_skill_id', '')}_{sub.get('sub_skill_name', '')}")
    return stem if not stem[0].isdigit() else "t_" + stem


def _context(doc, sub, quote_formulas):
    meta = doc.get("skill_metadata") or {}
    isat = doc.get("isatvon_definition") or {}
    v = isat.get("v_variables") if isinstance(isat.get("v_variables"), dict) else doc.get("v_variables")
    v = v if isinstance(v, dict) else {}
    out = isat.get("o_outcome") or {}
    seen = set()
    props = ((doc.get("contracts") or {}).get("output_schema") or {}).get("properties") or {}
    fields = [{"name": _field_name(k, seen), "type": _PYTYPE.get((p or {}).get("type") if isinstance(p, dict) else None, "Any")}
              for k, p in props.items()]
    mi, bm = v.get("max_iterations"), _budget_ms(v.get("budget_limit"))
    stem = _stem(doc, sub)
    return {
        "skill_id": meta.get("skill_id", ""), "skill_name": meta.get("skill_name", ""),
        "sub_skill_id": sub.get("sub_skill_id", ""), "sub_skill_name": sub.get("sub_skill_name", ""),
        "version": meta.get("version", ""),
        "max_iterations": mi if isinstance(mi, int) and not isinstance(mi, bool) and mi >= 1 else 1,
        "budget_ms": bm if bm is not None else 60_000,
        "instructions": isat.get("i_instructions", ""), "success_gate": v.get("success_gate", ""),
        "no_op_condition": v.get("no_op_condition", ""), "escalation_condition": v.get("escalation_condition", ""),
        "acceptance_check": (isat.get("a_automation") or {}).get("acceptance_check", ""),
        "outcome_schema": out["json_schema"] if isinstance(out.get("json_schema"), str)
        else json.dumps(out.get("json_schema", ""), sort_keys=True), "outcome_handoff": out.get("state_handoff_file", ""),
        "steps": [{"step_id": x.get("step_id", i + 1), "action": x.get("action", ""), "mode": x.get("mode") or "Auto"}
                  for i, x in enumerate(sub.get("steps") or [])],
        "variables": list(v.items()), "outcome_fields": fields,
        "service_name": f"{meta.get('skill_id', '')}.{sub.get('sub_skill_id', '')}", "tool_func": stem,
        "quote_formulas": quote_formulas,
    }


def render_skill_tool(doc, sub_skill_id=None, quote_formulas=True):
    subs = _subs(doc, sub_skill_id)
    if len(subs) != 1:
        raise ValueError("sub_skill_id is required to render one tool")
    return ENV.get_template("skill_tool.py.j2").render(_context(doc, subs[0], quote_formulas))


# ---------------------------------------------------------------- preview

def _formula_keys(doc):
    v = (doc.get("isatvon_definition") or {}).get("v_variables")
    v = v if isinstance(v, dict) else doc.get("v_variables")
    return [k for k, x in (v or {}).items() if isinstance(x, str) and x.startswith("=")]


def _infer_kind(doc):
    return "agent" if "agent_metadata" in doc else "reporting" if "reports" in doc else "skill"


def build_preview(doc, sub_skill_id=None):
    kind = _infer_kind(doc) if isinstance(doc, dict) else "skill"
    lint = lint_manifest(doc, kind)
    result = {"ok": False, "files": {}, "bundle_sha256": None, "findings": lint["findings"], "repairs": [],
              "ast": {"ok": False, "errors": []}}
    if not lint["ok"]:
        return result
    if kind == "agent":
        result["findings"].append({"level": "error", "path": "", "message": "codegen needs a skill manifest, not an agent manifest"})
        return result
    try:
        subs = _subs(doc, sub_skill_id)
    except ValueError as e:
        result["findings"].append({"level": "error", "path": "sub_skill_id", "message": str(e)})
        return result

    v = (doc.get("isatvon_definition") or {}).get("v_variables")
    if not isinstance(v, dict):
        result["findings"].append({"level": "warning", "path": "v_variables",
                                   "message": "no loop bounds in the manifest: defaulted to max_iterations=1, budget 60000ms"})
    formulas = _formula_keys(doc)
    for sub in subs:
        path = f"skills/{_stem(doc, sub)}.py"
        n = 2
        while path in result["files"]:  # two sub-skills that slug alike must not overwrite each other
            path = f"skills/{_stem(doc, sub)}_{n}.py"
            n += 1
        # Raw pass first (as BAM's template does) so a formula SyntaxError is caught and healed, not hidden.
        src = ENV.get_template("skill_tool.py.j2").render(_context(doc, sub, not formulas))
        gate = ast_gate(src)
        if not gate["ok"] and formulas and any(e["message"].startswith("SyntaxError") for e in gate["errors"]):
            src = ENV.get_template("skill_tool.py.j2").render(_context(doc, sub, True))  # the one retry
            result["repairs"].append({"path": path, "rule": "quote_spreadsheet_formula", "variables": formulas,
                                      "message": "unquoted '=' formula value caused a SyntaxError; quoted it and retried once"})
            gate = ast_gate(src)
        result["files"][path] = src
        result["ast"]["errors"] += [{"path": path, **e} for e in gate["errors"]]
    result["ast"]["ok"] = not result["ast"]["errors"]
    h = hashlib.sha256()
    for p in sorted(result["files"]):
        h.update(p.encode() + b"\0" + result["files"][p].encode() + b"\0")
    result["bundle_sha256"] = h.hexdigest()
    result["ok"] = result["ast"]["ok"]
    return result
