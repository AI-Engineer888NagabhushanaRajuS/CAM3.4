"""Scrub-intake's SQL sink for CAM 3.4.

3.3 tool_calling.py sent these statements through the MCP Jungle gateway, which 3.4 does not use
(SPEC-015). This runs the SQL directly against file_metadata_db and returns the same
JSON-RPC-shaped dict the scrub callers parse (result.content[0].text = repr of the rows).
create_session() is kept so the server's call sites do not change; there is no handshake to do.
"""
import os

import psycopg2
from psycopg2.extras import RealDictCursor


def create_session():
    return None


def call_tool(tool_name, arguments, session=None):
    # session is accepted for call-site compatibility with the 3.3 callers; SQL needs no session.
    sql = arguments["sql"]
    with psycopg2.connect(os.environ["FILE_METADATA_DB_URL"]) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql)
            rows = [dict(r) for r in cur.fetchall()] if cur.description else []
    return {"result": {"content": [{"type": "text", "text": repr(rows)}]}}
