# Bifrost (MCP Gateway for RFQ_Flow)

## Table of Contents

- [Purpose](#purpose)
- [Scope: RFQ_Flow only](#scope-rfq_flow-only)
- [Integration contract](#integration-contract)
- [Registered clients](#registered-clients)
- [Configuration](#configuration)
- [Resolved: ~30s tool-execution timeout](#resolved-30s-tool-execution-timeout-2026-09-28)
- [Related documents](#related-documents)

## Purpose

Bifrost (`https://github.com/maximhq/bifrost`) is a unified LLM+MCP gateway,
replacing [MCP Jungle](./mcp-jungle.md) as the tool-execution gateway for
`RFQ_Flow` (the platform's currently fully-operational routing profile).
Runs locally as a Docker container (`bifrost-custom:v2.2.3`, built from
`C:\bifrost-image\Dockerfile` — just the official `maximhq/bifrost:v2.2.3`
image plus `uv` for its Postgres stdio clients), state at
`C:\bifrost-data`. Management API on port 8010 (basic-auth protected, admin
credentials in `C:\bifrost-data\config.json`); tool execution on the same
port, unauthenticated (confirmed empirically — see below).

## Scope: RFQ_Flow only

Only `RFQ_Flow`'s tools are registered in Bifrost and migrated to it.
`Standard_BOM_Flow` still uses MCP Jungle — see that document's own status
banner for why.

## Integration contract

Implemented in `fastmcp-router/tool_calling.py` (and 3 mirrored copies:
`mcp-tools/intake/tool_calling.py`,
`mcp-tools/distributor-pricing/tool_calling.py`,
`mcp-tools/gerber-integration/tool_calling.py`). Two functions:

| Function | JSON-RPC method | Purpose |
|---|---|---|
| `list_tools(client_name)` | `tools/list` | Debug helper, lists one client's tools |
| `call_tool(tool_name, arguments)` | `tools/call` | Invokes a named tool |

**No session/handshake** — confirmed empirically that a bare `tools/call`
POST with no prior `initialize` request reaches the real tool and returns
its real response. This is the biggest contract difference from MCP
Jungle, which requires a session handshake first.

**Per-client endpoint, not one shared URL**: `POST
{BIFROST_URL}/mcp/{endpoint_slug}` — `endpoint_slug` differs per client and
is **not derivable** from the client name (e.g. `Production_Logic_DB`'s
slug is `production-postgres-db`, not a mechanical transform). Client →
slug is an explicit lookup table, `BIFROST_ENDPOINT_SLUGS` in each
`config.py`.

**Tool naming**: `<client_name>-<tool_name>` (single hyphen, unlike MCP
Jungle's `<server>__<tool>` double-underscore). This is stored directly in
`quote_routing_profiles.routing_sequence` (`RFQ_Flow` row) and
`system_skills_registry.mcp_tool_name` for the 8 matching rows — the DB
values themselves were rewritten to this format, not translated at call
time, so a direct DB read shows exactly what Bifrost expects.

## Registered clients

(As registered by the user directly via Bifrost's own admin API/UI — this
repo does not register them.)

| client name | endpoint_slug | tools | backing server |
|---|---|---|---|
| `intake` | `intake` | `scan_local_file`, `import_bom` | `mcp-tools/intake/mcp_server.py`, port 8002 |
| `gerber_integration` | `gerber-integration` | `extract_features` | `mcp-tools/gerber-integration/mcp_server.py`, port 8007 |
| `distributor` | `distributor` | `enrich_bom`, `detect_alternates`, `apply_alternatives`, `export_enriched_bom`, `export_quote_summary` | `mcp-tools/distributor-pricing/mcp_server.py`, port 8003 |
| `Production_Logic_DB` | `production-postgres-db` | `execute_sql` (+unused others) | `postgres-mcp` (stdio), `logic_db_2` |
| `Production_FileMetedata_DB` (typo preserved from registration) | `production-filemetedata-db` | `execute_sql` (+unused others) | `postgres-mcp` (stdio), `file_metadata_db_2` |

The last two replace MCP Jungle's `postgres_logic_2`/`postgres_metadata_2`
tools that `fastapi_router.py`'s own `/pipeline/routing-sequence` endpoint
uses internally (not part of any routing_sequence itself, but the same
kind of gateway call).

## Configuration

`BIFROST_URL` (default `http://localhost:8010`) and `BIFROST_ENDPOINT_SLUGS`
in `fastmcp-router/config.py` and the 3 mirrored tool-server `config.py`
files.

## Resolved: ~30s tool-execution timeout (2026-09-28)

During initial migration testing, Bifrost's own internal MCP-proxy-to-
backend timeout (~30 seconds — independent of and shorter than the Python
client's own `requests.post(..., timeout=300)`) caused real, in-progress
tool calls to fail: `intake-scan_local_file` (a ClamAV-backed scan) and
`distributor-enrich_bom` (105 sequential real DigiKey/Mouser/Element14
pricing lookups) both timed out at ~30s while the underlying work was
genuinely still completing correctly server-side (confirmed via each tool
server's own log).

**Fixed directly in Bifrost's own configuration** (by the platform
operator, not a code change in this repo) — the exact mechanism wasn't
identified from this repo's side: no diff was visible afterward in the
container's env vars, `C:\bifrost-data\config.json`, or any field returned
by a client's own `/api/mcp/clients` entry, so the change most likely was
made via Bifrost's own web UI at `http://localhost:8010` (not reachable
via the REST API used for this repo's own read-only verification). Full
`RFQ_Flow` run (`RFQ-000053`) confirmed completing end-to-end through
Bifrost afterward, including `enrich_bom` and the `apply_alternatives`
HITL gate.

## Related documents

- [MCP Jungle](./mcp-jungle.md) — the gateway Bifrost is replacing (still
  live for `Standard_BOM_Flow`)
- [fastmcp-tools.md](./fastmcp-tools.md) — the FastMCP tool servers Bifrost
  proxies to
