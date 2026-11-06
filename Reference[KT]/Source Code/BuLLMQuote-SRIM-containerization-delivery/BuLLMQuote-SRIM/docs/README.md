# SRIM 3.2 — Technical Documentation

Official engineering documentation for this platform's architecture,
components, and codebase. Written to be the long-term reference for new
engineers, solution architects, technical leads, and future AI-assisted
development (see [CLAUDE_CONTEXT.md](./CLAUDE_CONTEXT.md) specifically for
the latter).

## How to navigate

Start with **[CLAUDE_CONTEXT.md](./CLAUDE_CONTEXT.md)** for a complete,
self-contained orientation — architecture summary, folder map, coding
standards, request flow, extension guide, and glossary in one place. Every
other document below goes deeper on its specific area.

| Area | Document | What it covers |
|---|---|---|
| Architecture | [Architecture/overview.md](./Architecture/overview.md) | System architecture, lifecycles, data flow, security, deployment, scalability |
| Architecture | [Architecture/design-principles.md](./Architecture/design-principles.md) | Modular architecture, config-over-code, dynamic routing, project isolation — with an honest current-vs-target assessment |
| Orchestration | [DMR/dynamic-master-router.md](./DMR/dynamic-master-router.md) | The Dify-based Dynamic Master Router, grounded in the real exported workflow |
| MCP | [MCP/mcp-jungle.md](./MCP/mcp-jungle.md) | The external MCP gateway integration contract |
| MCP | [MCP/fastmcp-tools.md](./MCP/fastmcp-tools.md) | All 16 tools across 4 FastMCP servers, cross-tool relationships |
| MCP | [MCP/intake-tool-reference.md](./MCP/intake-tool-reference.md) | Full per-file reference: the dormant `intake` tool server |
| MCP | [MCP/distributor-pricing-tool-reference.md](./MCP/distributor-pricing-tool-reference.md) | Full per-file reference: the dormant `distributor_pricing` tool server |
| Database | [Database/logic-database.md](./Database/logic-database.md) | Real Postgres schema (logic_db, file_metadata_db), plus prescriptive multi-project isolation guidance |
| Backend | [Backend/overview.md](./Backend/overview.md) | Service map, startup process |
| Backend | [Backend/file-reference.md](./Backend/file-reference.md) | Full per-file reference: `centum intake`'s 25 root files |
| Reporting | [Reporting/reporting-module.md](./Reporting/reporting-module.md) | Full per-file reference: the CBOM/reporting pipeline, plus Superset integration |
| Frontend | [Frontend/accomplish-ui.md](./Frontend/accomplish-ui.md) | Folder-level architecture of the accomplish-ui frontend monorepo |
| APIs | [APIs/endpoints.md](./APIs/endpoints.md) | Every REST endpoint across all backend services |
| Deployment | [Deployment/deployment.md](./Deployment/deployment.md) | Current reality vs. target state, orchestration mechanics, secrets, networking |
| Developer Guide | [DeveloperGuide/getting-started.md](./DeveloperGuide/getting-started.md) | Local setup, running services, testing, debugging, known issues |
| Reference | [Reference/glossary.md](./Reference/glossary.md) | Every term used throughout this documentation set |

## Documentation conventions used throughout this set

- **`**Inference:**`** — anything labeled this way is a reasonable
  conclusion drawn from the code, not a directly-confirmed fact. Verify
  before relying on it for something consequential.
- **Cross-references** — every document links to related documents at its
  end; follow them rather than assuming one document is self-contained
  (except `CLAUDE_CONTEXT.md`, which deliberately is).
- **Current state vs. target/prescriptive guidance** — explicitly labeled
  wherever the two diverge (most notably: multi-project isolation in
  [Database/logic-database.md](./Database/logic-database.md), and the
  overall maturity assessment in
  [Architecture/design-principles.md](./Architecture/design-principles.md)).
  This documentation set deliberately does not present aspirational
  architecture as already-implemented fact.
- **Ground truth over inference where available** — the DMR documentation
  is derived directly from a real Dify workflow export
  (`Dify_DMR (6).yml`), not reverse-engineered from partial evidence;
  the Database documentation is derived from live `information_schema`
  introspection against the running Postgres instance, not from any
  `.sql` file (none exists in this codebase for these tables).

## Keeping this documentation in sync

**This is a living documentation set, not a one-time snapshot.** Every
code change that alters behavior, an API, a database schema, a routing
sequence, or an architectural fact stated here must update the
corresponding document in the same change — see
[CLAUDE_CONTEXT.md](./CLAUDE_CONTEXT.md)'s "Documentation Maintenance
Policy" section for the full rule, a table mapping code areas to the
document that owns them, and verification steps. If you're a human
maintainer rather than an AI session, the same rule applies to you —
don't merge a change without updating its documentation.

## Scope note

Full per-file documentation covers the core platform: `centum intake`'s
root (25 files), `reporting_module` (51 files), and the two dormant MCP
tool servers `intake` (25 files) and `distributor_pricing` (17 files) — the
BOM/RFQ-specific codebase. `accomplish-ui` (a separate, general-purpose
frontend product, ~1,315 files) is documented at folder level only in this
pass — see [Frontend/accomplish-ui.md](./Frontend/accomplish-ui.md)'s own
scope note for why, and what a follow-up full per-file pass would need to
cover.
