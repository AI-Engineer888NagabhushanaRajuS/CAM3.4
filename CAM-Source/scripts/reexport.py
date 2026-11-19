#!/usr/bin/env python
"""Re-runs ONLY the export step for RFQs whose workbook was written before a reporting fix, one at a time.

    python scripts/reexport.py --prefix B --before "2026-11-18 10:23"      # UTC, as rfq_step_events.at stores it

Uses the same call the in-app edit-and-regenerate uses (fastapi-router/edit_regenerate.call_reporting_export, inside the python-bridge
container): the data stays as the pipeline left it, the stage and the review state are not touched, and a new workbook version is written
next to the old one (the download route serves the newest). Prints one line per RFQ.
"""
import argparse
import subprocess
import sys
import time

PG, BRIDGE = "cam-e2e-postgres-1", "cam-e2e-python-bridge-1"


def psql(sql):
    r = subprocess.run(["docker", "exec", "-i", PG, "psql", "-U", "centum", "-d", "file_metadata_db_2", "-tA", "-F", "|", "-c", sql],
                       capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[:300])
    return [ln.split("|") for ln in r.stdout.strip().splitlines() if ln]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--before", required=True)
    a = ap.parse_args()
    like = a.prefix.replace("'", "") + "%"
    rows = psql(
        "SELECT t.rfq_id, t.version, max(e.at) FROM rfq_process_tracking t JOIN rfq_step_events e ON e.rfq_id=t.rfq_id AND e.version=t.version "
        f"WHERE t.is_active AND t.rfq_id LIKE '{like}' AND e.skill_code='centum_reporting__export_reports' AND e.step_status='completed' "
        "GROUP BY 1,2 ORDER BY 1")
    todo = [(r, int(v)) for r, v, at in rows if at < a.before]
    print(f"{len(todo)} workbook(s) written before {a.before} UTC", flush=True)
    bad = 0
    for rfq, ver in todo:
        key = rfq if ver == 1 else f"{rfq}__v{ver}"
        t0 = time.time()
        code = ("import json, edit_regenerate as e; r = e.call_reporting_export(%r); "
                "print(json.dumps({k: r.get(k) for k in ('status', 'workbook_path', 'release_ready')}))") % key
        p = subprocess.run(["docker", "exec", "-w", "/app/fastapi-router", BRIDGE, "python", "-c", code],
                           capture_output=True, text=True, timeout=1800)
        ok = p.returncode == 0 and '"success"' in p.stdout
        bad += not ok
        print(f"{'OK ' if ok else 'BAD'} {key} in {time.time() - t0:.0f} s: {(p.stdout.strip() or p.stderr.strip())[-300:]}", flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
