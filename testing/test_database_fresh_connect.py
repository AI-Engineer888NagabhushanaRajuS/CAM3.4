"""
SPEC-017/015 bug (reporting database.py _column_type): connect() asks for a column's type before
the table is created. On a fresh cbom.duckdb, DESCRIBE raised a catalog error, so the first run of
the cbom step failed. A table that does not exist yet has no column type: return None.
"""
import os
import sys

import duckdb

SUP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mcp-tools", "reporting", "superset"))


def test_column_type_of_a_missing_table_is_none():
    sys.path.insert(0, SUP)
    try:
        import database as db
    finally:
        sys.path.remove(SUP)
    con = duckdb.connect()
    assert db._column_type(con, "no_such_table", "volume_no") is None
