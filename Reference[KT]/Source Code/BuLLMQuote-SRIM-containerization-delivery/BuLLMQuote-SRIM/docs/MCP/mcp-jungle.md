# MCP Jungle

> **Status (as of the Bifrost migration, 2026-09-28): partially retired.**
> `RFQ_Flow`'s tool calls (`intake`, `gerber_integration`, `distributor`, plus
> `fastapi_router.py`'s own internal Postgres lookups) now go through
> **Bifrost** instead — see [bifrost.md](./bifrost.md) for that integration.
> MCP Jungle itself is still running, untouched, and still the live gateway
> for **`Standard_BOM_Flow`** (`scrub_mcp_server`/`reporting_module`'s tools,
> `centum_intake__*`/`centum_reporting__*` naming) — that profile hasn't been
> migrated because 3 of its 8 tools (`scrub_mcp_server`) aren't even copied
> into this consolidated repo yet (separate, pre-existing gap). Do not delete
> this document or MCP Jungle's containers while `Standard_BOM_Flow` still
> depends on it.

## Table of Contents

- [Purpose](#purpose)
- [What can and cannot be documented here](#what-can-and-cannot-be-documented-here)
- [Integration contract](#integration-contract)
- [Connection lifecycle](#connection-lifecycle)
- [Tool invocation](#tool-invocation)
- [Why MCP Jungle exists](#why-mcp-jungle-exists)
- [Configuration](#configuration)
- [Error propagation, as observed from the client side](#error-propagation-as-observed-from-the-client-side)
- [Health / monitoring](#health--monitoring)
- [Related documents](#related-documents)

## Purpose

MCP Jungle is a unified gateway that sits between this platform's own HTTP
router (`fastapi_router.py`) and every individual FastMCP tool server
(`scrub_mcp_server.py`, `reporting_module/mcp_server.py`, and the two
dormant tools `intake` and `distributor_pricing`). Callers speak one
consistent JSON-RPC 2.0 / MCP protocol to a single endpoint, instead of each
caller needing to know the network address of every individual tool server.

## What can and cannot be documented here

MCP Jungle is a **pure external dependency** from this codebase's
perspective — there is no MCP Jungle source code, configuration file, or
registry file anywhere in this repository. Everything below is derived from
how this codebase *calls* it (`tool_calling.py`, `fastapi_router.py`), not
from MCP Jungle's own implementation, which is out of scope for this
documentation set. Sections that would normally cover a subsystem's
internals — gateway architecture, tool registration mechanics, registry
storage, health-check implementation — are written here strictly as **the
integration contract observed from the client side**. If MCP Jungle's own
admin documentation or source becomes available, this document should be
expanded from that, not from further reverse-engineering of this repo.

Known, confirmed facts:
- Reached over plain HTTP at a single URL, default `http://localhost:8080/mcp`
  (see [Configuration](#configuration)).
- Speaks JSON-RPC 2.0 over that one endpoint (not one endpoint per method).
- Requires a session handshake before tool calls are accepted (see
  [Connection lifecycle](#connection-lifecycle)).
- At least one backing server is confirmed registered behind it: a
  `postgres-mcp` server (referenced by `tool_calling.py`'s `list_tools()`
  as a `server_id`).

## Integration contract

Implemented entirely in `centum intake\tool_calling.py` (see
[Backend/file-reference.md](../Backend/file-reference.md#tool_callingpy)
for the file-level writeup) — 3 functions, each a single JSON-RPC call:

| Function | JSON-RPC method | Purpose |
|---|---|---|
| `create_session()` | `initialize` + `notifications/initialized` | Handshake — see below |
| `list_tools(session)` | `tools/list` | Lists tools for a given `server_id` (only `postgres-mcp` used in current code) |
| `call_tool(session, tool_name, arguments)` | `tools/call` | Invokes a named tool with a JSON `arguments` object |

## Connection lifecycle

1. `create_session()` opens a `requests.Session()`, sets
   `Content-Type: application/json` and `MCP-Protocol-Version: 2025-11-25`
   headers.
2. Sends an `initialize` JSON-RPC request declaring client capabilities
   (`roots.listChanged: true`, empty `sampling`) and client identity
   (`python-tool-client`, version `1.0.0`).
3. Reads an `Mcp-Session-Id` response header, if present, and attaches it to
   all subsequent requests on that session.
4. Sends a `notifications/initialized` message (no response expected) to
   complete the handshake. The code comment is explicit about why this step
   exists: *"Without this, the gateway will not attach external server
   tools to this session."*
5. Returns the now-initialized `requests.Session` for reuse across multiple
   `call_tool()`/`list_tools()` calls.

`fastapi_router.py` calls `create_session()` fresh at least twice: once
during a "wake up Postgres MCP" step and once per `/tool/execute` request
(see [APIs/endpoints.md](../APIs/endpoints.md)) — sessions are not
long-lived/reused across HTTP requests in the current implementation.

## Tool invocation

`call_tool(session, tool_name, arguments)` sends:

```json
{
  "jsonrpc": "2.0",
  "id": <monotonic int>,
  "method": "tools/call",
  "params": {
    "name": "<tool_name>",
    "arguments": { "...": "..." }
  }
}
```

with a **300-second read timeout**. The code comment explains why 300s
specifically: a 30s timeout was observed to time out mid-call for LLM-backed
tools (example given: `standardize_quote_win` on a large file can take over
a minute), silently losing the tool's result. 300s matches the timeout
already used by the Dify workflow's own HTTP nodes for the equivalent call
(see [DMR/dynamic-master-router.md](../DMR/dynamic-master-router.md), step
4a — Dify's own `HTTP Request 2` node uses `read: 600` seconds, actually
double this client-side value; the two are not currently kept in sync by
any shared config, which is worth knowing if either needs tuning later).

`tool_name` values are the fully-qualified MCP tool names stored in
`system_skills_registry.mcp_tool_name` (e.g.
`centum_reporting__cbom`, `centum_intake__standardize_scrub_bom`) — see
[Database/logic-database.md](../Database/logic-database.md) and
[MCP/fastmcp-tools.md](../MCP/fastmcp-tools.md) for the full list MCP
Jungle is expected to be able to route to.

## Why MCP Jungle exists

It decouples the router/orchestration layer from the physical location and
count of tool servers. `fastapi_router.py` and the Dify workflow only ever
need to know one URL. Adding a new FastMCP tool server (e.g. activating the
currently-dormant `intake` or `distributor_pricing` servers) is expected to
require registering it with MCP Jungle so its tools become callable via the
same `tools/call` interface — it should not require any change to
`tool_calling.py`, `fastapi_router.py`, or the Dify workflow, only a new
row in `system_skills_registry` and an entry in the relevant
`routing_sequence`. This is the concrete mechanism behind this platform's
stated "modular, swap-the-tool-set" design principle (see
[Architecture/design-principles.md](../Architecture/design-principles.md)).

## Configuration

Single environment variable, read in `config.py` (centum intake root):

```python
MCP_JUNGLE_URL = os.environ.get("MCP_JUNGLE_URL", "http://localhost:8080/mcp")
```

Note: `fastapi_router.py` also has its own **hardcoded** copy of this same
default (`MCP_JUNGLE_URL = "http://localhost:8080/mcp"` at its own module
level, not imported from `config.py`) — the two currently agree, but they
are two separate literals, not one shared source of truth. Worth
consolidating if this URL ever needs to change in one deployment but not
another.

## Error propagation, as observed from the client side

`tool_calling.py` calls `response.raise_for_status()` only inside
`create_session()`'s `initialize` step — a failed handshake raises an
`requests.HTTPError` that will surface as an unhandled exception up through
`fastapi_router.py` unless caught there. `call_tool()` and `list_tools()`
do NOT call `raise_for_status()` — they return `response.json()`
unconditionally, meaning a JSON-RPC-level error response (as opposed to an
HTTP-level error) is returned as normal data and must be checked by the
caller. Whether `fastapi_router.py` actually inspects the returned payload
for a JSON-RPC `error` field is documented per-endpoint in
[Backend/file-reference.md](../Backend/file-reference.md#fastapi_routerpy).

## Health / monitoring

`manage_backend.py` (see
[Deployment/deployment.md](../Deployment/deployment.md)) lists
`mcp_jungle_gateway` as one of its 3 monitored "External dependencies"
(alongside Postgres and Ollama), confirmed healthy throughout this
documentation effort's own session. The health-check mechanism itself
(what URL/method `manage_backend.py` polls) is documented in
[Backend/file-reference.md](../Backend/file-reference.md#manage_backendpy).

## Related documents

- [MCP/fastmcp-tools.md](../MCP/fastmcp-tools.md) — every tool name MCP Jungle is expected to route.
- [DMR/dynamic-master-router.md](../DMR/dynamic-master-router.md) — the caller of `/tool/execute`, which itself calls into this gateway.
- [Database/logic-database.md](../Database/logic-database.md) — where `mcp_tool_name` values are registered.
- [Backend/file-reference.md](../Backend/file-reference.md) — `tool_calling.py` and `fastapi_router.py` full detail.
