"""
SPEC-017 bug (reporting exporter.py): export_reports hard-coded cbom_bounds_by_sheet
["7.0 CBOM VL-1"]. An RFQ whose volumes do not include "1" (prototype-only, or numbered
from 2) raised KeyError at export. The reference sheet must come from the volumes that exist.

The helper is lifted out of the source with ast (exporter.py imports openpyxl and sibling
modules that are not importable here).
"""
import ast
import os

EXPORTER = os.path.join(os.path.dirname(__file__), "..", "mcp-tools", "reporting", "superset", "exporter.py")


def _reference_sheet():
    with open(EXPORTER, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_reference_cbom_sheet")
    namespace = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), EXPORTER, "exec"), namespace)
    return namespace["_reference_cbom_sheet"]


def test_prefers_vl1_when_present():
    f = _reference_sheet()
    assert f({"7.0 CBOM Proto": (1, 2), "7.0 CBOM VL-1": (3, 9), "7.0 CBOM VL-2": (10, 12)}) == "7.0 CBOM VL-1"


def test_proto_only_rfq_does_not_crash():
    f = _reference_sheet()
    assert f({"7.0 CBOM Proto": (1, 4)}) == "7.0 CBOM Proto"


def test_numbered_from_two_uses_lowest_numbered_volume():
    f = _reference_sheet()
    assert f({"7.0 CBOM VL-3": (1, 4), "7.0 CBOM VL-2": (5, 8)}) == "7.0 CBOM VL-2"
