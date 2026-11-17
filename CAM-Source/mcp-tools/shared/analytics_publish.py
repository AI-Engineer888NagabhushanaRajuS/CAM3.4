"""Parquet snapshots of one RFQ for the editable BI dashboard (SPEC-026, phase 1).

Superset never opens a .duckdb file: DuckDB does not queue cross-process access, so a dashboard query could make a pipeline step fail.
`publish(rfq_id)` copies the RFQ's rows out of reports.duckdb / cbom.duckdb while holding the shared advisory lock
(db.duckdb_file_lock, the one every pipeline service takes) for as short a time as possible: it attaches both files READ-ONLY, copies the
rows into an in-memory DuckDB, detaches and releases. Then, without the lock, it writes one Parquet file per table to
<analytics root>/<rfq_id>/<table>.parquet (temp file + os.replace, so a reader never sees half a file), plus three tables read from the
delivered workbook: feasibility_lines (tab "Feasibility & Risk"), run_inputs (tab "Run Inputs") and kpi (one row per figure, the same
figures the Classic view reads through rfq_analytics.analytics). Every table is written even when it has no rows, so the dashboard's
read_parquet globs always match. The rfq_id column always holds the bare RFQ id (never the internal "__v2" key), which is what the
guest token's row-level-security clause filters on.

Run inside the reporting container (it has duckdb, openpyxl, the lock and the data):
  docker exec cam-e2e-reporting-mcp-server-1 python /app/mcp-tools/shared/analytics_publish.py C03-CE-005570
"""
import json
import os
import re
import sys
from contextlib import nullcontext

import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DB_DIR = os.environ.get("REPORTING_DATABASE_DIR", os.path.join(REPO, "database"))
EXPORTS_DIR = os.environ.get("REPORTING_EXPORTS_DIR", os.path.join(REPO, "exports"))
ANALYTICS_DIR = os.environ.get("CAM_ANALYTICS_DIR", os.path.join(DB_DIR, "analytics"))
VALID_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def _lock_and_key(rfq_id):
    """The pipeline's advisory lock and the RFQ's active DuckDB key (bare id for version 1, "<id>__v<n>" after an edit)."""
    router = os.path.join(REPO, "fastapi-router")
    if router not in sys.path:
        sys.path.append(router)
    import db  # noqa: PLC0415  (only present where the services run)
    try:
        key = db.versioned_key(rfq_id, db.get_active_version(rfq_id))
    except Exception:
        key = rfq_id                       # an RFQ created outside the tracked upload flow keeps its bare id
    return db.duckdb_file_lock(), key


def _slug(value):
    return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")[:60] or "unknown_rfq"


def latest_workbook(key, exports_dir=EXPORTS_DIR):
    pattern = re.compile(rf"^CBOM_Report_{re.escape(_slug(key))}_\d{{8}}_\d{{6}}(_[0-9a-f]{{8}})?\.xlsx$")
    names = [n for n in (os.listdir(exports_dir) if os.path.isdir(exports_dir) else []) if pattern.match(n)]
    return max((os.path.join(exports_dir, n) for n in names), key=os.path.getmtime, default=None)


def _snapshot(mem, reports_db, cbom_db, key, rfq_id):
    """Copy every table with an rfq_id column into `mem` (UUIDs as text, rfq_id rewritten to the bare id). Returns the table names."""
    mem.execute(f"ATTACH '{reports_db}' AS rep (READ_ONLY)")
    if os.path.exists(cbom_db):
        mem.execute(f"ATTACH '{cbom_db}' AS cb (READ_ONLY)")
    try:
        cols = mem.execute(
            "SELECT database_name, table_name, column_name, data_type FROM duckdb_columns() "
            "WHERE database_name IN ('rep', 'cb') AND schema_name = 'main' ORDER BY database_name, table_name, column_index").fetchall()
        tables = {}
        for dbn, tbl, col, typ in cols:
            tables.setdefault((dbn, tbl), []).append((col, typ))
        names = []
        for (dbn, tbl), columns in tables.items():
            if "rfq_id" not in [c for c, _ in columns]:
                continue
            select = ", ".join("CAST(? AS VARCHAR) AS rfq_id" if c == "rfq_id" else (f'CAST("{c}" AS VARCHAR) AS "{c}"' if t == "UUID" else f'"{c}"')
                               for c, t in columns)
            mem.execute(f'CREATE OR REPLACE TABLE main."{tbl}" AS SELECT {select} FROM {dbn}.main."{tbl}" WHERE rfq_id = ?', [rfq_id, key])
            names.append(tbl)
        return names
    finally:
        mem.execute("DETACH rep")
        if os.path.exists(cbom_db):
            mem.execute("DETACH cb")


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _tab_rows(path, tab, header_first):
    """Rows of one workbook tab as dicts, starting at the first row whose first cell is `header_first`; stops at the first blank row."""
    import openpyxl  # noqa: PLC0415
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        if tab not in wb.sheetnames:
            return []
        rows = list(wb[tab].iter_rows(values_only=True))
    finally:
        wb.close()
    start = next((i for i, r in enumerate(rows) if r and r[0] == header_first), None)
    if start is None:
        return []
    head = [str(h).strip() if h is not None else "" for h in rows[start]]
    out = []
    for r in rows[start + 1:]:
        if not r or r[0] in (None, ""):
            break
        out.append({h: v for h, v in zip(head, r) if h})
    return out


def _vol(label):
    return str(label).replace("VL-", "").strip()


def kpi_rows(rfq_id, a):
    """One row per figure: (rfq_id, metric, volume_no, value, text). Every value comes from rfq_analytics.analytics(workbook)."""
    out = []
    add = lambda metric, value, vol=None, text=None: out.append((rfq_id, metric, vol, value, text))  # noqa: E731
    s = a.get("summary") or {}
    for key, metric in (("totals", "cost_per_set"), ("ext_vol_conv_price", "ext_vol_cost"), ("moq_cost", "moq_cost"), ("moq_pct", "moq_share")):
        for vol, value in (s.get(key) or {}).items():
            add(metric, value, _vol(vol))
    for vol, value in (a.get("excess_cost") or {}).items():
        add("excess_cost", value, _vol(vol))
    for i, t in enumerate(a.get("cashflow_totals") or []):
        vol = _vol(s["volumes"][i]) if i < len(s.get("volumes") or []) else str(i + 1)
        add("buy_value", t.get("buy"), vol)
        add("final_buy_value", t.get("final_buy"), vol)
    cbom = a.get("cbom") or {}
    if cbom:
        add("cbom_lines", _num(cbom.get("rows")))
        add("priced_lines", _num(cbom.get("priced")))
        add("priced_ratio", cbom["priced"] / cbom["rows"] if cbom.get("rows") else None)
    add("uncosted_parts", _num(a.get("uncosted_parts")))
    for kind, n in (a.get("exceptions") or {}).items():
        add(f"exceptions_{kind}", _num(n))
    m = a.get("manifest") or {}
    add("error_cells", _num(m.get("error_cells")))
    add("go", None if m.get("go_no_go") is None else float(m["go_no_go"] == "GO"), text=m.get("go_no_go"))
    add("workbook", None, text=a.get("workbook"))
    add("currency", None, text=a.get("currency"))
    return out


def _workbook_tables(mem, rfq_id, path):
    """feasibility_lines, run_inputs and kpi from the delivered workbook (empty tables when there is none)."""
    mem.execute("CREATE OR REPLACE TABLE feasibility_lines (rfq_id VARCHAR, fg VARCHAR, assembly VARCHAR, part_number VARCHAR, mpn VARCHAR, "
                "description VARCHAR, commodity VARCHAR, qty_per DOUBLE, part_status VARCHAR, lead_time_weeks DOUBLE, verdict VARCHAR, "
                "risk VARCHAR, reasons VARCHAR)")
    mem.execute("CREATE OR REPLACE TABLE run_inputs (rfq_id VARCHAR, input VARCHAR, required VARCHAR, status VARCHAR, meaning VARCHAR)")
    mem.execute("CREATE OR REPLACE TABLE kpi (rfq_id VARCHAR, metric VARCHAR, volume_no VARCHAR, value DOUBLE, text VARCHAR)")
    for name, ddl in WB_DDL.items():
        mem.execute(f"CREATE OR REPLACE TABLE {name} ({ddl})")
    if not path:
        return
    t = lambda v: None if v in (None, "") else str(v)  # noqa: E731
    feas = [(rfq_id, t(r.get("FG")), t(r.get("Assembly")), t(r.get("Part Number")), t(r.get("MPN")), t(r.get("Description")),
             t(r.get("Commodity")), _num(r.get("Qty per")), t(r.get("Part Status")), _num(r.get("Best lead time (weeks)")),
             t(r.get("Verdict")), t(r.get("Risk")), t(r.get("Reasons"))) for r in _tab_rows(path, "Feasibility & Risk", "FG")]
    if feas:
        mem.executemany("INSERT INTO feasibility_lines VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", feas)
    runs = [(rfq_id, t(r.get("Input")), t(r.get("Required")), t(r.get("Status")), t(r.get("What it means for this report")))
            for r in _tab_rows(path, "Run Inputs", "Input")]
    if runs:
        mem.executemany("INSERT INTO run_inputs VALUES (?, ?, ?, ?, ?)", runs)
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    import rfq_analytics  # noqa: PLC0415
    a = rfq_analytics.analytics(path)
    for name, rows in [("kpi", kpi_rows(rfq_id, a))] + list(wb_tables(rfq_id, a).items()):
        if rows:
            mem.executemany(f"INSERT INTO {name} VALUES ({', '.join('?' * len(rows[0]))})", rows)


# The formula-driven tabs (Summary, Price Control, Lead Time Consolidated, Batchwise Cashflow, Ex Inv) are computed by the workbook's
# formulas and re-checked by the Formula Engine; reports.duckdb keeps pre-formula values that differ (SPEC-026, decisions). The figure
# charts therefore read these wb_* tables, taken from the delivered workbook; the line-level tables come from DuckDB.
WB_DDL = {
    "wb_summary": "rfq_id VARCHAR, assembly VARCHAR, volume_no VARCHAR, cost_per_set DOUBLE",
    "wb_price_control": "rfq_id VARCHAR, price_control VARCHAR, ext_price DOUBLE, ext_vol_cost DOUBLE, share DOUBLE",
    "wb_lead_time": "rfq_id VARCHAR, lead_time_weeks VARCHAR, weeks_sort DOUBLE, parts DOUBLE, share DOUBLE",
    "wb_cashflow": "rfq_id VARCHAR, volume_no VARCHAR, supplier_type VARCHAR, buy_value DOUBLE, final_buy_value DOUBLE",
    "wb_commodity_excess": "rfq_id VARCHAR, volume_no VARCHAR, commodity VARCHAR, net_excess_cost DOUBLE",
}


def wb_tables(rfq_id, a):
    s = a.get("summary") or {}
    vols = s.get("volumes") or []
    out = {"wb_summary": [(rfq_id, str(f.get("assembly")), _vol(v), f.get(v)) for f in s.get("fgs") or [] for v in vols]}
    out["wb_price_control"] = [(rfq_id, p["label"], p["ext_price"], p["ext_vol_cost"], p["pct"]) for p in a.get("price_control") or []]
    out["wb_lead_time"] = [(rfq_id, w["weeks"] or "none", _weeks(w["weeks"]), w["count"], w["pct"]) for w in a.get("lead_time") or []]
    out["wb_cashflow"] = [(rfq_id, _vol(vols[i]) if i < len(vols) else str(i + 1), c["type"], c["buy"], c["final_buy"])
                          for i, block in enumerate(a.get("cashflow") or []) for c in block]
    out["wb_commodity_excess"] = [(rfq_id, _vol(v), c, x) for v, by in (a.get("commodity_excess") or {}).items() for c, x in by.items()]
    return out


def _weeks(label):
    try:
        return float(label)
    except (TypeError, ValueError):
        return None


def publish(rfq_id, *, reports_db=None, cbom_db=None, out_root=ANALYTICS_DIR, exports_dir=EXPORTS_DIR, lock_and_key=None):
    """Write <out_root>/<rfq_id>/<table>.parquet for every table. Returns {"rfq_id", "dir", "tables": {name: rows}, "workbook"}."""
    if not isinstance(rfq_id, str) or not VALID_ID.match(rfq_id):
        raise ValueError("rfq_id must be letters, digits, '-' or '_' (at most 80)")
    lock, key = (lock_and_key or _lock_and_key)(rfq_id)
    reports_db = reports_db or os.path.join(DB_DIR, "reports.duckdb")
    cbom_db = cbom_db or os.path.join(DB_DIR, "cbom.duckdb")
    mem = duckdb.connect()
    try:
        with lock:                                   # held only while the two files are attached and copied
            names = _snapshot(mem, reports_db, cbom_db, key, rfq_id)
        workbook = latest_workbook(key, exports_dir)
        _workbook_tables(mem, rfq_id, workbook)
        names += ["feasibility_lines", "run_inputs", "kpi", *WB_DDL]
        out_dir = os.path.join(out_root, rfq_id)
        os.makedirs(out_dir, exist_ok=True)
        counts = {}
        for name in sorted(set(names)):
            final = os.path.join(out_dir, f"{name}.parquet")
            tmp = final + ".tmp"
            mem.execute(f"COPY (SELECT * FROM main.\"{name}\" ORDER BY ALL) TO '{tmp}' (FORMAT parquet, COMPRESSION zstd)")
            os.replace(tmp, final)
            counts[name] = mem.execute(f'SELECT count(*) FROM main."{name}"').fetchone()[0]
        return {"rfq_id": rfq_id, "dir": out_dir, "tables": counts, "workbook": os.path.basename(workbook) if workbook else None}
    finally:
        mem.close()


def published_rfqs(out_root=ANALYTICS_DIR):
    # listdir, not glob: the repo folder name holds square brackets, which glob reads as a pattern
    names = os.listdir(out_root) if os.path.isdir(out_root) else []
    return sorted(n for n in names if os.path.exists(os.path.join(out_root, n, "kpi.parquet")))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: analytics_publish.py <rfq_id>")
    print(json.dumps(publish(sys.argv[1]), indent=1))
