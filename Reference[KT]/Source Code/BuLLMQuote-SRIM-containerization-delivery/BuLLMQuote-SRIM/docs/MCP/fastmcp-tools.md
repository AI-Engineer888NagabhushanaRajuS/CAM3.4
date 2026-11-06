# FastMCP Tools

## Table of Contents

- [Overview](#overview)
- [Server inventory](#server-inventory)
- [Tool inventory](#tool-inventory)
  - [intake (dormant, port 8002)](#intake-dormant-port-8002)
  - [distributor_pricing (dormant, port 8003)](#distributor_pricing-dormant-port-8003)
  - [scrub_mcp_server (live, port 8004)](#scrub_mcp_server-live-port-8004)
  - [reporting_mcp_server (live, port 8005)](#reporting_mcp_server-live-port-8005)
- [Cross-tool relationships / execution order](#cross-tool-relationships--execution-order)
- [Registration process](#registration-process)
- [Example request/response](#example-requestresponse)
- [Related documents](#related-documents)

## Overview

Every FastMCP tool is an independent Python function decorated with
`@mcp.tool()` inside a small `mcp_server.py` file, built with the
[FastMCP](https://github.com/jlowin/fastmcp) framework. Each server is its
own OS process; tools are exposed to the rest of the platform exclusively
through MCP Jungle (see [MCP/mcp-jungle.md](../MCP/mcp-jungle.md)) — nothing
calls a tool server's port directly except MCP Jungle itself. This is the
concrete unit of "modularity" referenced throughout the design principles:
a tool is added or removed by registering/deregistering it with MCP Jungle
and updating `system_skills_registry`/`quote_routing_profiles`, not by
changing any router or orchestration code.

Full per-file source documentation for each server lives in its own
dedicated document (linked below); this document is the cross-cutting index
and relationship map.

## Server inventory

| Server | Port | Status | Tool count | File reference |
|---|---|---|---|---|
| `intake` | 8002 | **Dormant** — not registered in `manage_backend.py` | 2 active, 3 commented out | [MCP/intake-tool-reference.md](../MCP/intake-tool-reference.md) |
| `distributor_pricing` | 8003 | **Dormant** — not registered in `manage_backend.py` | 4 active | [MCP/distributor-pricing-tool-reference.md](../MCP/distributor-pricing-tool-reference.md) |
| `scrub_mcp_server` (in `centum intake\`) | 8004 | **Live** | 4 active | [Backend/file-reference.md](../Backend/file-reference.md#scrub_mcp_serverpy) |
| `reporting_mcp_server` (`reporting_module/mcp_server.py`) | 8005 | **Live** | 6 active | [Reporting/reporting-module.md](../Reporting/reporting-module.md#mcp_serverpy) |

"Dormant" means fully implemented, with its own `requirements.txt`, but not
part of the currently-running orchestration (`manage_backend.py`'s service
list) — they can be started standalone (`python mcp_server.py`) but nothing
currently wires them into MCP Jungle or the live routing sequences by
default.

## Tool inventory

All 16 tools take `rfq_id` as their primary/only required parameter (the 4
`scrub_mcp_server` tools also take an optional `version`, default `1`) — the
platform's tools are uniformly scoped to "do your job for this one RFQ,"
with all state persisted to Postgres/DuckDB rather than returned in-band for
the caller to thread through subsequent calls.

### intake (dormant, port 8002)

| Tool | Status | Description |
|---|---|---|
| `scan_local_file` | Active | Scans local paths for malware (ClamAV) and returns structural metrics. |
| `import_bom` | Active | Schema mapping, standardization, volume expansion, MM conversion, consolidation, save to DuckDB. |
| `enrich_bom` | Commented out | Superseded — see `distributor_pricing`'s own `enrich_bom` below. |
| `detect_alternates` | Commented out | Superseded — see `distributor_pricing`'s own `detect_alternates` below. |
| `apply_alternatives` | Commented out | Superseded — see `distributor_pricing`'s own `apply_alternatives` below. |

### distributor_pricing (dormant, port 8003)

| Tool | Description |
|---|---|
| `enrich_bom` | Enriches every row of `processed_bom_items` using DigiKey, Element14, Mouser. Pricing fetched exactly once per part. |
| `detect_alternates` | Detects alternate manufacturer parts (same CPN, different MPN) in enriched `processed_bom_items`; populates `update_alternatives` for review. Must run after `enrich_bom`. |
| `apply_alternatives` | Applies the user's `preferred_flag=TRUE` selections from `update_alternatives`, removing other alternates from `processed_bom_items`. |
| `export_enriched_bom` | Exports the final enriched BOM. |

### scrub_mcp_server (live, port 8004)

| Tool | Params | Description |
|---|---|---|
| `standardize_scrub_bom` | `rfq_id`, `version=1` | Standardizes a SCRUB BOM workbook; stores standardized rows (`scrub_bom_items`, `volume`, `batch`) in DuckDB. Schema mapping + standardization only — no volume expansion/consolidation/duplicate-CPN detection. |
| `standardize_quote_win` | `rfq_id`, `version=1` | Standardizes a QuoteWin (Awards Part Number Listing) report into DuckDB's `quote_win` table. |
| `standardize_costing_sheet` | `rfq_id`, `version=1` | Standardizes a Costing Sheet report into `costing_sheet`. Optional input — returns "skipped" if none provided. |
| `standardize_erp` | `rfq_id`, `version=1` | Standardizes an ERP purchase-history export into `erp`. No upload path in the current product — always returns "skipped" today. |

### reporting_mcp_server (live, port 8005)

| Tool | Params | Description |
|---|---|---|
| `cbom` | `rfq_id` | Regenerates the CBOM table from existing read-only input tables. Does not touch the 16 downstream reports. |
| `enrich_erp` | `rfq_id` | Fills `_erp` columns on existing CBOM rows from ERP master data. Requires `cbom` to have already run. |
| `enrich_costing_sheet` | `rfq_id` | Fills `_costing` columns on existing CBOM rows from costing sheet data. Requires `cbom`; independent of `enrich_erp`. |
| `resolve_final_selection` | `rfq_id` | **The HITL gate.** Auto-resolves `final_*` for rows where exactly one source has data; flags genuine multi-source conflicts for human review. |
| `generate_reports` | `rfq_id` | Regenerates all 16 reports from whatever CBOM data currently exists. Does not regenerate CBOM. |
| `export_reports` | `rfq_id` | Exports already-generated CBOM + 16 reports into one consolidated Excel workbook. Does not regenerate any data. |

## Cross-tool relationships / execution order

The live `Standard_BOM_Flow` routing sequence (real row in
`quote_routing_profiles`, see
[Database/logic-database.md](../Database/logic-database.md)) encodes the
actual, currently-used execution order across these tools:

```mermaid
flowchart LR
    A["centum_intake__standardize_scrub_bom"] --> B["centum_intake__standardize_quote_win"]
    B --> C["centum_intake__standardize_costing_sheet"]
    C --> D["centum_reporting__cbom"]
    D --> E["centum_reporting__enrich_costing_sheet"]
    E --> F["centum_reporting__resolve_final_selection<br/>(HITL gate)"]
    F --> G["centum_reporting__generate_reports"]
    G --> H["centum_reporting__export_reports"]
```

Note `enrich_erp` (skill_index 10) is registered in `system_skills_registry`
but marked `is_active = false` and does **not** appear in the live
`Standard_BOM_Flow` sequence — consistent with `standardize_erp` always
returning "skipped" today (no ERP upload path exists yet in the product).

The separate `Standard_BOM_Intake_Flow` profile (3 steps:
`intake__scan_local_file`, `intake_consolidation_bom_file`,
`intake__semantically_map_bom_files`) references tool names that do **not**
exactly match any tool documented above (`intake_consolidation_bom_file` and
`intake__semantically_map_bom_files` are not found in the dormant `intake`
server's own `mcp_server.py`, which only exposes `scan_local_file` and
`import_bom` as active tools). **Inference**: this profile may be either
stale/aspirational (referencing tools not yet implemented under those exact
names), or referencing a different, not-yet-located intake implementation.
Flagged here rather than silently reconciled — verify against
`system_skills_registry`'s own rows for these tool names before relying on
this profile.

The dormant `distributor_pricing` tools have their own internal ordering
requirement independent of the routing sequence: `enrich_bom` →
`detect_alternates` → `apply_alternatives` → `export_enriched_bom` (see
[MCP/distributor-pricing-tool-reference.md](../MCP/distributor-pricing-tool-reference.md)).
Since this server isn't currently wired into any registered profile, this
ordering is presently enforced only by convention/documentation, not by the
DMR.

## Registration process

**Inference** (MCP Jungle's own registration mechanics aren't visible from
this codebase — see [MCP/mcp-jungle.md](../MCP/mcp-jungle.md)'s scope note):
based on the confirmed integration contract, making a new or currently-dormant
tool callable through the live pipeline appears to require, at minimum:

1. The tool server process running and reachable.
2. The tool registered with MCP Jungle under the exact name used in
   `system_skills_registry.mcp_tool_name` (so `tools/call` with that name
   resolves to the right backend).
3. A row in `system_skills_registry` for the tool (skill_index, skill_name,
   macro_category, mcp_tool_name, `is_active = true`).
4. The tool's name inserted into the target profile's `routing_sequence`
   array at the desired position in `quote_routing_profiles`.

No code change to `fastapi_router.py`, `tool_calling.py`, or the Dify
workflow should be required for this — that's the intended payoff of the
MCP Jungle + Postgres-driven design (see
[Architecture/design-principles.md](../Architecture/design-principles.md)).

## Example request/response

A representative `/tool/execute` call for `centum_reporting__cbom` (from
[DMR/dynamic-master-router.md](../DMR/dynamic-master-router.md)'s step 4a),
shown end to end:

**Request** (Dify → `fastapi_router.py`):
```json
POST /tool/execute
{
  "tool_name": "centum_reporting__cbom",
  "arguments": { "rfq_id": "RFQ-000049" }
}
```

**fastapi_router.py → MCP Jungle** (JSON-RPC, via `tool_calling.call_tool()`):
```json
{
  "jsonrpc": "2.0",
  "id": 42,
  "method": "tools/call",
  "params": { "name": "centum_reporting__cbom", "arguments": { "rfq_id": "RFQ-000049" } }
}
```

**Response shape expected by the Dify workflow** (must include a `hitl`
field, per [DMR/dynamic-master-router.md](../DMR/dynamic-master-router.md)'s
step 4b):
```json
{ "status": "success", "hitl": 0, "...": "tool-specific fields" }
```

Exact response schemas per tool are documented in each server's own
file-reference document (linked above), since they vary by tool.

## Related documents

- [MCP/mcp-jungle.md](../MCP/mcp-jungle.md)
- [DMR/dynamic-master-router.md](../DMR/dynamic-master-router.md)
- [Database/logic-database.md](../Database/logic-database.md)
- [MCP/intake-tool-reference.md](../MCP/intake-tool-reference.md)
- [MCP/distributor-pricing-tool-reference.md](../MCP/distributor-pricing-tool-reference.md)
- [Backend/file-reference.md](../Backend/file-reference.md)
- [Reporting/reporting-module.md](../Reporting/reporting-module.md)
