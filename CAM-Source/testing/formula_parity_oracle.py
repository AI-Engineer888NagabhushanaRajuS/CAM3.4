"""Golden parity oracle for generated CAM workbooks (SPEC-018 first gate).

A generated export keeps two things per formula cell: the formula, and the value the generator cached.
LibreOffice recalculates every formula from the same inputs. A cell is at parity when the cached value
equals the recalculated one. Parity is the gate a dynamic-recalculation engine must pass before it is
trusted; this module only measures, it does not recalculate anything itself.
"""
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import openpyxl

LO_CANDIDATES = [
    os.environ.get("LIBREOFFICE_BIN", ""),
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
]

# Forces LibreOffice to recalculate OOXML formulas on load (its default keeps the cached values).
_RECALC_ALWAYS = """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<item oor:path="/org.openoffice.Office.Calc/Formula/Load"><prop oor:name="OOXMLRecalcMode" oor:op="fuse"><value>0</value></prop></item>
</oor:items>
"""


def find_libreoffice():
    for candidate in LO_CANDIDATES:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def recalculate(src: Path, workdir: Path) -> Path:
    """Return a copy of src recalculated by LibreOffice, written under workdir."""
    lo = find_libreoffice()
    if lo is None:
        raise RuntimeError("LibreOffice not found (set LIBREOFFICE_BIN)")
    profile = workdir / "lo_profile"
    (profile / "user").mkdir(parents=True, exist_ok=True)
    (profile / "user" / "registrymodifications.xcu").write_text(_RECALC_ALWAYS, encoding="utf-8")
    out = workdir / "recalc"
    out.mkdir(exist_ok=True)
    subprocess.run(
        [lo, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--norestore",
         "--convert-to", "xlsx", "--outdir", str(out), str(src)],
        check=True, timeout=600, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    recalculated = out / src.name
    if not recalculated.exists():
        raise RuntimeError(f"LibreOffice produced no file for {src.name}")
    return recalculated


def _same(cached, recalculated) -> bool:
    if cached in (None, "") and recalculated in (None, ""):
        return True
    if isinstance(cached, (int, float)) and isinstance(recalculated, (int, float)):
        return math.isclose(cached, recalculated, rel_tol=1e-9, abs_tol=1e-9)
    return cached == recalculated


def compare(generated: Path, recalculated: Path) -> dict:
    """Compare every formula cell that stores a cached value with its LibreOffice recalculation.

    formula_cells counts only cells with a cached value; uncached cells are reported as uncached_cells.
    """
    formulas = openpyxl.load_workbook(generated, data_only=False)
    cached = openpyxl.load_workbook(generated, data_only=True)
    fresh = openpyxl.load_workbook(recalculated, data_only=True)
    total = 0
    uncached = 0
    mismatches = []
    for sheet in formulas.sheetnames:
        if sheet not in fresh.sheetnames:
            mismatches.append((sheet, "*", "sheet missing after recalculation", None, None))
            continue
        for row in formulas[sheet].iter_rows():
            for cell in row:
                if not (isinstance(cell.value, str) and cell.value.startswith("=")):
                    continue
                a = cached[sheet][cell.coordinate].value
                if a is None:
                    uncached += 1
                    continue  # no cached value stored: nothing to compare against
                total += 1
                b = fresh[sheet][cell.coordinate].value
                if not _same(a, b):
                    mismatches.append((sheet, cell.coordinate, cell.value[:80], a, b))
    return {"formula_cells": total, "uncached_cells": uncached, "mismatches": mismatches}
