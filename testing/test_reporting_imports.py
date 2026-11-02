"""
SPEC-017 bug: the reporting modules import `db` from a `fastmcp-router/` folder that does not
exist in this repo (db.py lives in `fastapi-router/`). Each import of currency, scrap_factor
or final_selection raised ModuleNotFoundError, so the reporting MCP server could not start.
Checked in a fresh interpreter so the suite's own sys.path does not hide the failure.
"""
import os
import subprocess
import sys

import pytest

REPORTING = os.path.join(os.path.dirname(__file__), "..", "mcp-tools", "reporting", "superset")


@pytest.mark.parametrize("module", ["currency", "scrap_factor", "final_selection"])
def test_reporting_module_imports_in_a_fresh_interpreter(module):
    code = f"import sys; sys.path.insert(0, {os.path.abspath(REPORTING)!r}); import {module}"
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-800:]
