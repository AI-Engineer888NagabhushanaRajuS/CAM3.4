"""Proof (11 Nov): does the Formula Engine keep a delivered workbook dynamic? Change an input cell, and every formula that depends on it must follow.

For each edit: the engine (set_value + re-read every formula) is compared, cell by cell over ALL formula cells, with native Excel making the same edit
(COM: open the delivered file, set the value, CalculateFullRebuild, SaveCopyAs). Also checks the delivered file itself (formulas + cached values, calcPr).
usage: python engine_dynamic_proof.py [workbook.xlsx]      Needs Excel on this machine. Writes nothing into the repo except what it prints.
"""
import datetime
import math
import os
import re
import sys
import tempfile
import time
import zipfile

sys.path.insert(0, r"C:\CAM[3.4]-RFQ_centum\CAM-Source\mcp-tools\shared\formula_engine\engine")
import excel_formula_engine as fe  # noqa: E402
import openpyxl  # noqa: E402
from openpyxl.utils import get_column_letter  # noqa: E402
from openpyxl.utils.datetime import to_excel  # noqa: E402

PATH = sys.argv[1] if len(sys.argv) > 1 else r"C:\CAM[3.4]-RFQ_centum\acceptance_evidence\spec019\create-rfq\RFQ-000032-report.xlsx"
# (sheet, row, col, new value): real input cells found by walking the dependency graph, chosen for their fan-out in different tabs
EDITS = [
    ("Scrap Factor", 4, 1, 2.0),
    ("Batch Settings", 3, 3, 400.0),
    ("7.0 CBOM VL-1", 228, 12, 0.25),
    ("7.0 CBOM VL-1", 2, 11, 2.0),
    ("7.0 CBOM VL-2", 238, 9, 3.0),
    ("Ex Inv VL-1", 1, 38, 30.0),
    ("Lead Time Consolidated", 28, 2, 5.0),
    ("CBOM", 495, 58, 3000.0),
]
OUT = os.path.join(tempfile.gettempdir(), "engine_dynamic_proof")
os.makedirs(OUT, exist_ok=True)


def eq(e, x):
    if fe.is_error(e):
        return str(e) == str(x)
    if fe.is_blank(e) or e == "":
        return x in (None, "")
    if isinstance(x, (datetime.datetime, datetime.date)):
        x = to_excel(x)
    if isinstance(e, bool) or isinstance(x, bool):
        return e == x
    if isinstance(e, (int, float)) and isinstance(x, (int, float)):
        return math.isclose(float(e), float(x), rel_tol=1e-9, abs_tol=1e-9)
    return e == x


def read_all(wb):
    return {(sd.title, r, c): wb.cell_value_now(k, r, c) for k, sd in wb.sheets.items() for (r, c) in list(sd.formulas)}


def addr(k):
    return f"{k[0]}!{get_column_letter(k[2])}{k[1]}"


# ---- the delivered file itself
with zipfile.ZipFile(PATH) as z:
    wbxml = z.read("xl/workbook.xml").decode("utf8")
    calc = re.search(r"<calcPr[^>]*/>", wbxml)
    print("delivered workbook calcPr:", calc.group(0) if calc else "(none)")
fo = openpyxl.load_workbook(PATH)
fv = openpyxl.load_workbook(PATH, data_only=True)
nform = nval = 0
for ws in fo.worksheets:
    for row in ws.iter_rows():
        for c in row:
            if c.data_type == "f":
                nform += 1
                nval += fv[ws.title][c.coordinate].value is not None
print(f"delivered workbook: {nform} formula cells, {nval} carry a stored value\n")

# ---- engine baseline
t = time.time()
wb = fe.Workbook(PATH)
base = read_all(wb)
print(f"engine: loaded + evaluated {len(base)} formulas in {time.time() - t:.1f}s; pivot snapshots in file: {len(wb.pivot_snapshots)}")
arrayish = {k for k in base if re.search(r"INDEX\(.*\*.*,\s*0\)|MATCH\(\s*1\s*,\s*INDEX", str(wb.get_formula(k[0], k[1], k[2]) or ""))}
print(f"array-style INDEX/MATCH formula cells in the workbook: {len(arrayish)}\n")

# ---- engine side of every edit
engine = {}
for (sheet, r, c, new) in EDITS:
    sd = wb._sheet(sheet)
    old = sd.cached.get((r, c))
    t = time.time()
    wb.set_value(sheet, r, c, new)
    after = read_all(wb)
    secs = time.time() - t
    changed = {k for k in base if not eq(after[k], base[k])}
    notes = [n for n in wb.notes if n.startswith("pivot-source-dirty")]
    engine[(sheet, r, c)] = {"old": old, "new": new, "after": after, "changed": changed, "secs": secs, "pivot": notes}
    wb.set_value(sheet, r, c, old)                     # put it back and prove the round trip returns the baseline
    back = read_all(wb)
    engine[(sheet, r, c)]["restored"] = all(eq(back[k], base[k]) for k in base)

# ---- native Excel, same edits
import win32com.client  # noqa: E402

xl = win32com.client.DispatchEx("Excel.Application")
xl.Visible = False
xl.DisplayAlerts = False
excel_files = {}
try:
    for (sheet, r, c, new) in EDITS:
        t = time.time()
        book = xl.Workbooks.Open(PATH, 0, True)        # read only: the delivered file is never touched
        book.Worksheets(sheet).Cells(r, c).Value = new
        xl.CalculateFullRebuild()
        dst = os.path.join(OUT, f"edit_{re.sub('[^A-Za-z0-9]+', '_', sheet)}_{r}_{c}.xlsx")
        if os.path.exists(dst):
            os.remove(dst)
        book.SaveCopyAs(dst)
        book.Close(False)
        excel_files[(sheet, r, c)] = (dst, time.time() - t)
finally:
    xl.Quit()

# ---- compare every formula cell, engine vs Excel
print(f"{'edit (sheet!cell old -> new)':44} {'engine changed':>14} {'Excel changed':>13} {'all equal':>14} {'changed equal':>14} {'array-style':>11} {'engine s':>8} {'restored':>8}")
for (sheet, r, c, new) in EDITS:
    e = engine[(sheet, r, c)]
    dst, xsecs = excel_files[(sheet, r, c)]
    xw = openpyxl.load_workbook(dst, data_only=True)
    xval = {k: xw[k[0]].cell(row=k[1], column=k[2]).value for k in base}
    xchanged = {k for k in base if not eq(base[k], xval[k])}
    equal_all = sum(eq(e["after"][k], xval[k]) for k in base)
    bad = [k for k in base if not eq(e["after"][k], xval[k])]
    ch = e["changed"] | xchanged
    equal_ch = sum(eq(e["after"][k], xval[k]) for k in ch)
    arr = [k for k in ch if k in arrayish]
    arr_ok = sum(eq(e["after"][k], xval[k]) for k in arr)
    name = f"{addr((sheet, r, c))} {e['old']:g} -> {new:g}"
    print(f"{name:44} {len(e['changed']):>14} {len(xchanged):>13} {equal_all:>7}/{len(base)} {equal_ch:>7}/{len(ch)} {arr_ok:>5}/{len(arr):<5} {e['secs']:>8.1f} {str(e['restored']):>8}")
    for k in bad[:4]:
        print(f"    MISMATCH {addr(k)}: engine {e['after'][k]!r} vs Excel {xval[k]!r}  (base {base[k]!r})")
    if e["pivot"]:
        print("    engine notes:", e["pivot"][:2])
    if e["changed"] != xchanged:
        print(f"    changed-set differs: only engine {len(e['changed'] - xchanged)}, only Excel {len(xchanged - e['changed'])}")
