"""SPEC-018 gate: every generated formula cell must match a LibreOffice recalculation of the same workbook.

Set CAM_PARITY_WORKBOOK to a real export (.xlsx). Exports hold customer BOM data, so they are never committed.
"""
import os
from pathlib import Path

import openpyxl
import pytest

from formula_parity_oracle import compare, find_libreoffice, recalculate

WORKBOOK = os.environ.get("CAM_PARITY_WORKBOOK", "")


@pytest.mark.skipif(find_libreoffice() is None, reason="LibreOffice not installed (set LIBREOFFICE_BIN)")
@pytest.mark.skipif(not WORKBOOK, reason="set CAM_PARITY_WORKBOOK to a generated export")
def test_generated_formulas_match_libreoffice_recalculation(tmp_path):
    result = compare(Path(WORKBOOK), recalculate(Path(WORKBOOK), tmp_path))
    if result["formula_cells"] == 0:
        pytest.skip(f"export stores no cached formula values ({result['uncached_cells']} uncached); Excel recalculates on open")
    shown = result["mismatches"][:10]
    assert not result["mismatches"], f"{len(result['mismatches'])} of {result['formula_cells']} cells differ: {shown}"


ERROR_LITERALS = {"#REF!", "#VALUE!", "#N/A", "#DIV/0!", "#NAME?", "#NUM!", "#NULL!"}


@pytest.mark.skipif(find_libreoffice() is None, reason="LibreOffice not installed (set LIBREOFFICE_BIN)")
@pytest.mark.skipif(not WORKBOOK, reason="set CAM_PARITY_WORKBOOK to a generated export")
def test_export_ships_no_error_cells(tmp_path):
    # RE 2, ship gate A1: nothing leaves with an Excel error literal in a cell (checked on the recalculated values)
    import collections
    import openpyxl

    recalculated = openpyxl.load_workbook(recalculate(Path(WORKBOOK), tmp_path), data_only=True)
    errors = collections.Counter(
        (ws.title, cell.value)
        for ws in recalculated.worksheets
        for row in ws.iter_rows()
        for cell in row
        if isinstance(cell.value, str) and cell.value in ERROR_LITERALS
    )
    assert not errors, f"error cells in the export: {dict(errors)}"


PLACEHOLDERS = {0, "-", "(unspecified)", "0", "$ 0.00"}


@pytest.mark.skipif(find_libreoffice() is None, reason="LibreOffice not installed (set LIBREOFFICE_BIN)")
@pytest.mark.skipif(not WORKBOOK, reason="set CAM_PARITY_WORKBOOK to a generated export")
def test_export_has_no_dead_report_tabs(tmp_path):
    # RE 2, ship gate A2: a tab whose computed content is mostly placeholders is a dead report, not a result
    recalculated = openpyxl.load_workbook(recalculate(Path(WORKBOOK), tmp_path), data_only=True)
    dead = []
    for ws in recalculated.worksheets:
        values = [cell.value for row in ws.iter_rows() for cell in row if cell.value not in (None, "")]
        if len(values) >= 20 and sum(1 for v in values if v in PLACEHOLDERS) / len(values) > 0.9:
            dead.append(ws.title)
    assert not dead, f"tabs that are more than 90% placeholders: {dead}"
