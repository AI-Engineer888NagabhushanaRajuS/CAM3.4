# Core Design Principles

## Table of Contents

- [Modular Architecture](#modular-architecture)
- [Configuration over Code](#configuration-over-code)
- [Dynamic Routing](#dynamic-routing)
- [Project Isolation](#project-isolation)
- [How well the current implementation matches these principles](#how-well-the-current-implementation-matches-these-principles)
- [Related documents](#related-documents)

## Modular Architecture

**Principle**: MCP Tools are independent modules; business capabilities are
encapsulated inside tools; tools can be reused across projects; tools
should be independently deployable where possible.

**How this is realized concretely**: every FastMCP tool server is its own
Python process with its own `requirements.txt`, reachable only through MCP
Jungle (see [MCP/mcp-jungle.md](../MCP/mcp-jungle.md)) — the router
(`fastapi_router.py`) never imports a tool's code directly, only calls it
by name over the network. This is verified, not aspirational: 2 of the 4
FastMCP servers documented in this platform (`intake`, `distributor_pricing`
— see [MCP/fastmcp-tools.md](../MCP/fastmcp-tools.md)) are currently
**dormant** (fully implemented, independently runnable, simply not
registered in the live orchestration) — direct, real evidence that a tool
genuinely can exist, be deployed, and be started independently of whether
it's wired into any particular routing sequence.

## Configuration over Code

**Principle**: business workflows should be modified by updating workflow
definitions stored in the Logic Database rather than changing application
code.

**How this is realized concretely**: see
[Database/logic-database.md](../Database/logic-database.md) in full — the
`quote_routing_profiles`/`system_skills_registry` tables are exactly this
configuration surface, and the extension guide there shows adding a skill
or a whole new profile requires zero changes to `fastapi_router.py`,
`tool_calling.py`, or any FastMCP tool. The one documented exception (the
Dify workflow's HTTP node hardcodes the profile name
`Standard_BOM_Flow`) is called out explicitly there and in
[DMR/dynamic-master-router.md](../DMR/dynamic-master-router.md) — worth
being aware this one seam isn't yet fully data-driven.

## Dynamic Routing

**Principle**: routing is determined at runtime; no workflow sequence
should be hardcoded; the DMR reads routing definitions from Postgres and
executes them iteratively.

**How this is realized concretely**: fully verified against the real Dify
workflow export — see
[DMR/dynamic-master-router.md](../DMR/dynamic-master-router.md) for the
exact node-by-node mechanics. The routing sequence truly is fetched fresh
on every run (`GET /pipeline/routing-sequence/{rfq_id}/{profile}`), and the
iteration genuinely walks whatever array comes back, with no tool names
baked into the Dify graph itself.

## Project Isolation

**Principle**: every project is completely isolated; projects should never
interfere with one another; only reusable platform components are shared.

**How this is realized concretely — IMPORTANT CAVEAT**: this principle is
**not yet implemented** in the running system as observed. There is
currently one `logic_db`, one `file_metadata_db`, and one shared Postgres
credential — no per-project database, schema, or role separation exists
today. [Database/logic-database.md](../Database/logic-database.md)'s
"Logic Database Isolation" section documents this principle in full as
**prescriptive guidance for onboarding the next project**, explicitly
distinguished from current state. Treat this principle as the design intent
this platform is built to eventually support (its Postgres-driven,
code-free-reconfiguration architecture makes per-project isolation
straightforward to add later), not as something already protecting
multiple concurrent projects today.

## How well the current implementation matches these principles

| Principle | Status |
|---|---|
| Modular Architecture | **Implemented and verified** — dormant tools prove independent deployability |
| Configuration over Code | **Implemented and verified**, with one hardcoded seam (Dify's profile name) |
| Dynamic Routing | **Implemented and verified** against the real Dify workflow |
| Project Isolation | **Not yet implemented** — documented as target/prescriptive guidance only |

This table exists so this document doesn't overstate the platform's current
maturity — 3 of 4 principles are demonstrably true today; the 4th is a
stated goal the architecture is well-positioned to support once the
provisioning work in
[Database/logic-database.md](../Database/logic-database.md#multi-project-architecture-target)
is actually done.

## Related documents

- [Architecture/overview.md](./overview.md)
- [DMR/dynamic-master-router.md](../DMR/dynamic-master-router.md)
- [Database/logic-database.md](../Database/logic-database.md)
- [MCP/mcp-jungle.md](../MCP/mcp-jungle.md), [MCP/fastmcp-tools.md](../MCP/fastmcp-tools.md)
