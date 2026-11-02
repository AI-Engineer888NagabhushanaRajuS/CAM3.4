"""
SPEC-012: hostile rfq_id values must be rejected before any SQL is built.

The MCP servers import sibling packages from their deployed layout, so they
cannot be imported here. Instead, the `_validate_id` function is lifted out of
each source file with `ast` and executed alone.
"""
import ast
import os
import re

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
HOSTILE_IDS = [
    "CE-1'; DROP TABLE rfq_file_telemetry--",
    "CE-1 OR 1=1",
    "CE-1\x00null",
    "../etc/passwd",
    "CE-1'",
]


def _extract_validate_id(relpath):
    with open(os.path.join(ROOT, relpath), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_validate_id")
    namespace = {"re": re}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), relpath, "exec"), namespace)
    return namespace["_validate_id"]


@pytest.mark.parametrize("relpath", [
    "mcp-tools/intake/mcp_server.py",
    "mcp-tools/gerber-integration/mcp_server.py",
    "mcp-tools/scrub-intake/scrub_mcp_server.py",
])
def test_mcp_validate_id_rejects_hostile_rfq_id(relpath):
    validate_id = _extract_validate_id(relpath)
    for evil in HOSTILE_IDS:
        with pytest.raises(ValueError):
            validate_id(evil)
    assert validate_id("CE-001") == "CE-001"
