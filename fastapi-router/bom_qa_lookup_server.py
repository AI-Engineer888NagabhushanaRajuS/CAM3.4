"""[BuLLMQuote-SRIM MIGRATION NOTE -- added on copy, updated after reporting_module migrated]
Not explicitly named in the original copy request but included as an "other
essential service" (same routing/lookup-layer role as hitl_router.py/
duck_db_api.py, not a BOM-processing MCP tool).
UPDATE: reporting_module has been migrated to mcp-tools/reporting/superset/;
the sys.path insert below now points there, so `import config as
reporting_config` correctly resolves to reporting_module's own config.py, not
this folder's same-named one (the silent name-collision bug described below
is now fixed) -- verified.
STILL BROKEN, though, at the point of actually USING it: reporting_module's
config.py resolves REPORTS_DB_PATH/CBOM_DB_PATH/INPUT_DB_PATH relative to
itself (`../database`), which from mcp-tools/reporting/superset/ does not
reach this repo's `database/` (not yet migrated -- see database/README.md
and mcp-tools/reporting/superset/config.py's own migration note). This file's
_open_readonly_connection() will still fail (now with a duckdb "file not
found"-style error, not AttributeError) until database/ is migrated into
this repo or REPORTING_DATABASE_DIR is set to point at
`centum intake\database\` directly.

Prior (now-fixed) finding, kept for context: before this update, `import
config as reporting_config` resolved SILENTLY to this folder's own config.py
(no ModuleNotFoundError, since a module literally named `config` DOES exist
here) instead of failing loudly -- it had none of the attributes this file
needs (REPORTS_DB_PATH, CBOM_DB_PATH, INPUT_DB_PATH; this folder's config.py
only defines MCP_JUNGLE_URL). The module imported fine; it would only have
raised AttributeError once a request actually triggered
_open_readonly_connection().
[END MIGRATION NOTE]

Scripted BOM/RFQ Q&A lookup for the accomplish-ui demo chatbot.

Plain HTTP JSON endpoint -- deliberately NOT an MCP server and NOT in any LLM/agent
tool-calling loop. accomplish-ui's daemon (apps/daemon/src/task-service.ts) calls
POST /ask directly, as a normal backend HTTP call, BEFORE a chat message is ever
handed to OpenCode/Ollama. If a question matches one of a small fixed set of known
shapes, this returns the answer and the daemon short-circuits -- no LLM, no MCP
protocol, no tool-calling involved at any point. Anything that doesn't match reports
matched=false and the daemon falls through to its normal agent flow unaffected.

This exists as a separate Python process (not folded into the Node daemon) purely
because Node's native duckdb bindings are blocked by this machine's Application
Control policy (confirmed against both the `duckdb` and `@duckdb/node-api` npm
packages -- both fail with ERR_DLOPEN_FAILED). Python's duckdb package already works
everywhere else in this pipeline. Uses only the standard library (http.server) --
no FastAPI/FastMCP/web framework -- to keep this as small and boring as possible.

Every connection is opened fully READ_ONLY (reports.duckdb as the main catalog, plus
cbom_db/input_db attached read-only) -- unlike reporting_module/database.py's own
connect(), which opens cbom.duckdb read-write for the pipeline's own generation/
enrichment steps. Using that function here would compete for the same write lock
whenever the pipeline is actively running; this module's connections never do.
"""

import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_CENTUM_INTAKE_DIR = os.path.dirname(os.path.abspath(__file__))
# [BuLLMQuote-SRIM] Updated for the new layout -- see migration note above.
_REPORTING_MODULE_DIR = os.path.join(_CENTUM_INTAKE_DIR, "..", "mcp-tools", "reporting", "superset")
for _dir in (_CENTUM_INTAKE_DIR, _REPORTING_MODULE_DIR):
    if _dir not in sys.path:
        sys.path.insert(0, _dir)

import duckdb
import config as reporting_config  # noqa: E402  (path setup above must run first)
from db import duckdb_file_lock  # noqa: E402  (path setup above must run first)


def _open_readonly_connection():
    """reports.duckdb as the read-only main catalog, cbom_db/input_db attached
    read-only alongside it -- matching reporting_module/database.py's own alias
    convention (cbom_db, input_db) so table references stay familiar, but with every
    database opened READ_ONLY (that module's own connect() opens cbom.duckdb
    read-write, which this tool must never do -- see module docstring).
    """
    con = duckdb.connect(reporting_config.REPORTS_DB_PATH, read_only=True)
    con.execute(f"ATTACH '{reporting_config.CBOM_DB_PATH}' AS cbom_db (READ_ONLY)")
    con.execute(f"ATTACH '{reporting_config.INPUT_DB_PATH}' AS input_db (READ_ONLY)")
    return con


def _run_query_raw(sql: str) -> dict:
    """Runs a pre-trusted SELECT (callers below build the SQL themselves from a
    regex-constrained ID token, never from raw user text) and returns the actual
    rows as Python values.
    """
    con = None
    try:
        # Even a read-only connection to reports.duckdb/cbom_db/input_db
        # competes for the same cross-process file-open exclusivity as the
        # pipeline's own read-write connections (reporting_mcp_server,
        # python_bridge, hitl_router) -- see db.duckdb_file_lock()'s docstring.
        with duckdb_file_lock():
            con = _open_readonly_connection()
            cursor = con.execute(sql)
            rows = cursor.fetchall()
            cols = [d[0] for d in cursor.description]
            return {"rows": [dict(zip(cols, row)) for row in rows]}
    except Exception as e:
        return {"error": str(e), "rows": []}
    finally:
        if con is not None:
            con.close()


# ─── Scripted question handlers ────────────────────────────────────────────────
# Exactly 2 known, literal templates -- the client will type these verbatim with
# only the RFQ ID / MPN swapped in, so this matches those two shapes directly
# instead of trying to be clever/flexible about phrasing.
#
#   "How many FGs does {rfq_id} contain?"
#   "What's the final conv price of MPN {mfg_part_num}?"

_FG_COUNT_RE = re.compile(r"how\s+many\s+fgs?\s+does\s+([\w-]+)\s+contain", re.IGNORECASE)
_MPN_PRICE_RE = re.compile(r"final\s+conv\s+price\s+of\s+mpn\s+([\w-]+)", re.IGNORECASE)

# The two handlers below interpolate their captured token straight into a SQL
# string (see _run_query_raw's docstring: "pre-trusted... from a regex-
# constrained ID token"). The capture groups above already restrict to
# [\w-]+, which cannot contain a quote, but re-validating here makes that
# safety property explicit and auditable at the point of use rather than
# implicit in a regex two functions away.
_SAFE_SQL_TOKEN_RE = re.compile(r"^[\w-]+$")


def _validate_sql_token(value: str) -> str:
    if not value or not _SAFE_SQL_TOKEN_RE.match(value):
        raise ValueError(f"Invalid identifier: {value!r}")
    return value


def _fg_count_for_rfq(rfq_id: str) -> str:
    rfq_id = _validate_sql_token(rfq_id)
    result = _run_query_raw(f"SELECT COUNT(DISTINCT fg) AS n FROM cbom_db.cbom WHERE rfq_id = '{rfq_id}'")
    n = result["rows"][0]["n"] if result.get("rows") else 0
    if not n:
        return f"I couldn't find any data for RFQ {rfq_id}."
    return f"RFQ {rfq_id} contains {n} FG{'s' if n != 1 else ''}."


def _mpn_price(mpn: str) -> str:
    mpn = _validate_sql_token(mpn)
    result = _run_query_raw(
        "SELECT DISTINCT final_price_conv AS v FROM cbom_db.cbom "
        f"WHERE mfg_part_number = '{mpn}' AND final_price_conv IS NOT NULL"
    )
    values = [r["v"] for r in result.get("rows", [])]
    if not values:
        return f"I couldn't find a final conv price on file for MPN {mpn}."
    if len(values) == 1:
        return f"The final conv price for MPN {mpn} is ${values[0]}."
    return f"MPN {mpn} has more than one final conv price on file: {', '.join(f'${v}' for v in values)}."


def try_hardcoded_answer(question: str) -> str | None:
    q = question.strip()

    m = _FG_COUNT_RE.search(q)
    if m:
        return _fg_count_for_rfq(m.group(1).rstrip("?.,!"))

    m = _MPN_PRICE_RE.search(q)
    if m:
        return _mpn_price(m.group(1).rstrip("?.,!"))

    return None


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            self._send_json(200, {"status": "ok"})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/ask":
            self._send_json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            question = (body.get("question") or "").strip()
        except (ValueError, json.JSONDecodeError):
            self._send_json(400, {"error": "invalid request body"})
            return

        if not question:
            self._send_json(400, {"error": "question is required"})
            return

        answer = try_hardcoded_answer(question)
        if answer is None:
            self._send_json(200, {"matched": False})
        else:
            self._send_json(200, {"matched": True, "answer": answer})

    def log_message(self, format, *args):
        print(f"[bom_qa_lookup_server] {self.address_string()} - {format % args}")


if __name__ == "__main__":
    # 0.0.0.0, not a single fixed LAN IP -- binding to one specific interface
    # address means the process refuses connections on every OTHER interface
    # (e.g. the NetBird virtual adapter) regardless of firewall rules.
    server = ThreadingHTTPServer(("0.0.0.0", 8106), Handler)
    print("[bom_qa_lookup_server] listening on http://0.0.0.0:8106")
    server.serve_forever()
