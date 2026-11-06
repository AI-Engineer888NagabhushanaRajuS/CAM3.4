# Glossary

| Term | Definition |
|---|---|
| **RFQ** | Request For Quote — the top-level unit of work in this platform. Everything (a BOM upload, its pipeline progress, its generated reports) is scoped to one `rfq_id`. |
| **BOM** | Bill of Materials — the list of parts/components making up a product, uploaded as the initial input for an RFQ. |
| **SCRUB BOM** | The standardized/cleaned form of an uploaded BOM workbook, produced by `standardize_scrub_bom` and stored in DuckDB's `scrub_bom_items`/`volume`/`batch` tables. |
| **QuoteWin** | An "Awards Part Number Listing" report — pricing/award data standardized by `standardize_quote_win` into DuckDB's `quote_win` table. |
| **CBOM** | Costed BOM — the BOM enriched with pricing/cost data, built by the `cbom` MCP tool and enriched further by `enrich_costing_sheet`/`enrich_erp`. The centerpiece data structure the reporting pipeline is built around. |
| **Costing Sheet** | An optional third pipeline input providing additional costing data, standardized by `standardize_costing_sheet`. Replaced an earlier ERP-based input path (see **ERP** below). |
| **ERP** | Enterprise Resource Planning export — a purchase-history data source with a defined `standardize_erp`/`enrich_erp` tool pair, but **not currently exposed** in the product (no upload path exists; these tools are registered in `system_skills_registry` with `is_active = false` and always return "skipped"). |
| **HITL** | Human-In-The-Loop — a deliberate pause point in the pipeline where a tool signals `hitl: 1` in its response, halting the Dify DMR workflow until a human resolves something (most notably, the `resolve_final_selection` gate). |
| **DMR** | Dynamic Master Router — the Dify workflow app (literally named `Dify_DMR`) that fetches a routing sequence from Postgres and executes each tool in order, one HTTP call at a time. See [DMR/dynamic-master-router.md](../DMR/dynamic-master-router.md). |
| **MCP** | Model Context Protocol — the JSON-RPC-based protocol used to invoke tools (`tools/call`) through MCP Jungle. |
| **MCP Jungle** | The external gateway/hub that sits between `fastapi_router.py` and every individual FastMCP tool server, providing one consistent endpoint (`/mcp`, JSON-RPC) regardless of how many tool servers exist behind it. See [MCP/mcp-jungle.md](../MCP/mcp-jungle.md). |
| **FastMCP** | The Python framework (`from fastmcp import FastMCP`) used to implement every tool server in this platform (`scrub_mcp_server.py`, `reporting_module/mcp_server.py`, and the two dormant tool servers). |
| **skill_index** / **rfq_process_stage** | The integer position within a routing sequence that a given RFQ has reached. Stored as `rfq_process_tracking.rfq_process_stage` (runtime state, `file_metadata_db`) and cross-referenced against `system_skills_registry.skill_index` (config, `logic_db`). |
| **routing_sequence** | A JSONB array of `mcp_tool_name` strings defining the order tools execute in, stored per-profile in `quote_routing_profiles.routing_sequence`. Despite the name, it is a single array column, not a dedicated routing table. |
| **quote_routing_profiles** | The `logic_db` table holding named workflow profiles (`profile_name` → `routing_sequence`). Currently 2 real rows: `Standard_BOM_Intake_Flow` and `Standard_BOM_Flow`. |
| **system_skills_registry** | The `logic_db` table mapping each `mcp_tool_name` to metadata (`skill_index`, `skill_name`, `macro_category_name`, `is_active`). |
| **rfq_process_tracking** | The `file_metadata_db` table holding one row per `(rfq_id, version)`, tracking `rfq_process_stage`, `hitl_required`, and `is_active`. |
| **version** (of an RFQ) | A re-upload of a BOM for an already-existing `rfq_id` creates a new, isolated version rather than overwriting the prior one. `(rfq_id, version)` is the composite primary key of `rfq_process_tracking`; a partial unique index enforces only one version per `rfq_id` is ever `is_active = true`. |
| **versioned_key** | A `db.py` helper that constructs a compound identifier from `(rfq_id, version)`, used to keep each version's DuckDB-side data separate. |
| **CPN** | Customer Part Number — an identifier for a specific BOM line item, used throughout `reporting_module`'s hierarchy/rollup logic (e.g. "dual-role CPN," "structural CPN"). |
| **FG** | Finished Good — a top-level assembly in a BOM (as opposed to a sub-assembly or leaf component). Used extensively in `reporting_module`'s CBOM VL and Assembly Summary reporting logic. |
| **Hierarchy multiplier** | A per-row cumulative-quantity multiplier used in `reporting_module` to correctly weight a leaf component's true cost contribution to a Finished Good, accounting for how many times each ancestor sub-assembly is used. See [Reporting/reporting-module.md](../Reporting/reporting-module.md). |
| **Structural CPN** | A CPN that represents a sub-assembly container (used as an `assembly` value for other rows) rather than a purchased leaf component. |
| **Dual-role CPN** | A structural CPN that ALSO carries its own genuine, independently-quoted price (as opposed to a "pure container" whose price is purely a rollup of its children's costs). Requires special handling in the "Is Assembly" flag logic to avoid silently dropping its cost. |
| **Superset** | Apache Superset — the external BI/dashboarding tool this platform's data feeds, embedded directly into `apps/web` via guest tokens minted by `apps/daemon`. |
| **accomplish-ui** | The separate, general-purpose "Accomplish" product (an AI coworker desktop app) used as this platform's frontend. Not purpose-built for this BOM/RFQ platform — see [Frontend/accomplish-ui.md](../Frontend/accomplish-ui.md). |
| **DigiBull** | The organization maintaining the `SRIM-UI` fork of Accomplish used as this platform's frontend. |
| **SRIM 3.2** | The user-facing umbrella name for this whole assembled platform. Does not appear as an internal version string anywhere in the platform's own source code — found only as a UI preset label inside `accomplish-ui`. |
| **Dify** | The external workflow-automation SaaS/self-hosted product hosting the DMR workflow. Not part of this codebase; its workflow definition is an exported `.yml` (Dify DSL), the source of truth for [DMR/dynamic-master-router.md](../DMR/dynamic-master-router.md). |
