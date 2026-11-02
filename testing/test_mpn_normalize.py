"""
SPEC-017 bug (reporting/queries.py _normalize_mpn_sql): a purely numeric MPN longer than
BIGINT (19+ digits) normalized to NULL, so the QuoteWin/Scrub BOM join dropped the row
silently. The leading-zero rule must not depend on the value fitting a 64-bit integer.

The SQL-building function is lifted out of the source with ast (queries.py imports sibling
modules that are not importable here) and run in DuckDB.
"""
import ast
import os

import duckdb
import pytest

QUERIES = os.path.join(os.path.dirname(__file__), "..", "mcp-tools", "reporting", "superset", "queries.py")


def _normalize_mpn_sql_fn():
    with open(QUERIES, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_normalize_mpn_sql")
    namespace = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), QUERIES, "exec"), namespace)
    return namespace["_normalize_mpn_sql"]


@pytest.mark.parametrize("raw, expected", [
    ("000013", "13"),                       # leading zeros dropped (the documented rule)
    ("13", "13"),
    ("000", "0"),
    ("A013", "A013"),                       # alphanumeric: compared as-is, uppercased
    ("  000013  ", "13"),
    ("12345678901234567890123", "12345678901234567890123"),  # > BIGINT: must not become NULL
    ("0012345678901234567890123", "12345678901234567890123"),
])
def test_mpn_key_normalizes_without_loss(raw, expected):
    con = duckdb.connect()
    sql = _normalize_mpn_sql_fn()("v")
    got = con.execute(f"SELECT {sql} FROM (SELECT ? AS v)", [raw]).fetchone()[0]
    assert got == expected, f"{raw!r} -> {got!r}"
