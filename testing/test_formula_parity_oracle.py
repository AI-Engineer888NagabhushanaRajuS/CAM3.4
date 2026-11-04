"""SPEC-018 gate: every generated formula cell must match a LibreOffice recalculation of the same workbook.

Set CAM_PARITY_WORKBOOK to a real export (.xlsx). Exports hold customer BOM data, so they are never committed.
"""
import os
from pathlib import Path

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
