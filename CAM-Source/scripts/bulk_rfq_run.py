#!/usr/bin/env python
"""Bulk RFQ run: every batch folder goes through the REAL pipeline (upload -> Temporal workflow -> review gate -> export) and gets an OP folder.

    python scripts/bulk_rfq_run.py --root "<folder holding batch-01-...>" --prefix R --ramp 3 --inflight 8

For each `batch-NN-CE-<number>-...` folder (files: `1 SCRUB BOM*`, `2 QuoteWin*`, optional `3 costing*`):
  1. stage the QuoteWin / costing sheet and upload the BOM with the force flag (the same endpoints the intake dialog uses), RFQ id `<prefix>NN-CE-<number>`;
  2. watch the run in Temporal (the only place a failure is recorded) and in rfq_step_events;
  3. at the final-selection review gate: take the conflicts from the review endpoint, decide them by POLICY (below) and submit them through the
     same endpoint the review screen uses; every decision is written to OP so a person can overrule it;
  4. when the export is done, collect into `<batch>/OP`: the workbook exactly as the app's own download route serves it (checked against the file
     the exporter wrote), its engine check, the analytics numbers, the flags (forced run, auto-resolved conflicts), the step timings and a summary;
  5. optional dashboard export (scripts/rfq_dashboard_export.py) when that script exists.
Concurrency: at most --inflight RFQs are started at a time and the Temporal worker runs at most CAM_WORKER_MAX_ACTIVITIES tool calls (default 4), so
the shared DuckDB lock and the single local model are never asked for more than they can do. --ramp N runs the first N batches alone and stops if any fails.
Never prints a secret: the stack is reached through its published ports and `docker exec`, no password is read.
"""
import argparse
import concurrent.futures as cf
import csv
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time

import openpyxl
import requests

BR, UP, HITL = "http://localhost:13110", "http://localhost:13100", "http://localhost:15102"
PG, EXP, TMP = "cam-e2e-postgres-1", "cam-e2e-reporting-mcp-server-1", "cam-e2e-temporal-1"
HERE = os.path.dirname(os.path.abspath(__file__))
RUN_DIR = os.path.join(os.path.dirname(HERE), ".run")
FAILED_STATES = ("Failed", "TimedOut", "Terminated", "Canceled")
# Final-selection policy for a conflict between the costing sheet, the ERP and the QuoteWin: among the sources that carry a price, costing > erp > qw
# (the costing sheet is Centum's own, specific costing; QuoteWin lines often say "ANY MANUFACTURER"); if none carries a price, the same order.
POLICY = "auto: costing > erp > qw, a source with a price first"
POLICY_ORDER = ("costing", "erp", "qw")
USER = "Bulk run"


def log(msg):
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def W(path):
    """Windows long-path form: a batch folder plus OP plus a file name can pass 260 characters."""
    p = os.path.abspath(path)
    return "\\\\?\\" + p if os.name == "nt" and not p.startswith("\\\\?\\") else p


def sh(args, timeout=180):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")


def psql(sql):
    r = sh(["docker", "exec", "-i", PG, "psql", "-U", "centum", "-d", "file_metadata_db_2", "-tA", "-F", "|", "-c", sql])
    if r.returncode != 0:
        raise RuntimeError("psql: " + r.stderr.strip()[:300])
    return r.stdout.strip()


def q(value):
    return "'" + str(value).replace("'", "''") + "'"


def retry(fn, what, seconds=240):
    """A service restarting (a deploy, a rebuilt image) drops connections for a few seconds; wait it out instead of failing the batch.
    Only for calls that are safe to repeat (token mint, reads, the idempotent review submission)."""
    deadline = time.time() + seconds
    while True:
        try:
            return fn()
        except (requests.ConnectionError, requests.Timeout) as e:
            if time.time() > deadline:
                raise RuntimeError(f"{what}: service unreachable for {seconds} s ({type(e).__name__})")
            time.sleep(5)


def token(rfq):
    return retry(lambda: requests.post(f"{BR}/auth/token", json={"rfq_id": rfq}, timeout=60).json()["token"], "token")


def H(rfq):
    return {"Authorization": f"Bearer {token(rfq)}", "X-CAM-User": USER}


class Monitor:
    """One shared, short-lived snapshot of every run with this prefix: Postgres (steps, gate) and Temporal (the real status)."""

    def __init__(self, prefix, interval=6.0):
        self.prefix, self.interval, self.t, self.snap, self.lock = prefix, interval, 0.0, {}, threading.Lock()

    def get(self, rfq):
        with self.lock:
            if time.time() - self.t > self.interval:
                self._refresh()
            return dict(self.snap.get(rfq, {}))

    def _refresh(self):
        snap = {}
        rows = psql(
            "SELECT t.rfq_id, t.version, t.rfq_process_stage, t.hitl_required,"
            " coalesce((SELECT e.skill_code FROM rfq_step_events e WHERE e.rfq_id=t.rfq_id AND e.version=t.version ORDER BY e.id DESC LIMIT 1),''),"
            " coalesce((SELECT e.step_status FROM rfq_step_events e WHERE e.rfq_id=t.rfq_id AND e.version=t.version ORDER BY e.id DESC LIMIT 1),''),"
            " (SELECT count(*) FROM rfq_step_events e WHERE e.rfq_id=t.rfq_id AND e.version=t.version AND e.skill_code='centum_reporting__resolve_final_selection' AND e.step_status='completed'),"
            " (SELECT count(*) FROM rfq_step_events e WHERE e.rfq_id=t.rfq_id AND e.version=t.version AND e.skill_code='centum_reporting__export_reports' AND e.step_status='completed')"
            f" FROM rfq_process_tracking t WHERE t.is_active AND t.rfq_id LIKE {q(self.prefix + '%')}")
        for ln in filter(None, rows.splitlines()):
            f = ln.split("|")
            snap[f[0]] = {"version": int(f[1]), "stage": int(f[2] or 0), "hitl": f[3] == "t", "last_skill": f[4], "last_status": f[5],
                          "resolve_done": int(f[6]) > 0, "export_done": int(f[7]) > 0}
        out = sh(["docker", "exec", TMP, "temporal", "--address", "temporal:7233", "workflow", "list", "--query",
                  f'WorkflowId STARTS_WITH "rfq-{self.prefix}"', "--limit", "500"]).stdout
        seen = set()
        for ln in out.splitlines():  # newest first: the first line of a workflow id is its current run
            m = re.match(r"\s*(Running|Completed|Failed|TimedOut|Terminated|Canceled|ContinuedAsNew)\s+rfq-(\S+)", ln)
            if m and m.group(2) not in seen:
                seen.add(m.group(2))
                snap.setdefault(m.group(2), {})["wf"] = m.group(1)
        self.snap, self.t = snap, time.time()


def classify(folder):
    names = sorted(os.listdir(folder))
    bom = next((n for n in names if n.startswith("1 SCRUB BOM")), None)
    qw = next((n for n in names if n.startswith("2 QuoteWin")), None)
    cs = next((n for n in names if n.lower().startswith("3 costing")), None)
    if not bom:
        raise RuntimeError("no '1 SCRUB BOM' file in the folder")
    return bom, qw, cs


def failure_reason(rfq):
    r = sh(["docker", "exec", TMP, "temporal", "--address", "temporal:7233", "workflow", "describe", "--workflow-id", f"rfq-{rfq}"])
    msgs = [ln.strip() for ln in r.stdout.splitlines() if ln.strip().startswith(("Message:", "ReadTimeout", "httpx", "TimeoutType"))]
    return " | ".join(m for m in msgs if len(m) > 9)[:500] or r.stdout[-400:]


def pick(sources):
    priced = [s for s in POLICY_ORDER if s in sources and (sources[s] or {}).get("price_conv") is not None]
    pool = priced or [s for s in POLICY_ORDER if s in sources] or list(sources)
    return pool[0]


def resolve_gate(rfq):
    """The review screen's own calls: list the pending conflicts, submit a decision for each (or the empty confirm when nothing conflicts)."""
    hdr, items, cursor = H(rfq), [], None
    while True:
        r = retry(lambda: requests.get(f"{HITL}/api/rfq/{rfq}/final-selection/pending", headers=hdr, timeout=120,
                                       params={"limit": 500, **({"cursor": cursor} if cursor else {})}), "conflict list")
        r.raise_for_status()
        body = r.json()
        items += body["items"]
        cursor = body.get("next_cursor")
        if not cursor:
            break
    decisions = [{"conflict_id": i["conflict_id"], "resolved_source": pick(i["available_sources"]), "resolved_by": POLICY[:60]} for i in items]
    r = retry(lambda: requests.post(f"{HITL}/api/rfq/{rfq}/final-selection", headers=hdr, json={"resolutions": decisions}, timeout=900),
              "review submission")  # repeat-safe: an already-resolved conflict is skipped, a passed review is a no-op
    if r.status_code != 200:
        raise RuntimeError(f"final-selection answered HTTP {r.status_code}: {r.text[:200]}")
    body = r.json()
    if not body.get("fully_approved"):
        raise RuntimeError(f"gate not fully approved: {body}")
    if body.get("signal_delivered") is False:  # the stage advanced but the workflow was not told: tell it the way the review screen does
        requests.post(f"{HITL}/api/rfq/{rfq}/hitl/decision", json={"approved": True, "stage": "final_selection"}, timeout=120).raise_for_status()
    rows = []
    for item, d in zip(items, decisions):
        row = {"conflict_id": item["conflict_id"], "cpn": item["cpn"], "volume_no": item["volume_no"], "chosen": d["resolved_source"]}
        for s, v in sorted(item["available_sources"].items()):
            for k in ("price_conv", "price_original", "currency_original", "supp_name", "mfg_name", "moq", "pkg_qty", "lead_time", "unit_of_measure"):
                row[f"{s}.{k}"] = (v or {}).get(k)
        rows.append(row)
    return rows


def drive(folder_name, root, prefix, mon, timeout_min, retries):
    folder = os.path.join(root, folder_name)
    parts = folder_name.split("-")
    rfq = f"{prefix}{parts[1]}-{parts[2]}-{parts[3]}"
    out = {"batch": folder_name, "rfq": rfq, "status": "started", "attempts": 0, "notes": []}
    t_start = time.time()
    try:
        bom, qw, cs = classify(folder)
        out.update(bom=bom, quotewin=qw, costing=cs)
        for attempt in range(1, retries + 2):
            out["attempts"] = attempt
            adopted = mon.get(rfq).get("wf") in ("Running", "Completed") and attempt == 1
            if adopted:
                out["notes"].append("adopted a run that already existed (no upload)")
            else:
                for role, name in (("quotewin", qw), ("costing", cs)):
                    if name:
                        with open(os.path.join(folder, name), "rb") as fh:
                            r = requests.post(f"{UP}/api/rfq/{rfq}/inputs/{role}", headers=H(rfq), files={"file": (name, fh)}, timeout=600)
                        if r.status_code != 200:
                            raise RuntimeError(f"staging the {role} file answered HTTP {r.status_code}: {r.text[:200]}")
                with open(os.path.join(folder, bom), "rb") as fh:
                    r = requests.post(f"{UP}/api/rfq/upload", headers=H(rfq), data={"rfq_id": rfq, "force_run": "true"}, files={"bom_file": (bom, fh)}, timeout=900)
                if r.status_code != 200:
                    raise RuntimeError(f"upload answered HTTP {r.status_code}: {r.text[:300]}")
                up = r.json()
                out["upload"] = {k: up.get(k) for k in ("version", "staged_inputs")}
                time.sleep(2)
                mon.t = 0  # the cached snapshot still shows the previous run (often Failed): read the new one
            gate_done, gate_rows, state, t0 = False, [], "", time.time()
            while True:
                s = mon.get(rfq)
                wf = s.get("wf", "?")
                if wf in FAILED_STATES:
                    out["notes"].append(f"attempt {attempt}: workflow {wf}: {failure_reason(rfq)}")
                    state = "failed"
                    break
                if s.get("export_done") and wf in ("Completed", "Running"):
                    if wf == "Completed" or time.time() - t0 > 20:
                        state = "exported"
                        break
                if s.get("resolve_done") and s.get("hitl") and wf == "Running" and not gate_done and s.get("last_skill", "").endswith("resolve_final_selection"):
                    gate_rows = resolve_gate(rfq)
                    gate_done = True
                    log(f"{rfq}: review gate decided by policy ({len(gate_rows)} conflicts)")
                if s.get("hitl") and not s.get("resolve_done") and s.get("last_skill", "").endswith("standardize_scrub_bom") and s.get("last_status") == "completed" and time.time() - t0 > 90:
                    raise RuntimeError("the run waits for a QuoteWin upload: the batch has no QuoteWin the BOM accepts")
                if time.time() - t0 > timeout_min * 60:
                    out["notes"].append(f"attempt {attempt}: no export after {timeout_min} min (last step {s.get('last_skill')} {s.get('last_status')})")
                    state = "timeout"
                    break
                time.sleep(5)
            if state == "exported":
                break
        if state != "exported":
            out["status"] = f"not exported ({state})"
            return out
        collect(out, folder, rfq, gate_rows, t_start)
    except Exception as e:  # keep the batch's reason; the others go on
        out.update(status="error", error=f"{type(e).__name__}: {e}"[:500])
    return out


def steps_timeline(rfq, version):
    rows = psql(f"SELECT skill_code, step_status, to_char(at,'YYYY-MM-DD\"T\"HH24:MI:SS'), coalesce(left(detail,160),'') FROM rfq_step_events "
                f"WHERE rfq_id={q(rfq)} AND version={version} ORDER BY id")
    started, out = {}, []
    for ln in filter(None, rows.splitlines()):
        skill, status, at, detail = (ln.split("|", 3) + [""])[:4]
        if status == "running":
            started[skill] = dt.datetime.fromisoformat(at)
            continue
        secs = (dt.datetime.fromisoformat(at) - started[skill]).total_seconds() if skill in started else None
        out.append({"skill": skill, "status": status, "at_utc": at, "seconds": secs, "detail": detail})
    return out


def collect(out, folder, rfq, gate_rows, t_start):
    hdr = H(rfq)
    op = os.path.join(folder, "OP")
    os.makedirs(W(op), exist_ok=True)
    s = psql(f"SELECT version FROM rfq_process_tracking WHERE rfq_id={q(rfq)} AND is_active")
    ver = int(s)
    # 1. The workbook through the app's own download route (what the browser's report button gets), checked against the exporter's file.
    r = retry(lambda: requests.get(f"{BR}/api/bom/export/{rfq}/download", timeout=900), "workbook download")
    r.raise_for_status()
    name = re.search(r'filename="?([^";]+)"?', r.headers.get("content-disposition", "")).group(1)
    data = r.content
    with open(W(os.path.join(op, name)), "wb") as fh:
        fh.write(data)
    sha = hashlib.sha256(data).hexdigest()
    in_container = sh(["docker", "exec", EXP, "sha256sum", f"/app/exports/{name}"]).stdout.split()[:1]
    same = bool(in_container) and in_container[0] == sha
    sh(["docker", "cp", f"{EXP}:/app/exports/{name}.verify.json", W(os.path.join(op, name + ".verify.json"))])
    verify = {}
    try:
        with open(W(os.path.join(op, name + ".verify.json")), encoding="utf-8") as fh:
            verify = json.load(fh)
    except OSError:
        pass
    # 2. The numbers behind the app's Reports & Analytics screen.
    a = retry(lambda: requests.get(f"{BR}/api/rfq/{rfq}/analytics", headers=hdr, timeout=300), "analytics")
    if a.status_code == 200:
        with open(W(os.path.join(op, "analytics.json")), "w", encoding="utf-8") as fh:
            json.dump(a.json(), fh, indent=1, default=str)
    # 3. Mix check: the workbook must name its own RFQ and no other RFQ of this run.
    wb = openpyxl.load_workbook(W(os.path.join(op, name)), read_only=True, data_only=True)
    head = " ".join(str(c) for row in wb["Summary"].iter_rows(min_row=1, max_row=3, values_only=True) for c in row if c)
    sheets = wb.sheetnames
    run_inputs = [[c for c in row] for row in wb["Run Inputs"].iter_rows(values_only=True)] if "Run Inputs" in sheets else []
    manifest = {str(r[0]): r[1] for r in wb["Manifest"].iter_rows(values_only=True) if r and r[0]} if "Manifest" in sheets else {}
    wb.close()
    mixed = rfq not in head
    # 4. Flags and the review decisions.
    forced = psql(f"SELECT coalesce((execution_logs->'forced_run')::text,'') FROM rfq_file_telemetry WHERE rfq_id={q(rfq)} AND version={ver} AND file_role='BOM' AND is_active")
    forced = json.loads(forced) if forced.startswith("{") else None
    files = psql(f"SELECT string_agg(file_role || ' = ' || regexp_replace(file_path,'^.*[/\\\\]',''), '; ') FROM rfq_file_telemetry WHERE rfq_id={q(rfq)} AND version={ver} AND is_active")
    timeline = steps_timeline(rfq, ver)
    by_src = {}
    for g in gate_rows:
        by_src[g["chosen"]] = by_src.get(g["chosen"], 0) + 1
    if gate_rows:
        cols = sorted({k for g in gate_rows for k in g})
        with open(W(os.path.join(op, "Final_Selection_Conflicts_auto_resolved.csv")), "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=["conflict_id", "cpn", "volume_no", "chosen"] + [c for c in cols if c not in ("conflict_id", "cpn", "volume_no", "chosen")])
            w.writeheader()
            w.writerows(gate_rows)
    export_detail = next((t["detail"] for t in timeline if t["skill"].endswith("export_reports") and t["status"] == "completed"), "")
    flags = {
        "rfq": rfq, "batch_folder": out["batch"], "version": ver, "files_in_run": files, "workflow": "Completed or exported",
        "forced_run": forced, "forced": bool(forced and forced.get("unresolved_cells")),
        "final_selection": {"policy": POLICY, "conflicts_decided_by_policy": len(gate_rows), "by_source": by_src,
                            "note": "decided by rule, not by a person: see Final_Selection_Conflicts_auto_resolved.csv" if gate_rows else "no conflicts"},
        "export": {"workbook": name, "bytes": len(data), "sha256": sha, "same_file_as_exporter": same, "sheets": len(sheets), "detail": export_detail},
        "engine_check": {k: verify.get(k) for k in ("release_ready", "complete", "totals", "corrected", "elapsed_seconds", "error")},
        "run_inputs_sheet": run_inputs, "go_no_go": manifest.get("Go / no-go"), "error_cells_all_tabs": manifest.get("Error cells (all tabs)"),
        "mix_check": "FAILED: another RFQ's id or none in the Summary header" if mixed else "ok: the Summary names this RFQ",
        "minutes_total": round((time.time() - t_start) / 60, 1),
    }
    with open(W(os.path.join(op, "Run_Flags.json")), "w", encoding="utf-8") as fh:
        json.dump(flags, fh, indent=1, default=str)
    fb = openpyxl.Workbook()
    ws = fb.active
    ws.title = "Run Flags"
    for k, v in flags.items():
        ws.append([k, v if isinstance(v, (str, int, float, bool, type(None))) else json.dumps(v, default=str)])
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 28, 110
    ts = fb.create_sheet("Step timings")
    ts.append(["skill", "status", "at (UTC)", "seconds", "detail"])
    for t in timeline:
        ts.append([t["skill"], t["status"], t["at_utc"], t["seconds"], t["detail"]])
    fb.save(W(os.path.join(op, "Run_Flags.xlsx")))
    with open(W(os.path.join(op, "RUN_SUMMARY.md")), "w", encoding="utf-8") as fh:
        fh.write(f"# {rfq}  ({out['batch']})\n\n- Workbook: `{name}` ({len(data):,} bytes, sha256 `{sha[:16]}...`; same file the exporter wrote: {same})\n"
                 f"- Sheets: {len(sheets)}; GO / NO-GO: {manifest.get('Go / no-go')}; error cells: {manifest.get('Error cells (all tabs)')}\n"
                 f"- Export step: {export_detail}\n- Engine check: release_ready={verify.get('release_ready')}, formulas={(verify.get('totals') or {}).get('formulas')}, "
                 f"replaced by the engine={verify.get('corrected')}\n- Forced run: {flags['forced_run']}\n"
                 f"- Final selection: {len(gate_rows)} conflicts decided by policy ({POLICY}); by source {by_src}\n- Mix check: {flags['mix_check']}\n"
                 f"- Total minutes: {flags['minutes_total']}\n\nThe workbook is the file the app delivers, copied byte for byte. Flags, conflicts and timings are beside it.\n")
    dash = "skipped: scripts/rfq_dashboard_export.py not present yet"
    exporter = os.path.join(HERE, "rfq_dashboard_export.py")
    if os.path.exists(exporter):
        try:
            p = sh([sys.executable, exporter, "--rfq", rfq, "--out", os.path.join(op, "dashboard")], timeout=1200)
            dash = "ok" if p.returncode == 0 else f"failed ({p.returncode}): {(p.stderr or p.stdout).strip()[-300:]}"
        except Exception as e:
            dash = f"failed: {type(e).__name__}: {e}"[:300]
    out.update(status="done" if not mixed else "MIXED", workbook=name, op=op, forced=flags["forced"], conflicts=len(gate_rows), go_no_go=manifest.get("Go / no-go"),
               engine_release_ready=verify.get("release_ready"), dashboard=dash, minutes=flags["minutes_total"])
    log(f"{rfq}: DONE in {flags['minutes_total']} min -> {os.path.join(folder_short(out['batch']), 'OP')} (dashboard: {dash.split(':')[0]})")


def folder_short(name):
    return name[:28]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--prefix", default="R")
    ap.add_argument("--inflight", type=int, default=8)
    ap.add_argument("--ramp", type=int, default=0, help="run the first N batches alone and stop if one fails")
    ap.add_argument("--only", default="", help="comma list of batch-NN prefixes")
    ap.add_argument("--first", default="batch-03", help="runs first (the control)")
    ap.add_argument("--timeout-min", type=int, default=60)
    ap.add_argument("--retries", type=int, default=1)
    a = ap.parse_args()
    names = sorted(d for d in os.listdir(a.root) if d.startswith("batch-") and os.path.isdir(os.path.join(a.root, d)))
    if a.only:
        wanted = tuple(x.strip() for x in a.only.split(",") if x.strip())
        names = [n for n in names if n.startswith(wanted)]
    names.sort(key=lambda n: (not n.startswith(a.first), n))
    os.makedirs(RUN_DIR, exist_ok=True)
    done_flag = os.path.join(RUN_DIR, "bulk_run.done")
    if os.path.exists(done_flag):
        os.remove(done_flag)
    with open(os.path.join(RUN_DIR, "bulk_run.lock"), "w") as fh:
        fh.write(json.dumps({"pid": os.getpid(), "prefix": a.prefix, "started": dt.datetime.now().isoformat(), "batches": len(names)}))
    mon, t0, results = Monitor(a.prefix), time.time(), []

    def run(group, workers):
        with cf.ThreadPoolExecutor(max_workers=workers) as ex:
            return list(ex.map(lambda n: drive(n, a.root, a.prefix, mon, a.timeout_min, a.retries), group))

    head, tail = (names[:a.ramp], names[a.ramp:]) if a.ramp else ([], names)
    if head:
        log(f"ramp: {len(head)} batch(es) first: {[n[:9] for n in head]}")
        results += run(head, len(head))
        bad = [r for r in results if r["status"] != "done"]
        if bad:
            log("ramp FAILED, stopping: " + json.dumps([{k: r.get(k) for k in ("batch", "status", "error", "notes")} for r in bad], default=str)[:1500])
            tail = []
    if tail:
        log(f"releasing {len(tail)} batch(es), {a.inflight} in flight")
        results += run(tail, a.inflight)
    summary = {"prefix": a.prefix, "seconds": round(time.time() - t0), "policy": POLICY, "results": results,
               "counts": {s: sum(1 for r in results if r["status"] == s) for s in sorted({r["status"] for r in results})}}
    with open(os.path.join(RUN_DIR, f"bulk_{a.prefix}_result.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=1, default=str)
    with open(W(os.path.join(a.root, f"BULK_RUN_{a.prefix}_INDEX.md")), "w", encoding="utf-8") as fh:
        fh.write(f"# Bulk run {a.prefix}: {summary['counts']} in {summary['seconds']} s\n\n| Batch | RFQ | Status | GO/NO-GO | Forced | Conflicts auto-resolved | Minutes |\n|---|---|---|---|---|---|---|\n")
        for r in sorted(results, key=lambda r: r["batch"]):
            fh.write(f"| {r['batch']} | {r['rfq']} | {r['status']} | {r.get('go_no_go', '')} | {r.get('forced', '')} | {r.get('conflicts', '')} | {r.get('minutes', '')} |\n")
    os.remove(os.path.join(RUN_DIR, "bulk_run.lock"))
    if not [r for r in results if r["status"] != "done"]:
        with open(done_flag, "w") as fh:
            fh.write(dt.datetime.now().isoformat())
    print("STATUS", summary["counts"], flush=True)
    print("SECONDS", summary["seconds"], flush=True)
    return 0 if summary["counts"].get("done") == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
