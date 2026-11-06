# PostgreSQL Logic Database

## Table of Contents

- [Overview](#overview)
- [Databases](#databases)
- [Schema: logic_db](#schema-logic_db)
  - [quote_routing_profiles](#quote_routing_profiles)
  - [system_skills_registry](#system_skills_registry)
- [Schema: file_metadata_db](#schema-file_metadata_db)
  - [rfq_process_tracking](#rfq_process_tracking)
- [How workflow execution is driven entirely by this data](#how-workflow-execution-is-driven-entirely-by-this-data)
- [Versioning strategy](#versioning-strategy)
- [Extension guide](#extension-guide)
- [Logic Database Isolation](#logic-database-isolation)
- [Multi-project architecture (target)](#multi-project-architecture-target)
- [Backup strategy](#backup-strategy)
- [Disaster recovery](#disaster-recovery)
- [Related documents](#related-documents)

## Overview

All schema and sample data in this document was pulled by live
`information_schema`/`pg_indexes` introspection against the actual running
Postgres instance during this documentation effort (not from any `.sql`
file — no local schema-definition file for these tables exists anywhere in
this codebase; they are provisioned upstream and accessed by application
code as an already-existing schema). Access goes exclusively through
`centum intake\db.py` (see
[Backend/file-reference.md](../Backend/file-reference.md#dbpy)).

## Databases

Two separate Postgres databases are in use, both on the same instance
(`postgresql://postgres:***@localhost:5432/`), reached via two distinct
connection helpers in `db.py`:

| Database | Connection helper | Purpose |
|---|---|---|
| `logic_db` | `get_logic_connection()` | **Workflow definitions** — routing sequences and the skill registry. Read-mostly from application code; conceptually "configuration," not runtime state. |
| `file_metadata_db` | `get_metadata_connection()` | **Runtime state** — per-RFQ execution progress. Read/write from application code on every pipeline step. |

This split (config vs. runtime state, in separate databases) is itself an
architectural signal worth preserving: `logic_db` should change rarely and
deliberately (a human editing a workflow), while `file_metadata_db` changes
constantly as pipelines run.

## Schema: logic_db

### quote_routing_profiles

| Column | Type | Nullable | Default |
|---|---|---|---|
| `profile_id` | `uuid` | NO | `uuid_generate_v4()` |
| `profile_name` | `character varying` | NO | — |
| `routing_sequence` | `jsonb` | NO | — |
| `created_at` | `timestamp without time zone` | YES | `CURRENT_TIMESTAMP` |
| `updated_at` | `timestamp without time zone` | YES | `CURRENT_TIMESTAMP` |

**Keys/indexes**: `PRIMARY KEY (profile_id)`; `UNIQUE (profile_name)`.

**Purpose**: one row per named workflow "profile." `routing_sequence` is a
JSONB array of `mcp_tool_name` strings, in the exact order they should
execute. This is the entire "routing table" — despite the name, it is a
single array column, not a set of ordered rows.

**All real rows, as of this writing** (2 total):

| `profile_name` | `routing_sequence` |
|---|---|
| `Standard_BOM_Intake_Flow` | `["intake__scan_local_file", "intake_consolidation_bom_file", "intake__semantically_map_bom_files"]` |
| `Standard_BOM_Flow` | `["centum_intake__standardize_scrub_bom", "centum_intake__standardize_quote_win", "centum_intake__standardize_costing_sheet", "centum_reporting__cbom", "centum_reporting__enrich_costing_sheet", "centum_reporting__resolve_final_selection", "centum_reporting__generate_reports", "centum_reporting__export_reports"]` |

`Standard_BOM_Flow` is the profile the current Dify DMR workflow is
hardcoded to request (see
[DMR/dynamic-master-router.md](../DMR/dynamic-master-router.md)). Note
`Standard_BOM_Intake_Flow` references 2 tool names
(`intake_consolidation_bom_file`, `intake__semantically_map_bom_files`) not
found as active tools in the dormant `intake` MCP server as currently
implemented — flagged in
[MCP/fastmcp-tools.md](../MCP/fastmcp-tools.md#cross-tool-relationships--execution-order)
as unresolved, not silently assumed correct.

### system_skills_registry

| Column | Type | Nullable | Default |
|---|---|---|---|
| `skill_code` | `character varying` | NO | — |
| `skill_index` | `integer` | NO | — |
| `skill_name` | `character varying` | NO | — |
| `macro_category_name` | `character varying` | NO | — |
| `mcp_tool_name` | `character varying` | NO | — |
| `input_template` | `jsonb` | NO | `'{}'::jsonb` |
| `requires_llm` | `boolean` | YES | `false` |
| `is_active` | `boolean` | YES | `true` |
| `created_at` | `timestamp without time zone` | YES | `CURRENT_TIMESTAMP` |
| `macro_category` | `integer` | YES | — |

**Keys/indexes**: `PRIMARY KEY (skill_code)`; `UNIQUE (skill_index)`.

**Purpose**: a lookup/metadata table mapping each `mcp_tool_name` to a
human-readable `skill_name`, an integer `skill_index` (this is the value
`rfq_process_tracking.rfq_process_stage` advances through), and a
`macro_category_name` grouping. `is_active = false` marks a skill as
registered but not currently live (see the ERP rows below).

**All real rows, as of this writing** (10 total, ordered by `skill_index`):

| `skill_index` | `skill_code` | `skill_name` | `mcp_tool_name` | `macro_category_name` | `is_active` |
|---|---|---|---|---|---|
| 1 | `M03.1_ScrubBOMStandardize` | Standardize SCRUB BOM Workbook | `centum_intake__standardize_scrub_bom` | intake | true |
| 2 | `M03.2_QuoteWinStandardize` | Standardize QuoteWin Report | `centum_intake__standardize_quote_win` | erpDataSync | true |
| 3 | `M03.3_CostingSheetStandardize` | Standardize Costing Sheet (optional) | `centum_intake__standardize_costing_sheet` | erpDataSync | true |
| 4 | `M03.4_CbomBuild` | Build CBOM Structure + QuoteWin Pricing | `centum_reporting__cbom` | pricingConsolidation | true |
| 5 | `M03.5_CostingEnrichment` | Enrich CBOM with Costing Sheet Data | `centum_reporting__enrich_costing_sheet` | pricingConsolidation | true |
| 6 | `M03.6_FinalSelectionHITL` | Resolve Final Cost Selection (HITL gate) | `centum_reporting__resolve_final_selection` | pricingConsolidation | true |
| 7 | `M03.7_GenerateReports` | Generate CBOM Reports | `centum_reporting__generate_reports` | reportingAnalytics | true |
| 8 | `M03.8_ExportReports` | Export CBOM Reports to Excel | `centum_reporting__export_reports` | reportingAnalytics | true |
| 9 | `M03.9_ErpStandardize` | Standardize ERP Export (not currently exposed) | `centum_intake__standardize_erp` | erpDataSync | **false** |
| 10 | `M03.10_ErpEnrichment` | Enrich CBOM with ERP Data (not currently exposed) | `centum_reporting__enrich_erp` | pricingConsolidation | **false** |

Note skills 1-8 exactly match `Standard_BOM_Flow`'s `routing_sequence` in
the same order — confirming the registry and the profile are kept
consistent in practice for the live flow. Skills 9-10 (ERP) are registered
but excluded from the live sequence, matching `standardize_erp` always
returning "skipped" (no ERP upload path in the current product).

## Schema: file_metadata_db

### rfq_process_tracking

| Column | Type | Nullable | Default |
|---|---|---|---|
| `rfq_id` | `character varying` | NO | — |
| `rfq_process_stage` | `integer` | NO | `0` |
| `hitl_required` | `boolean` | NO | `false` |
| `triggered_by` | `character varying` | YES | `'SYSTEM_API'` |
| `created_at` | `timestamp without time zone` | NO | `CURRENT_TIMESTAMP` |
| `updated_at` | `timestamp without time zone` | NO | `CURRENT_TIMESTAMP` |
| `version` | `integer` | NO | `1` |
| `is_active` | `boolean` | NO | `true` |

**Keys/indexes**:
- `PRIMARY KEY (rfq_id, version)` — composite key, one row per version of a given RFQ.
- `idx_fmd_rfq_stage` — plain btree index on `rfq_process_stage` (supports queries filtering/sorting by pipeline progress).
- `idx_rfq_process_tracking_one_active` — a **partial unique index** on `rfq_id` `WHERE is_active` — this is the mechanism that enforces "only one version of a given RFQ can be active at a time" at the database level, not just by application convention.

**Purpose**: the actual runtime "skill index" state — `rfq_process_stage`
is the integer position in the routing sequence this RFQ has reached.
`hitl_required` mirrors whether the pipeline is currently paused awaiting
human review.

**Sample real rows** (5 most recently updated, at time of writing):

| `rfq_id` | `version` | `rfq_process_stage` | `is_active` | `hitl_required` | `triggered_by` |
|---|---|---|---|---|---|
| RFQ-000049 | 1 | 8 | true | false | UI_CANVAS_PORT_3000 |
| RFQ-000048 | 1 | 8 | true | false | UI_CANVAS_PORT_3000 |
| RFQ-000047 | 1 | 8 | true | false | UI_CANVAS_PORT_3000 |
| RFQ-000046 | 1 | 8 | true | false | UI_CANVAS_PORT_3000 |
| RFQ-000045 | 1 | 8 | true | false | UI_CANVAS_PORT_3000 |

All 5 sample rows sit at `rfq_process_stage = 8` with `hitl_required =
false` — i.e. fully completed runs through all 8 `Standard_BOM_Flow` steps,
with no pending human review. `triggered_by = UI_CANVAS_PORT_3000` confirms
these were initiated through the frontend's upload UI (port 3000 is
`upload_server.py`, see [APIs/endpoints.md](../APIs/endpoints.md)), not a
direct API call.

## How workflow execution is driven entirely by this data

No tool name, execution order, or step count is hardcoded in
`fastapi_router.py`, `tool_calling.py`, or (mostly) the Dify workflow. The
one exception, worth being explicit about: the Dify workflow's own HTTP
Request node hardcodes the **profile name** `Standard_BOM_Flow` in its URL
(see [DMR/dynamic-master-router.md](../DMR/dynamic-master-router.md)) — so
today, changing *which* profile a given Dify app uses requires editing that
Dify workflow, not just the database. Everything *within* a profile (which
tools, in what order, how many steps) is 100% data-driven from the two
tables above.

## Versioning strategy

`(rfq_id, version)` as a composite primary key allows the same `rfq_id` to
be re-run as a new, independent version — e.g. re-uploading a corrected BOM
for an RFQ that already completed once. `db.py`'s `get_active_version()` /
`versioned_key()` functions (see
[Backend/file-reference.md](../Backend/file-reference.md#dbpy)) resolve
which version is "current" for a given `rfq_id`, backed by the partial
unique index ensuring only one version is ever marked `is_active = true`
at a time. DuckDB-side data (in `reporting_module`) uses this same
`versioned_key()` to construct a compound key so re-running a version
doesn't silently overwrite the prior version's data.

## Extension guide

**Adding a new skill to an existing flow:**
1. Insert a row into `system_skills_registry` with a free `skill_index`, the exact `mcp_tool_name` MCP Jungle will route to, and `is_active = true`.
2. Insert that same `mcp_tool_name` string into the target profile's `routing_sequence` JSONB array in `quote_routing_profiles`, at the desired position.
3. No application code changes needed for the router/DMR side (see [MCP/fastmcp-tools.md](../MCP/fastmcp-tools.md#registration-process) for the MCP Jungle registration side, which IS required).

**Creating a new workflow profile:**
1. Insert a new row into `quote_routing_profiles` with a new `profile_name` and its own `routing_sequence` array, built from existing or new `system_skills_registry` entries.
2. A Dify workflow (or a new one) needs to actually request that profile name via its routing-sequence HTTP node — today this is a literal string in the Dify graph, not database-driven, so this step does require a Dify-side change.

**Creating a new Logic Database for a new project:** see
[Multi-project architecture (target)](#multi-project-architecture-target)
below.

## Logic Database Isolation

> The following is **prescriptive guidance for how future projects should be
> onboarded**, not a description of what's implemented today. As observed
> live, there is currently one `logic_db` and one `file_metadata_db`,
> accessed by a single Postgres role (the connection string in `db.py` uses
> a single `postgres` superuser-style credential, not a scoped per-project
> role) — there is no per-project database, schema, or role separation in
> the running system today. The principles below describe the target state
> this platform's modularity claims depend on, and should guide how the
> *next* project is provisioned, not be read as already true.

The PostgreSQL Logic Database is the authoritative source of workflow
definitions and runtime routing for a project. It must be treated as
protected, project-specific configuration:

- **Every project must have its own dedicated PostgreSQL database user.**
  A shared superuser credential (as currently used) cannot enforce that one
  project's automation can't accidentally read or write another's routing
  data — isolation currently depends entirely on there being only one
  project's data in the database, which does not scale to multiple
  simultaneous projects.
- **Prefer separate databases, or at minimum separate schemas, per
  project.** A separate database gives the strongest boundary (no way to
  reference another project's tables even by mistake); a separate schema
  under the same database is the minimum acceptable fallback.
- **Workflow definitions, routing sequences, and business logic must remain
  isolated between projects.** One project's `quote_routing_profiles`/
  `system_skills_registry` rows should never be visible to, joinable with,
  or mutable by another project's runtime.
- **One project's Logic Database must never be modified, queried, or
  impacted by another project's execution.** The DMR and MCP tools for
  Project B should not even be able to construct a connection string that
  reaches Project A's Logic Database.
- **Logic databases should remain untouched except through approved
  administrative or deployment processes.** Routing/skill definitions are
  not meant to be edited ad hoc by application code at runtime — they
  should change through a deliberate, reviewed process (a migration, an
  admin tool, or a controlled deployment step), the same way schema
  migrations are handled.
- **MCP Tools must never directly modify workflow routing definitions.** A
  tool's job is to do its one business capability and report `hitl`/result
  status back; it should have no write access to `quote_routing_profiles`
  or `system_skills_registry` at all — only the DMR/router layer (and
  humans, via an admin process) should be able to change routing.
- **The Dynamic Master Router should only have the minimum required
  permissions for the current project** — read access to that project's
  routing tables, read/write access to that project's runtime state table,
  nothing more.
- **Cross-project database access should not exist.** No shared connection
  pool, no shared credential, no shared schema search path that could let
  one project's queries accidentally resolve against another's tables.
- **Business logic should evolve by updating project-specific Logic DB
  contents rather than changing application code.** This is the existing
  design's own stated goal (see
  [Architecture/design-principles.md](../Architecture/design-principles.md))
  — the isolation principles above exist specifically to make that safe to
  do at scale, without one project's configuration change able to affect
  another's.

**Why dedicated PostgreSQL users are required, specifically:** database
permissions are an enforcement mechanism, not just a policy statement.
Relying solely on "the application code always filters by project" to
guarantee isolation means a single bug, a copy-pasted query missing a
`WHERE project_id = ...` clause, or a future engineer unfamiliar with the
convention can silently leak or corrupt another project's routing logic.
A dedicated role scoped (via `GRANT`) to only its own project's
database/schema makes that class of bug impossible to have externally
visible consequences, regardless of application-layer mistakes.

## Multi-project architecture (target)

Onboarding a new project, per the principles above, should look like:
1. Provision a new, isolated Logic Database (new database or new schema) —
   never reuse an existing project's.
2. Provision a new, dedicated Postgres role scoped only to that database/schema.
3. Populate `quote_routing_profiles`/`system_skills_registry`-equivalent
   tables for the new project's own workflow.
4. Point that project's own DMR/router deployment at the new role's
   connection string — the orchestration engine's code itself does not
   change; only its configuration (database URL, MCP tool set) does. This
   is the literal mechanism behind the platform's "reuse the same platform
   by replacing MCP Tool set / Logic Database / routing sequence" design
   goal (see [Architecture/design-principles.md](../Architecture/design-principles.md)).

## Backup strategy

Not implemented/observed in this codebase as of this writing — no backup
scripts, cron jobs, or `pg_dump` automation were found alongside `db.py` or
`manage_backend.py`. `centum intake\backup_postgres_demo_data.py` exists
(see [Backend/file-reference.md](../Backend/file-reference.md)) but is a
manual demo-data snapshot utility, not a scheduled backup strategy. **This
is a real, current gap**, not a design choice — flagged here rather than
described as if a strategy exists.

## Disaster recovery

Not implemented/observed. No documented recovery runbook, replica, or
point-in-time-recovery configuration was found. Given the DMR's own
resumption design (any run can restart cleanly from
`rfq_process_tracking.rfq_process_stage`, see
[DMR/dynamic-master-router.md](../DMR/dynamic-master-router.md#recovery--resumption)),
a Logic Database restore from any backup point would correctly resume
in-flight RFQs from wherever their last-committed `rfq_process_stage` was
— but this depends entirely on a working *backup* existing first, which
per the above, is not currently in place.

## Related documents

- [DMR/dynamic-master-router.md](../DMR/dynamic-master-router.md)
- [MCP/fastmcp-tools.md](../MCP/fastmcp-tools.md)
- [Backend/file-reference.md](../Backend/file-reference.md)
- [Architecture/design-principles.md](../Architecture/design-principles.md)
