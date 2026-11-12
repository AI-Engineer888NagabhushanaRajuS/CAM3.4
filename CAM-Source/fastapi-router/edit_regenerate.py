"""SPEC-020 dynamic propagation: edit a costed-BOM value, re-run ONLY the report builder, prove what changed.

The database is the truth (cbom.duckdb's final_* columns). An edit is applied with the SAME helper PUT
/api/bom/batch-update uses, the reporting MCP server's own `export_reports` tool writes a NEW versioned workbook
(the previous one stays), and the two workbooks are compared cell by cell (stored values) so the UI can show
which cells, in which sheets, moved. Any failure after the edit restores the previous values.

This module imports nothing from duck_db_api and no `config` at import time (the bridge process's `config` is the
reporting package's): duck_db_api hands in the database operations as `Ports`.

Deployment: the bridge container needs CAM_DAEMON_URL (SSE hub) and CAM_MCP_HOST_CENTUM_REPORTING (reporting MCP
server). Inside Docker they default to host.docker.internal:9334 and reporting-mcp-server when unset.
"""
import importlib.util
import json
import math
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from itertools import zip_longest
from typing import Any, Callable, Optional

import openpyxl
from openpyxl.utils import get_column_letter

MAX_EDITS = 200
EXPORT_TIMEOUT_S = 300
EXAMPLES_PER_SHEET = 20
EXPORT_TOOL = "centum_reporting__export_reports"
EVENTS = ("rfq:value-changed", "rfq:reports-regenerating", "rfq:reports-ready", "rfq:reports-failed")

# Value type of every editable field (duck_db_api.EDITABLE_FIELDS is the allow-list; a field it lists that is
# missing here is refused, so adding a field there never silently skips type checking). Column types: schema.py.
FIELD_TYPES = {
    "final_mfg_name": "str",
    "final_unit_of_measure": "str",
    "final_price_conv": "num",
    "final_price_original": "num",
    "final_currency_original": "str",
    "final_supp_name": "str",
    "final_pkg_qty": "num",
    "final_moq": "num",
    "final_lead_time": "int",
}

# Cells that differ between ANY two exports of the same data (the exporter's Manifest sheet: the file's own name and
# its generation time). Matched by the label in column A, value in column B.
VOLATILE_SHEET = "Manifest"
VOLATILE_LABELS = ("Workbook", "Generated (UTC)")
IGNORED_NOTE = f"{VOLATILE_SHEET} sheet: value cells of rows labelled {', '.join(VOLATILE_LABELS)}"

# Sheets that list items in an order the exporter does not fix (the same rows come out shuffled on every export, with
# a running "Sl.no" in column A). They are compared as sets of rows: sorted within each numbered block, serials renumbered.
ORDER_FREE_SHEETS = ("Missing Notes",)
ORDER_FREE_NOTE = f"{', '.join(ORDER_FREE_SHEETS)} sheet: compared as a set of rows (row order and serial numbers are not meaningful)"


class EditError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


@dataclass
class Ports:
    """What duck_db_api supplies. read_rows(specs) -> per spec the matching rows as dicts holding bom_item_id,
    volume_no and the spec's fields; apply(rows) -> None (batch-update row format, raises on failure);
    list_exports() -> this RFQ version's workbook paths; export() -> the export_reports result dict."""
    read_rows: Callable[[list], list]
    apply: Callable[[list], Any]
    list_exports: Callable[[], list]
    export: Callable[[], dict]
    emit: Callable[[str, dict], None]


# ---------------------------------------------------------------- validation

def validate_edits(edits: Any, editable_fields) -> list:
    if not isinstance(edits, list) or not edits:
        raise EditError(400, "edits must be a non-empty list")
    if len(edits) > MAX_EDITS:
        raise EditError(422, f"at most {MAX_EDITS} edits per request (got {len(edits)})")
    plan, seen = [], set()
    for i, edit in enumerate(edits):
        where = f"edits[{i}]"
        if not isinstance(edit, dict):
            raise EditError(422, f"{where} must be an object")
        bom_item_id = edit.get("bom_item_id")
        if not isinstance(bom_item_id, str) or not bom_item_id.strip():
            raise EditError(422, f"{where}.bom_item_id must be a non-empty string")
        volume_no = edit.get("volume_no")
        if isinstance(volume_no, bool) or not (volume_no is None or isinstance(volume_no, (int, str))):
            raise EditError(422, f"{where}.volume_no must be an integer or text when given")
        values = edit.get("set")
        if not isinstance(values, dict) or not values:
            raise EditError(422, f"{where}.set must be a non-empty object")
        clean = {}
        for field, value in values.items():
            if field not in editable_fields or field not in FIELD_TYPES:
                raise EditError(422, f"{where}: '{field}' is not an editable field (allowed: {', '.join(editable_fields)})")
            clean[field] = _check_value(f"{where}.set.{field}", FIELD_TYPES[field], value)
        key = (bom_item_id.strip(), volume_no)
        if key in seen:
            raise EditError(422, f"{where}: bom_item_id {key[0]!r} appears twice; merge the edits into one")
        seen.add(key)
        plan.append({"bom_item_id": key[0], "volume_no": volume_no, "set": clean})
    return plan


def _check_value(where: str, kind: str, value: Any):
    # None is refused on purpose: the nine fields are what the quote is built from, and "clear it" has no meaning
    # for the reports (it would silently drop the part from the costed set).
    if value is None:
        raise EditError(422, f"{where}: null is not allowed (clearing a value is not supported)")
    if kind == "str":
        if not isinstance(value, str) or not value.strip() or len(value) > 200:
            raise EditError(422, f"{where} must be a non-empty text of at most 200 characters")
        return value.strip()
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise EditError(422, f"{where} must be a finite number >= 0")
    if kind == "int":
        if isinstance(value, float) and not value.is_integer():
            raise EditError(422, f"{where} must be a whole number")
        return int(value)
    return value


# ---------------------------------------------------------------- events

def _in_docker() -> bool:
    return os.path.exists("/.dockerenv")


def daemon_url() -> str:
    url = os.environ.get("CAM_DAEMON_URL")
    if not url:
        url = "http://host.docker.internal:9334" if _in_docker() else "http://127.0.0.1:9334"
    return url.rstrip("/")


def emit_event(event: str, payload: dict) -> None:
    """POST to the daemon relay (apps/daemon browser-api-server /api/internal/emit-rfq-event). Best effort: a
    daemon that is down must never fail or revert an edit."""
    import httpx  # same client the router's notify_skill_progress uses
    try:
        httpx.post(daemon_url() + "/api/internal/emit-rfq-event", json={"event": event, **payload}, timeout=5)
    except Exception as e:
        print(f"[SSE ERROR] ({event}) {type(e).__name__}")


# ---------------------------------------------------------------- the export (reporting MCP server)

_call_tool: Optional[Callable] = None


def _router_call_tool() -> Callable:
    """fastapi-router/tool_calling.call_tool, the same code /tool/execute uses to reach an MCP server. It does
    `from config import get_mcp_url`, but in the bridge process `config` is the reporting package's, so it is loaded
    from file with the router's own config swapped in for the duration of the import."""
    global _call_tool
    if _call_tool is None:
        if _in_docker() and "CAM_MCP_HOST" not in os.environ:
            os.environ.setdefault("CAM_MCP_HOST_CENTUM_REPORTING", "reporting-mcp-server")
        here = os.path.dirname(os.path.abspath(__file__))

        def load(name, filename):
            spec = importlib.util.spec_from_file_location(name, os.path.join(here, filename))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module

        saved = sys.modules.get("config")
        sys.modules["config"] = load("cam_router_config", "config.py")
        try:
            _call_tool = load("cam_router_tool_calling", "tool_calling.py").call_tool
        finally:
            if saved is None:
                sys.modules.pop("config", None)
            else:
                sys.modules["config"] = saved
    return _call_tool


def call_reporting_export(cbom_key: str) -> dict:
    """Runs the reporting server's export_reports for the version-scoped key (what /tool/execute rewrites rfq_id to)
    and returns its result dict. Deliberately NOT /tool/execute: that endpoint also advances rfq_process_stage,
    clears hitl_required, publishes skill-progress and queues memory ingestion, none of which an edit may do.
    No token is involved: the MCP server and the router take none (network placement is their boundary)."""
    envelope = _router_call_tool()(EXPORT_TOOL, {"rfq_id": cbom_key})
    result = envelope.get("result") or {}
    text = (result.get("content") or [{}])[0].get("text", "")
    if result.get("isError") or "error" in envelope and "result" not in envelope:
        raise RuntimeError(f"export_reports call failed: {(text or json.dumps(envelope.get('error')))[:300]}")
    return json.loads(text)


# ---------------------------------------------------------------- the diff

def _norm(value):
    return None if value == "" else value


def _canonical_rows(rows: list) -> list:
    """Each run of numbered rows (integer in column A) sorted by the rest of the row and renumbered 1..n; headers and
    section titles (anything else in column A) stay where they are and end the run."""
    out, block = [], []

    def flush():
        block.sort(key=lambda p: repr([str(x) for x in p[0][1:]]))
        out.extend(((i,) + tuple(v[1:]), (i,) + tuple(f[1:])) for i, (v, f) in enumerate(block, 1))
        block.clear()

    for row_v, row_f in rows:
        if row_v and isinstance(row_v[0], int) and not isinstance(row_v[0], bool):
            block.append((tuple(row_v), tuple(row_f)))
        else:
            flush()
            out.append((row_v, row_f))
    flush()
    return out


def _load_cells(path: str) -> dict:
    """{sheet: {(row, col): (stored value, is_formula)}} for every non-empty or formula cell."""
    wv = openpyxl.load_workbook(path, data_only=True, read_only=True)
    wf = openpyxl.load_workbook(path, data_only=False, read_only=True)
    try:
        sheets = {}
        for name in wv.sheetnames:
            cells = {}
            rows = zip_longest(wv[name].iter_rows(values_only=True), wf[name].iter_rows(values_only=True), fillvalue=())
            if name in ORDER_FREE_SHEETS:
                rows = _canonical_rows(list(rows))
            for r, (row_v, row_f) in enumerate(rows, 1):
                for c, (v, f) in enumerate(zip_longest(row_v, row_f), 1):
                    is_formula = isinstance(f, str) and f.startswith("=")
                    v = _norm(v)
                    if v is not None or is_formula:
                        cells[(r, c)] = (v, is_formula)
            sheets[name] = cells
        return sheets
    finally:
        wv.close()
        wf.close()


def _volatile(sheets: dict) -> set:
    cells = sheets.get(VOLATILE_SHEET, {})
    return {(VOLATILE_SHEET, r, 2) for (r, c), (v, _) in cells.items() if c == 1 and v in VOLATILE_LABELS}


def _same(a, b) -> bool:
    if all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (a, b)):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
    return a == b and isinstance(a, bool) == isinstance(b, bool)   # 0 and False are different stored values (FE-5: a 0 -> FALSE change was invisible)


def _jsonable(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def diff_workbooks(before_path: str, after_path: str) -> dict:
    """Cell-level diff of the STORED values (openpyxl data_only) of two exports, all sheets. A formula cell whose
    result was never stored (export made without the LibreOffice step) cannot be compared: it is skipped and counted,
    never reported as a change."""
    before, after = _load_cells(before_path), _load_cells(after_path)
    ignored = _volatile(before) | _volatile(after)
    empty = (None, False)
    sheets, total, uncached = [], 0, 0
    for name in list(after) + [n for n in before if n not in after]:
        b, a = before.get(name, {}), after.get(name, {})
        changed, examples = 0, []
        for (r, c) in sorted(set(b) | set(a)):
            if (name, r, c) in ignored:
                continue
            (bv, bf), (av, af) = b.get((r, c), empty), a.get((r, c), empty)
            if (bf and bv is None) or (af and av is None):
                uncached += 1
                continue
            if _same(bv, av):
                continue
            changed += 1
            if len(examples) < EXAMPLES_PER_SHEET:
                examples.append({"cell": f"{get_column_letter(c)}{r}", "before": _jsonable(bv), "after": _jsonable(av)})
        if changed:
            entry = {"sheet": name, "changed": changed, "examples": examples}
            if name not in before:
                entry["note"] = "sheet is new in this version"
            elif name not in after:
                entry["note"] = "sheet no longer exists in this version"
            sheets.append(entry)
            total += changed
    return {"total_changed_cells": total, "sheets": sheets, "ignored": [IGNORED_NOTE, ORDER_FREE_NOTE],
            "uncached_formula_cells_skipped": uncached}


def _write_json(path: str, payload: dict) -> None:
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


# ---------------------------------------------------------------- exports listing

def _generated_at(path: str) -> str:
    return datetime.fromtimestamp(os.path.getmtime(path)).isoformat()


def _newest_first(paths: list) -> list:
    return sorted(paths, key=os.path.getmtime, reverse=True)


def describe_exports(paths: list) -> list:
    """[{filename, generated_at, diff_summary}] newest first; diff_summary is None for a version with no saved diff."""
    out = []
    for path in _newest_first(paths):
        summary = None
        try:
            with open(path + ".diff.json", encoding="utf-8") as f:
                d = json.load(f)
            summary = {"total_changed_cells": d["total_changed_cells"], "sheets": len(d["sheets"])}
        except (OSError, ValueError, KeyError, TypeError):
            pass
        out.append({"filename": os.path.basename(path), "generated_at": _generated_at(path), "diff_summary": summary})
    return out


# ---------------------------------------------------------------- orchestration

_locks: dict = {}
_locks_guard = threading.Lock()


def _rfq_lock(rfq_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(rfq_id, threading.Lock())


def _run_with_timeout(fn: Callable, seconds: float):
    # ponytail: a timed-out export cannot be cancelled; the worker thread (and the MCP server) may still finish
    # and write a late workbook after the revert. Upgrade: a cancel/handle on the reporting server.
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(fn).result(timeout=seconds)
    finally:
        pool.shutdown(wait=False)


def _detail(e: Exception) -> str:
    return str(getattr(e, "detail", None) or e)[:300]


def edit_and_regenerate(rfq_id: str, edits: Any, note: Optional[str], editable_fields, ports: Ports,
                        export_timeout: float = EXPORT_TIMEOUT_S) -> dict:
    plan = validate_edits(edits, editable_fields)
    if note is not None and (not isinstance(note, str) or len(note) > 500):
        raise EditError(422, "note must be text of at most 500 characters")
    lock = _rfq_lock(rfq_id)
    if not lock.acquire(blocking=False):
        raise EditError(409, f"Another edit for {rfq_id} is still regenerating its reports; try again when it finishes.")
    try:
        return _run(rfq_id, plan, note, ports, export_timeout)
    finally:
        lock.release()


def _emit(ports: Ports, event: str, payload: dict) -> None:
    try:
        ports.emit(event, payload)
    except Exception as e:  # never let a relay problem touch the edit
        print(f"[SSE ERROR] ({event}) {type(e).__name__}")


def _run(rfq_id: str, plan: list, note: Optional[str], ports: Ports, export_timeout: float) -> dict:
    # (1) remember: the latest export (before) and the previous value of every cell the edits touch
    before_path = next(iter(_newest_first(ports.list_exports())), None)
    matched = ports.read_rows([(e["bom_item_id"], e["volume_no"], list(e["set"])) for e in plan])
    apply_rows, revert_rows, items = [], [], []
    for edit, rows in zip(plan, matched):
        if not rows:
            raise EditError(404, f"bom_item_id {edit['bom_item_id']!r} was not found for {rfq_id}")
        for row in rows:
            key = {"bom_item_id": edit["bom_item_id"]}
            if row.get("volume_no") is not None:
                key["volume_no"] = row["volume_no"]
            apply_rows.append({**key, **edit["set"]})
            revert_rows.append({**key, **{f: row[f] for f in edit["set"]}})
            for field, new in edit["set"].items():
                items.append({"bomItemId": edit["bom_item_id"], "volumeNo": _jsonable(row.get("volume_no")),
                              "field": field, "before": _jsonable(row[field]), "after": new})

    # (2) apply with the same helper batch-update uses (one transaction: a failure here changes nothing)
    try:
        ports.apply(apply_rows)
    except Exception as e:
        raise EditError(500, f"Could not apply the edits (nothing was changed): {_detail(e)}")

    # (3)-(6); from here on a failure restores the previous values
    try:
        fields = sorted({i["field"] for i in items})
        _emit(ports, "rfq:value-changed", {"rfqId": rfq_id, "fields": fields, "items": items})
        _emit(ports, "rfq:reports-regenerating", {"rfqId": rfq_id})
        try:
            result = _run_with_timeout(ports.export, export_timeout)
        except FutureTimeout:
            raise EditError(504, f"Report regeneration did not finish within {int(export_timeout)} s")
        if not isinstance(result, dict) or result.get("status") != "success":
            reason = result.get("error") if isinstance(result, dict) else None
            raise EditError(502, f"Report regeneration failed: {str(reason or result)[:300]}")
        name = os.path.basename(str(result.get("workbook_name") or ""))
        after_path = next((p for p in ports.list_exports() if os.path.basename(p) == name), None)
        if after_path is None:
            raise EditError(502, f"Report regeneration reported {name!r} but that workbook is not in the exports folder")
        if after_path == before_path:
            raise EditError(502, "Report regeneration did not produce a new workbook version")
    except Exception as e:
        status, message = (e.status, e.message) if isinstance(e, EditError) else (502, f"Report regeneration failed: {_detail(e)}")
        try:
            ports.apply(revert_rows)
            message += " The edits were reverted; nothing is half-applied."
        except Exception as revert_error:
            status = 500
            message += f" REVERTING THE EDITS FAILED ({_detail(revert_error)}): the database may still hold the edited values."
        _emit(ports, "rfq:reports-failed", {"rfqId": rfq_id, "message": message})
        print(f"[EDIT REGENERATE] {rfq_id} failed: {message}")
        raise EditError(status, message)

    # diff: the edit and the new workbook are both in place and consistent, so a diff problem is reported, not reverted
    diff, diff_error, diff_note = None, None, None
    if before_path is None:
        diff_note = "No export existed before this edit, so there is nothing to compare."
    else:
        try:
            diff = diff_workbooks(before_path, after_path)
            cached = (result.get("cached_values") or {}).get("status")
            if cached != "ok":
                diff["cached_values"] = cached or "unknown"
                diff_note = ("The new workbook has no stored formula results (cached_values: %s); only literal cells "
                             "and formulas that had stored results are compared." % (cached or "unknown"))
            _write_json(after_path + ".diff.json", {
                "rfq_id": rfq_id, "before": os.path.basename(before_path), "after": os.path.basename(after_path),
                "generated_at": _generated_at(after_path), "note": note, "edits": items, **diff})
        except Exception as e:
            diff, diff_error = None, f"{type(e).__name__}: {_detail(e)}"
            print(f"[EDIT REGENERATE] {rfq_id} diff failed: {diff_error}")

    _emit(ports, "rfq:reports-ready", {
        "rfqId": rfq_id, "filename": os.path.basename(after_path),
        "totalChangedCells": diff["total_changed_cells"] if diff else None,
        "sheets": len(diff["sheets"]) if diff else None})
    response = {
        "ok": True, "rfq_id": rfq_id, "applied": len(apply_rows), "items": items, "note": note,
        "before": {"filename": os.path.basename(before_path)} if before_path else None,
        "after": {"filename": os.path.basename(after_path), "generated_at": _generated_at(after_path)},
        "diff": diff}
    if diff_note:
        response["diff_note"] = diff_note
    if diff_error:
        response["diff_error"] = diff_error
    return response
