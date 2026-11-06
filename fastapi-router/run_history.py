"""Run history of an RFQ's pipeline (SPEC-021): Temporal's own record of each run, with a failure explained in plain words.

No store of our own: every run of workflow `rfq-<rfq_id>` is kept by Temporal (a new upload re-uses the id with
TERMINATE_EXISTING). `classify_failure` is a pure function of the failure text raised by temporal_worker/workflow.py
("<tool> failed: <error>"); `list_runs` reads Temporal through a client passed in, so tests need no server.
"""
import os
import re
from typing import Any, Optional

MAX_RUNS = 20
RAW_LIMIT = 400
_ID = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")  # the id goes into a Temporal visibility query: nothing else is allowed in

_SHEET = re.compile(r"Could not find a sheet named '([^']+)' in (.+?)\.? Available sheets: \[(.*)\]", re.S)
_RATE = re.compile(r"no active conversion rate for '([^']+)' -> '([^']+)'")
_STEP = re.compile(r"^(\S+) failed: (.*)$", re.S)


def _step_label(tool: str) -> str:
    name = tool.split("__")[-1].replace("_", " ").strip()
    return name[:1].upper() + name[1:] if name else "A step"


def classify_failure(text: str) -> dict:
    """{kind, title, cause, next_step, step, can_rerun, raw} for a workflow failure text."""
    raw = (text or "").strip()
    m = _STEP.match(raw)
    tool, detail = (m.group(1), m.group(2)) if m else ("", raw)
    step = _step_label(tool) if tool else "A step"
    out: dict[str, Any] = {"step": step, "raw": raw[:RAW_LIMIT]}

    sheet = _SHEET.search(detail)
    rate = _RATE.search(detail)
    if sheet:
        need, path, found = sheet.group(1), sheet.group(2), sheet.group(3).replace("'", "").strip()
        out.update(kind="invalid_input", title=f"Invalid input: no ‘{need}’ sheet",
                   cause=f"{step} reads a sheet named ‘{need}’. The file {os.path.basename(path.strip())} has: {found or 'no sheets'}.",
                   next_step=f"Upload the workbook that contains a ‘{need}’ sheet; a new upload starts a new run.")
    elif "No QuoteWin file uploaded" in detail:
        out.update(kind="invalid_input", title="Invalid input: no QuoteWin file",
                   cause=f"{step} needs a QuoteWin file for this RFQ and none was uploaded.",
                   next_step="Upload the QuoteWin file, then continue.")
    elif "Could not locate the QuoteWin data header row" in detail:
        out.update(kind="invalid_input", title="Invalid input: QuoteWin header row not found",
                   cause=f"{step} could not find the column headings it expects in the QuoteWin file.",
                   next_step="Check the file has the QuoteWin columns (Part Number, Mfg Part Number, ...) and upload it again.")
    elif rate:
        out.update(kind="configuration", title=f"Missing currency rate: {rate.group(1)} → {rate.group(2)}",
                   cause=f"{step} will not report an amount it could not convert from {rate.group(1)} to {rate.group(2)}.",
                   next_step=f"Add an active {rate.group(1)} → {rate.group(2)} rate in Settings → Currencies, then run again.")
    else:
        out.update(kind="tool_error", title=f"{step} failed", cause=detail[:RAW_LIMIT] or "No details were reported.",
                   next_step="Run again. If it fails the same way, send the details below to support.")
    out["can_rerun"] = out["kind"] != "invalid_input"
    return out


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt else None


def _status(name: str, result_status: Optional[str]) -> str:
    if name == "RUNNING":
        return "running"
    if name == "COMPLETED":
        return "stopped" if result_status == "rejected" else "passed"
    if name == "TERMINATED":
        return "replaced"  # a new upload started a new run and ended this one
    if name == "CANCELED":
        return "cancelled"
    return "failed"  # FAILED, TIMED_OUT


def run_row(ex: Any, started_by: Optional[str], failure_text: Optional[str], result_status: Optional[str]) -> dict:
    status = _status(getattr(ex.status, "name", str(ex.status)), result_status)
    start, close = getattr(ex, "start_time", None), getattr(ex, "close_time", None)
    failure = classify_failure(failure_text or "") if status == "failed" else None
    return {
        "run_id": ex.run_id, "status": status, "started_at": _iso(start), "closed_at": _iso(close),
        "duration_ms": int((close - start).total_seconds() * 1000) if start and close else None,
        "started_by": started_by or "unknown",
        "failed_step": failure["step"] if failure else None,
        "failure": failure, "can_rerun": bool(failure and failure["can_rerun"]),
    }


def _cause_text(err: Exception) -> str:
    cause = getattr(err, "cause", None) or err
    return str(getattr(cause, "message", None) or cause)


async def list_runs(rfq_id: str, client: Any, limit: int = MAX_RUNS) -> list:
    """Newest first. `client` is a connected temporalio Client."""
    from temporalio.client import WorkflowFailureError  # lazy: classify_failure needs no Temporal

    if not _ID.match(rfq_id):
        raise ValueError("invalid rfq_id")
    runs = []
    async for ex in client.list_workflows(query=f'WorkflowId = "rfq-{rfq_id}"', limit=limit):
        try:
            started_by = (await ex.memo()).get("started_by")
        except Exception:
            started_by = None
        text = result_status = None
        name = getattr(ex.status, "name", "")
        if name in ("FAILED", "COMPLETED"):
            try:
                res = await client.get_workflow_handle(ex.id, run_id=ex.run_id).result(follow_runs=False)
                result_status = res.get("status") if isinstance(res, dict) else None
            except WorkflowFailureError as e:
                text = _cause_text(e)
            except Exception:
                pass  # a run whose outcome cannot be read still shows, with its status
        runs.append((ex.start_time, run_row(ex, started_by, text, result_status)))
    runs.sort(key=lambda p: p[0].timestamp() if p[0] else 0, reverse=True)
    return [r for _, r in runs][:limit]
