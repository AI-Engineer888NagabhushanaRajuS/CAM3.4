"""Intake's SQL sink for CAM 3.4.

3.3 tool_calling.py sent these statements through the Bifrost gateway, which 3.4 does not use
(SPEC-015). This runs the SQL directly against file_metadata_db and returns the same
JSON-RPC-shaped dict the intake callers parse (result.content[0].text = repr of the rows).
Only the {"sql": ...} argument shape is supported, which is all intake sends.
"""
import os

import psycopg2
from psycopg2.extras import RealDictCursor


def call_tool(tool_name, arguments):
    sql = arguments["sql"]
    with psycopg2.connect(os.environ["FILE_METADATA_DB_URL"]) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql)
            rows = [dict(r) for r in cur.fetchall()] if cur.description else []
    return {"result": {"content": [{"type": "text", "text": repr(rows)}]}}
