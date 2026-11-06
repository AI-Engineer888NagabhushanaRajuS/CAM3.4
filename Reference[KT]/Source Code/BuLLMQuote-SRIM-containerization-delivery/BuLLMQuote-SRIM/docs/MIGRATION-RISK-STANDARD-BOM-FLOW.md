# Pre-migration checklist — moving Standard_BOM_Flow onto Bifrost

This is a checklist to run **before** `Standard_BOM_Flow` is migrated from
MCP Jungle onto Bifrost (the same migration `RFQ_Flow` already went through).
None of this needs doing today — `Standard_BOM_Flow` has no entry in
`dify-orchestration/` and still routes through MCP Jungle directly, so the
bug below has zero live impact right now. It only matters the day someone
starts this migration.

## The bug this migration would trigger immediately

`fastmcp-router/tool_calling.py`'s `_endpoint_url()` resolves a Bifrost
client by splitting the tool name on its first `-`:

```python
client, _, _ = tool_name.partition("-")
endpoint_slug = BIFROST_ENDPOINT_SLUGS.get(client)
if not endpoint_slug:
    raise ValueError(f"No Bifrost endpoint_slug registered for client '{client}' ...")
```

`Standard_BOM_Flow`'s tool names use MCP Jungle's `server__tool` convention
(double underscore — e.g. `centum_reporting__cbom`, `centum_intake__standardize_scrub_bom`).
None of these contain a hyphen, so `partition("-")` returns the entire string
as `client`, the lookup misses, and every single tool call in the flow would
raise `ValueError` on its first invocation. Reproduced directly against the
real function, twice, this session.

## Checklist, in order

1. **Rename or remap every `Standard_BOM_Flow` tool to Bifrost's `client-tool`
   convention** before registering them with Bifrost — either rename the
   underlying MCP server/tool definitions, or add a translation layer in
   `tool_calling.py` that maps Jungle-style names to a registered
   `BIFROST_ENDPOINT_SLUGS` client before calling `_endpoint_url()`.
2. **Register the new client(s)** (likely `centum_intake` and
   `centum_reporting`, mirroring how `intake`/`distributor`/`gerber_integration`
   are already registered) in `BIFROST_ENDPOINT_SLUGS` in `config.py`.
3. **Write a Dify app for `Standard_BOM_Flow`**, the same way
   `Dify_DMR_RFQ_Flow.yml` was cloned from `Dify_DMR` with one line changed
   (the routing-sequence profile name) — confirm the new app's tool-execution
   step targets `fastapi_router.py`'s `/tool/execute`, the same way
   `RFQ_Flow`'s does, not MCP Jungle's `:8080/mcp`.
4. **Verify the Jungle session-handshake dependency is actually gone** —
   confirm nothing else in the `Standard_BOM_Flow` tool chain assumes the
   `initialize` → `Mcp-Session-Id` → `notifications/initialized` handshake
   MCP Jungle requires and Bifrost does not implement. A repo-wide grep this
   session found zero code anywhere that performs this handshake, meaning
   there's currently no fallback if something upstream still expects it.
5. **Re-run this exact unit-level test** before calling the migration done:
   ```python
   from tool_calling import _endpoint_url  # or wherever it ends up living
   _endpoint_url("centum_reporting__cbom")  # should resolve, not raise
   ```
6. **Confirm MCP Jungle's registration for `centum_reporting`/`centum_intake`
   is formally retired** once the migration is live, so the two gateways
   don't both claim ownership of the same tools (this already happened once,
   mid-migration, for `RFQ_Flow` — `manage_backend.py`'s own comments note
   MCP Jungle "is no longer health-checked" for it, but the containers were
   left running "since Standard_BOM_Flow still points at it").

## Who should own this

Whoever runs the Bifrost migration next should treat steps 1–2 as the actual
blocking work; steps 3–6 are the same shape of work already done once for
`RFQ_Flow`, so that migration's own history is the best reference for how
long this realistically takes.
