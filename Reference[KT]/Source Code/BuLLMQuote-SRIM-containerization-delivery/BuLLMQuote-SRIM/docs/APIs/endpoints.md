# API Reference

## Table of Contents

- [fastapi_router.py (port 5000)](#fastapi_routerpy-port-5000)
- [hitl_router.py (port 5002)](#hitl_routerpy-port-5002)
- [upload_server.py (port 3000)](#upload_serverpy-port-3000)
- [duck_db_api.py / python_bridge (port 3010)](#duck_db_apipy--python_bridge-port-3010)
- [bom_qa_lookup_server.py (port 8006)](#bom_qa_lookup_serverpy-port-8006)
- [accomplish-ui daemon (port 9234)](#accomplish-ui-daemon-port-9234)
- [A note on authentication](#a-note-on-authentication)
- [Related documents](#related-documents)

All request/response bodies below are JSON unless noted otherwise. None of
these endpoints were observed to require an auth header/token — see
[A note on authentication](#a-note-on-authentication).

## fastapi_router.py (port 5000)

### `GET /pipeline/routing-sequence/{rfq_id}/{profile_name}`

Called by the Dify DMR workflow's first HTTP node (see
[DMR/dynamic-master-router.md](../DMR/dynamic-master-router.md)).

**Real mechanism, confirmed by reading the handler in full** (correcting a
simplification elsewhere in this doc set — this endpoint does **not** call
`db.py` directly): it opens an MCP Jungle session, first fires an
unawaited `resources/list` request as a "wake up the Postgres MCP server"
step, then issues two SEPARATE `tools/call` requests to two generic
SQL-execution MCP tools:
- `postgres_logic__execute_sql` — `SELECT routing_sequence FROM
  quote_routing_profiles WHERE profile_name = '{profile_name}';`
- `postgres_metadata__execute_sql` — `SELECT rfq_process_stage FROM
  rfq_process_tracking WHERE rfq_id = '{rfq_id}';`

**Security note, confirmed by reading the code directly**: both SQL strings
are built with plain Python f-string interpolation of the path parameters,
not parameterized queries — `profile_name` and `rfq_id` come straight from
the URL into the SQL text sent to the `postgres_*__execute_sql` MCP tools.
This is a SQL injection surface if either MCP tool executes the string
as-is. Flagging this explicitly as a real, observed risk rather than
omitting it — not confirmed whether the backing `postgres-mcp` server
itself sanitizes/parameterizes on its end, since that server's
implementation is outside this codebase (see
[MCP/mcp-jungle.md](../MCP/mcp-jungle.md)'s scope note).

**Response**:
```json
{ "routing_sequence": ["...", "..."], "skill_index": 4 }
```
or `{"error": "Profile '...' not found"}` / `{"error": "RFQ '...' not found"}` /
`{"error": "<exception message>"}` on failure — this endpoint always returns
HTTP 200 with an `error` key rather than a non-2xx status code, confirmed
from the handler's own `try/except` wrapping the whole body.

### `POST /tool/execute`

Called by the Dify DMR workflow's per-iteration HTTP node.

**Request**:
```json
{ "tool_name": "centum_reporting__cbom", "arguments": { "rfq_id": "RFQ-000049" }, "rfq_id": null }
```
(`rfq_id` at the root is optional — if absent, the handler falls back to
`arguments.rfq_id`, defaulting to the literal string `"UNKNOWN_RFQ"` if
neither is present.)

**Behavior, in order**: (1) a routing-profile gate re-checks
`db.py`'s `get_routing_sequence("Standard_BOM_Flow")` (this call, unlike
the sibling GET endpoint above, DOES go through `db.py` directly, not MCP)
on every single call — deliberately uncached, so a live Skills Settings
toggle takes effect on the very next call, and deliberately fails OPEN (logs
and continues) rather than closed if this lookup itself errors, so a
routing-config bug can't silently stall every RFQ; (2) if the tool isn't in
the currently-active sequence, it's skipped without ever opening an MCP
session; (3) otherwise, resolves the versioned key, opens an MCP session,
and calls the named tool via `tool_calling.call_tool()`; (4) advances
`rfq_process_stage` only if the tool's response has a falsy `hitl`.

## hitl_router.py (port 5002)

All 3 endpoints back the `resolve_final_selection` HITL gate (see
[DMR/dynamic-master-router.md](../DMR/dynamic-master-router.md#failure-handling--hitl-halt)),
reading/writing `logic_db.final_selection_conflicts` (a table not otherwise
documented elsewhere in this doc set — confirmed to exist by this file's
own queries; add it to
[Database/logic-database.md](../Database/logic-database.md) if/when its
full schema is introspected).

### `GET /api/rfq/{rfq_id}/final-selection/pending?cursor=&limit=100`

Keyset/cursor-paginated list of unresolved conflicts for an RFQ —
deliberately not OFFSET-based, since an RFQ can have thousands of
conflicting rows and OFFSET pagination degrades at that scale. Pass the
last item's `conflict_id` as `cursor` for the next page. `limit` clamped to
`[1, 500]`.

### `GET /api/rfq/{rfq_id}/final-selection/summary`

Lightweight `{total, resolved}` counts only, no row payload — safe to poll
frequently for a progress UI.

### `POST /api/rfq/{rfq_id}/final-selection`

Batch/incremental resolution submission — a reviewer can submit any subset
of pending conflicts repeatedly, not all-or-nothing. Writes each resolved
row's chosen source values into `cbom.duckdb`'s `final_*` columns; only
once EVERY conflict for the `rfq_id` is resolved does it advance
`rfq_process_stage` past the `resolve_final_selection` skill, which is what
lets a later `GET /api/dify/start/{rfq_id}` resume the Dify run past the
HITL gate. An empty `resolutions` list is accepted as a no-op "confirm"
only when nothing is genuinely pending; rejected if real conflicts remain.

## upload_server.py (port 3000)

### `GET /api/dify/start/{rfq_id}`

**The DMR resumption endpoint** (see
[DMR/dynamic-master-router.md](../DMR/dynamic-master-router.md#recovery--resumption)).
Manually/externally triggers a fresh Dify workflow run for `rfq_id`.
Returns `{success, rfq_id, dify_status, dify_response}`.

### `POST /api/rfq/upload` (multipart: `bom_file`, `rfq_id`)

The initial BOM upload that starts a new RFQ intake. Calls
`db.ensure_version_schema()`, then inserts a `rfq_process_tracking` row. A
re-upload to an `rfq_id` that already has an active version creates an
**isolated new version** rather than overwriting — the prior version's
tracking row and its separately-versioned-keyed DuckDB data are left
untouched (see
[Database/logic-database.md](../Database/logic-database.md#versioning-strategy)).
After persisting, calls `trigger_dify_workflow_internal(rfq_id)` once.

### `POST /api/rfq/upload/quotewin` (multipart: `quotewin_file`, `rfq_id`)

Follow-up upload completing the same intake session the BOM upload started
— NOT a new version by itself; always tags the file with whatever version
is currently active.

### `POST /api/rfq/upload/costing_sheet` (multipart: `costing_sheet_file`, `rfq_id`)

The optional third input. Its own docstring notes it **replaces an earlier
ERP upload endpoint** — ERP isn't exposed in the current product (its MCP
tool/schema/routing code all still exist for future use — see
`erp_to_database.py` in
[Backend/file-reference.md](../Backend/file-reference.md) and skill_index 9
in [Database/logic-database.md](../Database/logic-database.md)), and
Costing Sheet has taken its place as the optional third pipeline input.

## duck_db_api.py / python_bridge (port 3010)

### `GET /api/bom/preview/{rfq_id}?volume_no=&cursor_fg=&cursor_cpn=&cursor_id=&limit=200`

FG-wise (ordered by `fg`, `cpn`) paginated costed-BOM preview for one
`rfq_id` + `volume_no`, read from `cbom.duckdb`. 3-part cursor
(`fg`, `cpn`, `cbom_item_id`) since the sort key is `(fg, cpn)`, not the
item id alone. `limit` capped at 1000.

### `PUT /api/bom/batch-update/{rfq_id}`

Applies inline cell edits (full row snapshots keyed by `bom_item_id`) to
`cbom.duckdb`'s `final_*` columns, then recomputes derived columns
(`is_costed`/`scrap_percent`/`abc_classification`/etc.) via
`final_selection.recompute_derived_columns` — the same function
`hitl_router.py` uses for the same purpose, confirming both editing paths
stay consistent.

### `GET /api/bom/export/{rfq_id}`

Metadata (`filename`, `generated_at`) for the most recently generated
report — lets the frontend show a "Download `<filename>`" link once
`export_reports` has actually run, without guessing the filename/timestamp.
404s if none found.

### `GET /api/bom/export/{rfq_id}/download`

Streams the same workbook as an actual file download
(`Content-Disposition: attachment`, `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`).

### `GET /api/bom/export-cbom/{rfq_id}/download`

A CBOM-only variant for the "Finalize Price" UI stage, distinct from the
full 16-report bundle the other two endpoints serve for "Quote Readiness."
Strips every sheet but "CBOM" out of the already-generated combined
workbook in-memory — no re-query, no temp files.

## bom_qa_lookup_server.py (port 8006)

Plain `http.server`-based handler (no FastAPI/framework) — deliberately
kept as small and boring as possible (see
[Backend/file-reference.md](../Backend/file-reference.md#bom_qa_lookup_serverpy)
for the full rationale, including why it exists as a separate Python
process rather than being folded into the Node daemon: the daemon's native
`duckdb` bindings are blocked by this machine's Application Control
policy).

### `GET /`

Health check — `{"status": "ok"}`.

### `POST /ask` — `{"question": "..."}`

If the question matches one of a small fixed set of known shapes, returns
`{"matched": true, "answer": "..."}` and the caller (accomplish-ui's
daemon) short-circuits before ever invoking an LLM/MCP tool call. Otherwise
`{"matched": false}` and the daemon falls through to its normal agent flow.
`400` for an empty/missing `question` or invalid JSON body.

## accomplish-ui daemon (port 9234)

### `POST /api/internal/trigger-hitl`

Called by the Dify DMR workflow (see
[DMR/dynamic-master-router.md](../DMR/dynamic-master-router.md), step 4d)
with `{"rfqId": ..., "stage": "<tool_name>", "hitlType": "approval"}` — the
daemon's own implementation lives in the separate `accomplish-ui` repo, not
in `centum intake`, so is out of full-file-reference scope for this
document set (see
[Frontend/accomplish-ui.md](../Frontend/accomplish-ui.md)); documented
here only as an inbound integration point this platform's DMR depends on.

## A note on authentication

No API key, bearer token, session cookie, or other credential was observed
being required or checked by any endpoint documented above. This matches
[Architecture/overview.md](../Architecture/overview.md#security)'s finding
— these services appear designed to run on a trusted local/LAN network
(`127.0.0.1` and `192.168.1.27` bindings), not to be exposed publicly.
Treat this as a gap to close before any public exposure, not as a
documented, intentional trust boundary.

## Related documents

- [DMR/dynamic-master-router.md](../DMR/dynamic-master-router.md)
- [MCP/mcp-jungle.md](../MCP/mcp-jungle.md)
- [Database/logic-database.md](../Database/logic-database.md)
- [Backend/file-reference.md](../Backend/file-reference.md)
