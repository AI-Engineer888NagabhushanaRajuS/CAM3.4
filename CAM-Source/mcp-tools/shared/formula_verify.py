"""Independent recalculation check of a finished report workbook, by the CAM Formula Engine (mcp-tools/shared/formula_engine).

The engine re-computes every formula cell itself and the result is compared with the value stored in the file (the one the LibreOffice
cache writer stored, see mcp-tools/reporting/superset/cached_values.py). It says, per tab: how many formulas agree exactly, how many
differ, how many the engine does not support or could not finish, and how many have no stored value to compare with.

What it is NOT (FE-3 / FE-7): not Excel certification, not client approval, not a financial check. `release_ready` is always False.
verify() writes nothing to the workbook; the result is kept next to it as `<workbook>.verify.json`. A run takes seconds to minutes, so
start() runs it in a background thread and status() reads it back.

correct() is the one writer: LibreOffice cannot evaluate array-style INDEX/MATCH(1,INDEX(a*b,0),0) and stores 0 for those cells (BOM MATRIX,
A CLASS PARTS, 7.0 CBOM), so a viewer that does not recalculate (Protected View, previews) shows zeros. Where the engine computed a cell
without any diagnostic and its value differs from the stored one, the engine's value is stored instead. Excel recalculates on open anyway.
"""
import datetime
import hashlib
import json
import math
import os
import re
import sys
import threading
import time
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

_ENGINE = Path(__file__).resolve().parent / "formula_engine" / "engine"
LABEL = "Independent recalculation check (CAM Formula Engine v0.1.0). Not client approval, not Excel certification."
SAMPLES_PER_SHEET = 15
_RUNS = {}
_LOCK = threading.Lock()


def _engine():
    if str(_ENGINE) not in sys.path:
        sys.path.insert(0, str(_ENGINE))
    import excel_formula_engine as fe
    from excel_formula_engine.workbook import CalculationBudgetExceeded
    return fe, CalculationBudgetExceeded


def same(fe, engine_value, stored):
    """Do the engine's value and the stored one agree? Numbers to 1e-9, text and booleans exactly, errors by their text."""
    if fe.is_error(engine_value):
        return str(engine_value) == str(stored)
    if isinstance(engine_value, bool) or isinstance(stored, bool):
        return engine_value is stored or (isinstance(engine_value, bool) and isinstance(stored, bool) and engine_value == stored)
    if isinstance(engine_value, (int, float)) and isinstance(stored, (int, float)):
        return math.isclose(float(engine_value), float(stored), rel_tol=1e-9, abs_tol=1e-9)
    if fe.is_blank(engine_value) or engine_value == "":
        return stored in (None, "")
    return engine_value == stored


_NOTE_CELL = re.compile(r"^\('([^']*)',\s*(\d+),\s*(\d+)\)")


def verify(path, as_of=None, budget_seconds=None, collect_fixes=False):
    """The full check of one workbook, synchronously. Never raises: a workbook the engine cannot read is itself the answer.
    With collect_fixes, `fixes` lists {sheet: {(row, col): engine value}} for cells the engine computed cleanly and that differ from (or lack) the stored value."""
    started = time.monotonic()
    fixes = {}
    as_of = as_of or datetime.date.today()
    budget = budget_seconds if budget_seconds is not None else float(os.environ.get("CAM_VERIFY_BUDGET", "600"))
    out = {"label": LABEL, "source_name": Path(path).name, "source_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
           "as_of": as_of.isoformat(), "release_ready": False, "complete": False, "sheets": {}, "totals": {}, "diagnostics": [], "error": None}
    try:
        fe, Budget = _engine()
        wb = fe.Workbook(str(path), today=as_of)
    except Exception as e:
        out["error"] = f"The engine could not open the workbook ({type(e).__name__}: {str(e)[:160]})."
        out["elapsed_seconds"] = round(time.monotonic() - started, 1)
        return out
    totals = {"formulas": 0, "exact": 0, "different": 0, "no_stored_value": 0, "engine_error": 0}
    complete = True
    for key, sd in wb.sheets.items():
        row = {"formulas": 0, "exact": 0, "different": 0, "no_stored_value": 0, "engine_error": 0, "samples": []}
        for (r, c) in list(sd.formulas):
            remaining = budget - (time.monotonic() - started)
            if remaining <= 0:
                complete = False
                break
            row["formulas"] += 1
            try:
                value = wb.cell_value_now(key, r, c, budget_seconds=remaining)
            except Budget:
                complete = False
                row["formulas"] -= 1
                break
            except Exception as e:
                row["engine_error"] += 1
                if len(row["samples"]) < SAMPLES_PER_SHEET:
                    row["samples"].append({"row": r, "col": c, "engine": f"engine failed: {type(e).__name__}", "stored": None})
                continue
            stored = sd.cached.get((r, c))
            if stored is None and not fe.is_blank(value) and value != "":
                row["no_stored_value"] += 1
                if collect_fixes and isinstance(value, (int, float, str, bool)) and not fe.is_error(value):
                    fixes.setdefault(sd.title, {})[(r, c)] = value
            elif same(fe, value, stored):
                row["exact"] += 1
            else:
                row["different"] += 1
                if collect_fixes and isinstance(value, (int, float, str, bool)) and not fe.is_error(value):
                    fixes.setdefault(sd.title, {})[(r, c)] = value
                if len(row["samples"]) < SAMPLES_PER_SHEET:
                    row["samples"].append({"row": r, "col": c, "engine": str(value), "stored": None if stored is None else str(stored)})
        if row["formulas"]:
            out["sheets"][sd.title] = row
            for k in totals:
                totals[k] += row[k]
        if not complete:
            break
    out["totals"] = totals
    out["complete"] = complete
    # Diagnostics are blockers even when an outer IFERROR hides them (FE-3): an unsupported inner call is listed, not forgiven.
    notes = list(dict.fromkeys(wb.notes))
    out["diagnostics"] = notes[:30]
    out["elapsed_seconds"] = round(time.monotonic() - started, 1)
    if collect_fixes:
        # A cell the engine reported a diagnostic for (an unsupported inner call hidden by IFERROR) is never overwritten.
        for note in notes:
            m = _NOTE_CELL.match(str(note))
            if m:
                fixes.get(m.group(1), {}).pop((int(m.group(2)), int(m.group(3))), None)
                for title in list(fixes):
                    if title.lower() == m.group(1).lower():
                        fixes[title].pop((int(m.group(2)), int(m.group(3))), None)
        out["fixes"] = fixes
    return out


_CELL = re.compile(r'<c r="([A-Z]+[0-9]+)"((?: [A-Za-z:]+="[^"]*")*)>(<f(?:\s[^>]*)?>.*?</f>|<f(?:\s[^>]*)?/>)(<v>[^<]*</v>|<v\s*/>)?(</c>)', re.S)


def _store(path, fixes):
    """Write each fixed cell's value into the workbook's XML next to its formula (the formula stays). Returns how many cells were rewritten."""
    import importlib.util
    # By file, not by putting the reporting folder on sys.path: that folder has a config.py that would shadow the other services' own.
    spec = importlib.util.spec_from_file_location("cam_cached_values", Path(__file__).resolve().parent.parent / "reporting" / "superset" / "cached_values.py")
    cv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cv)
    from openpyxl.utils import get_column_letter
    done = 0
    path = Path(path)
    patched = path.with_name("." + path.stem + ".engine.xlsx")   # hidden, and not CBOM_Report_*: the exports folder never sees it
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(patched, "w", zipfile.ZIP_DEFLATED) as zout:
        by_part = {part: name for name, part in cv._sheet_parts(zin).items()}
        for info in zin.infolist():
            data = zin.read(info.filename)
            wanted = fixes.get(by_part.get(info.filename), None)
            if wanted:
                cells = {f"{get_column_letter(c)}{r}": v for (r, c), v in wanted.items()}

                def put(m):
                    nonlocal done
                    if m.group(1) not in cells:
                        return m.group(0)
                    v = cells[m.group(1)]
                    attrs = re.sub(r' t="[^"]*"', "", m.group(2))
                    if isinstance(v, bool):
                        attrs, text = attrs + ' t="b"', "1" if v else "0"
                    elif isinstance(v, str):
                        attrs, text = attrs + ' t="str"', escape(v)
                    else:
                        text = repr(float(v)) if isinstance(v, float) else str(v)
                    done += 1
                    return f'<c r="{m.group(1)}"{attrs}>{m.group(3)}<v>{text}</v>{m.group(5)}'

                data = _CELL.sub(put, data.decode("utf-8")).encode("utf-8")
            zout.writestr(info, data)
    import io
    import openpyxl
    blob = patched.read_bytes()                                  # from memory: a handle on the path would lock the file on Windows
    openpyxl.load_workbook(io.BytesIO(blob)).close()             # the patched file must still open, formulas and values both
    openpyxl.load_workbook(io.BytesIO(blob), data_only=True).close()
    os.replace(patched, path)
    return done


def correct(path, as_of=None, budget_seconds=None):
    """verify() and then store the engine's value where it disagrees with the stored one. Never raises and never leaves a half-written file."""
    path = Path(path)
    started = time.monotonic()
    result = verify(path, as_of, budget_seconds, collect_fixes=True)
    fixes = result.pop("fixes", {})
    result["corrected"] = 0
    try:
        if result["complete"] and not result["error"] and any(fixes.values()):
            result["corrected"] = _store(path, fixes)
    except Exception as e:
        result["error"] = f"The corrected values could not be stored ({type(e).__name__}: {str(e)[:160]})."
        path.with_name("." + path.stem + ".engine.xlsx").unlink(missing_ok=True)
    result["source_sha256_after"] = hashlib.sha256(path.read_bytes()).hexdigest()
    result["elapsed_seconds"] = round(time.monotonic() - started, 1)
    try:
        Path(result_path(path)).write_text(json.dumps(result), encoding="utf-8")
    except OSError:
        pass
    return result


def result_path(workbook_path):
    return str(workbook_path) + ".verify.json"


def _run(path):
    result = verify(path)
    try:                                              # keep what the export step stored, the re-run itself writes nothing to the workbook
        before = json.loads(Path(result_path(path)).read_text(encoding="utf-8"))
        result["corrected_at_export"] = before.get("corrected_at_export", before.get("corrected"))
    except (OSError, ValueError):
        pass
    try:
        Path(result_path(path)).write_text(json.dumps(result), encoding="utf-8")
    except OSError:
        pass
    with _LOCK:
        _RUNS[path] = {"status": "done", "result": result}


def start(path):
    """Begin the check in the background (one per workbook at a time). Returns the state at once."""
    path = str(path)
    with _LOCK:
        if _RUNS.get(path, {}).get("status") == "running":
            return {"status": "running", "started": _RUNS[path]["started"]}
        _RUNS[path] = {"status": "running", "started": time.time()}
    threading.Thread(target=_run, args=(path,), daemon=True, name="formula-verify").start()
    return {"status": "running", "started": _RUNS[path]["started"]}


def status(path):
    """running | done (with the result) | none. A result saved by an earlier process is read back from disk."""
    path = str(path)
    with _LOCK:
        run = _RUNS.get(path)
    if run is not None:
        return {"status": run["status"], **({"result": run["result"]} if run["status"] == "done" else {"started": run["started"]})}
    saved = Path(result_path(path))
    if saved.exists():
        try:
            return {"status": "done", "result": json.loads(saved.read_text(encoding="utf-8"))}
        except (OSError, ValueError):
            pass
    return {"status": "none"}


# ---- storing the values in older exports (made before the engine step existed) ---------------------------------------------------------------

_REPAIR = {"running": False, "done": 0, "total": 0, "failed": []}


def repair_many(paths):
    """Run correct() over several workbooks in one background thread, one after the other (each loads a whole workbook). Returns the progress at once."""
    with _LOCK:
        if _REPAIR["running"]:
            return dict(_REPAIR)
        _REPAIR.update(running=True, done=0, total=len(paths), failed=[])

    def work():
        for p in paths:
            try:
                r = correct(p)
                if r["error"]:
                    _REPAIR["failed"].append(f"{Path(p).name}: {r['error']}")
            except Exception as e:                      # never leave the job "running" because one workbook was odd
                _REPAIR["failed"].append(f"{Path(p).name}: {type(e).__name__}")
            _REPAIR["done"] += 1
        _REPAIR["running"] = False

    threading.Thread(target=work, daemon=True, name="formula-repair").start()
    return dict(_REPAIR)


def repair_status():
    return dict(_REPAIR)
