"""Scheduled, read-only sync of CAM's live DuckDB files into this repo's own
database/ folder (containerization Phase 0, see docs/SESSION-SUMMARY.md and
mcp-tools/reporting/superset/config.py's migration note).

Why this exists: BuLLMQuote-SRIM's reporting pipeline has no ETL scripts of
its own -- cbom.duckdb/input_db.duckdb/reports.duckdb are produced entirely
by CAM's own live pipeline (quote_win_to_database.py, scrub_bom_to_database.py,
costing_sheet_to_database.py, erp_to_database.py, running continuously at
C:\\Users\\ADMIN\\Documents\\SRIM\\Tools\\I n D\\centum intake). A one-time copy
goes stale the moment CAM processes another RFQ. This script re-runs that
same copy on a schedule (invoked by a Windows Scheduled Task -- see
register_sync_task.ps1 in this same folder) so this repo's own copy stays
reasonably fresh without ever writing back to CAM.

Safety: uses DuckDB's own read-only ATTACH + COPY FROM DATABASE, never a raw
OS file copy -- CAM's files are actively written by a live system, and a raw
copy could grab a half-written file mid-write. The source is NEVER opened
read-write. Every copy is verified (row counts per table) before being
promoted into place; a failed/mismatched copy is left as a .copying temp file
and the previous good copy is left untouched, so a sync failure never leaves
this repo's data in a half-updated state.

Exit code 0 on full success (or nothing-to-do), 1 if any file failed
verification -- suitable for a scheduled task to alert on.
"""
import os
import sys
import time
import duckdb

SRC_DIR = r"C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum intake\database"
DST_DIR = os.path.dirname(os.path.abspath(__file__))

FILES = ["input_db.duckdb", "cbom.duckdb", "reports.duckdb"]


def table_counts(con, schema_prefix=""):
    rows = con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema NOT IN ('information_schema','pg_catalog')"
    ).fetchall()
    counts = {}
    for (name,) in rows:
        qname = f'{schema_prefix}"{name}"' if schema_prefix else f'"{name}"'
        try:
            counts[name] = con.execute(f"SELECT count(*) FROM {qname}").fetchone()[0]
        except Exception as e:
            counts[name] = f"ERROR: {e}"
    return counts


def sync_one(fname: str) -> bool:
    src_path = os.path.join(SRC_DIR, fname)
    dst_path = os.path.join(DST_DIR, fname)
    tmp_path = dst_path + ".copying"

    if not os.path.exists(src_path):
        print(f"[{fname}] SKIP -- source not found at {src_path}")
        return True

    if os.path.exists(tmp_path):
        os.remove(tmp_path)

    t0 = time.time()
    con = duckdb.connect(":memory:")
    try:
        con.execute(f"ATTACH '{src_path}' AS src (READ_ONLY)")
        con.execute(f"ATTACH '{tmp_path}' AS dst")
        con.execute("COPY FROM DATABASE src TO dst")
        src_counts = table_counts(con, "src.")
    finally:
        con.close()

    con2 = duckdb.connect(tmp_path, read_only=True)
    try:
        dst_counts = table_counts(con2)
    finally:
        con2.close()

    mismatches = {
        k: (src_counts.get(k), dst_counts.get(k))
        for k in set(src_counts) | set(dst_counts)
        if src_counts.get(k) != dst_counts.get(k)
    }
    if mismatches:
        print(f"[{fname}] FAILED verification, leaving previous copy in place: {mismatches}")
        return False

    if os.path.exists(dst_path):
        os.remove(dst_path)
    os.rename(tmp_path, dst_path)
    print(f"[{fname}] synced in {time.time() - t0:.1f}s, {len(dst_counts)} tables verified")
    return True


def main() -> int:
    ok = True
    for fname in FILES:
        ok = sync_one(fname) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
