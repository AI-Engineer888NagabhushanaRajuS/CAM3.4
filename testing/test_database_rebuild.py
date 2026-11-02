"""
SPEC-017 bug (reporting database.py _rebuild_table_with_new_ddl): the rebuild renamed the
table aside, then recreated and copied it, as separate autocommit statements. A failure in
between left the rows only in <table>__pre_proto_migration, and the next connect() no longer
sees the old type, so it never recovered them. The rebuild must be all-or-nothing.

Run against real DuckDB. The function is lifted with ast (database.py imports sibling config).
"""
import ast
import os

import duckdb
import pytest

DB = os.path.join(os.path.dirname(__file__), "..", "mcp-tools", "reporting", "superset", "database.py")


def _rebuild():
    with open(DB, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_rebuild_table_with_new_ddl")
    namespace = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), DB, "exec"), namespace)
    return namespace["_rebuild_table_with_new_ddl"]


def test_failed_rebuild_leaves_the_original_table_intact():
    con = duckdb.connect()
    con.execute("CREATE TABLE t (rfq_id VARCHAR, volume_no SMALLINT)")
    con.execute("INSERT INTO t VALUES ('CE-1', 1), ('CE-1', 2)")
    with pytest.raises(Exception):
        _rebuild()(con, "t", "CREATE TABLE t (this is not valid sql")
    assert con.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2, "rows must not be stranded"


def test_successful_rebuild_moves_rows_and_retypes():
    con = duckdb.connect()
    con.execute("CREATE TABLE t (rfq_id VARCHAR, volume_no SMALLINT)")
    con.execute("INSERT INTO t VALUES ('CE-1', 1)")
    _rebuild()(con, "t", "CREATE TABLE t (rfq_id VARCHAR, volume_no VARCHAR)")
    assert con.execute("SELECT volume_no FROM t").fetchall() == [("1",)]
    assert con.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 't__pre_proto_migration'").fetchone()[0] == 0
