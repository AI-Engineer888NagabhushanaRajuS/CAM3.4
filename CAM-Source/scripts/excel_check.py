#!/usr/bin/env python
"""Checks each delivered workbook against native Excel: every formula cell's stored value (what CAM delivered) against Excel's own
full recalculation of the same file. Windows with Excel installed (pywin32).

    python scripts/excel_check.py --root "<folder holding batch-NN-.../OP>"        # every batch's newest CBOM_Report_*.xlsx
    python scripts/excel_check.py --file some.xlsx                                  # one workbook

Writes <OP>/Excel_Check.json (per tab: formulas, agree; up to 25 disagreeing cells with formula, delivered and Excel value) and prints
one line per workbook. Excel is the reference the client opens the file with, so a disagreement is a defect to fix, not noise.
"""
import argparse
import json
import math
import os
import shutil
import sys
import tempfile

import openpyxl


def same(a, b):
    if a in (None, "") and b in (None, ""):
        return True
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
    return a == b


def excel_recalc(src, dst):
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    xl = win32com.client.DispatchEx("Excel.Application")
    xl.Visible = False
    xl.DisplayAlerts = False
    try:
        wb = xl.Workbooks.Open(os.path.abspath(src), UpdateLinks=0, ReadOnly=True)
        xl.CalculateFullRebuild()
        wb.SaveAs(os.path.abspath(dst), FileFormat=51)
        wb.Close(False)
    finally:
        xl.Quit()
        pythoncom.CoUninitialize()


def check(path):
    tmp = tempfile.mkdtemp(prefix="cam-xl-")
    try:
        src = os.path.join(tmp, "delivered.xlsx")
        dst = os.path.join(tmp, "excel.xlsx")
        shutil.copyfile(path, src)
        excel_recalc(src, dst)
        forms = openpyxl.load_workbook(src, data_only=False)
        stored = openpyxl.load_workbook(src, data_only=True)
        xl = openpyxl.load_workbook(dst, data_only=True)
        out = {"workbook": os.path.basename(path), "sheets": {}, "total": 0, "agree": 0, "differs": []}
        for ws in forms.worksheets:
            n = a = 0
            for row in ws.iter_rows():
                for cell in row:
                    if cell.data_type != "f":
                        continue
                    n += 1
                    d, e = stored[ws.title][cell.coordinate].value, xl[ws.title][cell.coordinate].value
                    if same(d, e):
                        a += 1
                    elif len(out["differs"]) < 25:
                        out["differs"].append({"sheet": ws.title, "cell": cell.coordinate, "formula": str(cell.value)[:300],
                                               "delivered": repr(d), "excel": repr(e)})
            if n:
                out["sheets"][ws.title] = {"formulas": n, "agree": a}
                out["total"] += n
                out["agree"] += a
        # Excel's own errors in the recalculated file are listed too: a #VALUE! in Excel is a defect even where CAM stored the same
        out["excel_error_cells"] = sum(1 for ws in xl.worksheets for row in ws.iter_rows(values_only=True)
                                       for v in row if isinstance(v, str) and v.startswith("#") and v.rstrip("!?/0").upper() in
                                       ("#N/A", "#VALUE", "#REF", "#DIV", "#NAME", "#NUM", "#NULL"))
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def newest_report(op):
    files = [f for f in os.listdir(op) if f.startswith("CBOM_Report_") and f.endswith(".xlsx")]
    return max((os.path.join(op, f) for f in files), key=os.path.getmtime) if files else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root")
    ap.add_argument("--file")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    targets = []
    if a.file:
        targets.append((a.file, None))
    else:
        for d in sorted(os.listdir(a.root)):
            op = os.path.join(a.root, d, "OP")
            if d.startswith("batch-") and os.path.isdir(op) and (not a.only or d.startswith(tuple(a.only.split(",")))):
                f = newest_report(op)
                if f:
                    targets.append((f, op))
    bad = 0
    for f, op in targets:
        try:
            r = check(f)
        except Exception as e:
            print(f"ERROR {os.path.basename(f)}: {type(e).__name__}: {e}", flush=True)
            bad += 1
            continue
        if op:
            with open(os.path.join(op, "Excel_Check.json"), "w", encoding="utf-8") as fh:
                json.dump(r, fh, indent=1)
        ok = r["agree"] == r["total"] and not r["excel_error_cells"]
        bad += not ok
        print(f"{'OK ' if ok else 'BAD'} {r['workbook']}: {r['agree']} of {r['total']} formula cells agree with Excel; "
              f"Excel error cells {r['excel_error_cells']}" + ("" if ok else f"; first: {r['differs'][:2]}"), flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
