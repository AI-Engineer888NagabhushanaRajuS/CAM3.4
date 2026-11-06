# Session summary — 2026-10-27 — CAM / Centum verification work

This is the index for everything produced in this session, across both related
deployments. Read this first; it links to everything else.

## CAM vs. Centum — resolving the naming confusion

These are **two related but distinct deployments of the same open-source UI**,
not the same project:

| | CAM | Centum (this repo) |
|---|---|---|
| Location | `C:\Users\ADMIN\Downloads\accomplish-ui\accomplish-ui` | `C:\Users\ADMIN\Documents\BuLLMQuote-SRIM` |
| Frontend git remote | `github.com/solutionsDigibull/SRIM-UI.git` | (daemon/web under `accomplish-ui/` subfolder here) |
| Backend | `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum intake` | `fastmcp-router/`, `mcp-tools/` in this repo |
| Backend GitHub repo | `github.com/solutionsDigibull/CAM.git` (private) | one local commit only, no remote push yet |
| Relationship | **Earlier, parent deployment** — `logic_db_2`/`file_metadata_db_2` were originally split *from* CAM's own database | Forked from CAM; added Bifrost gateway, FDE staging pipeline, RFQ_Flow |
| Who's using it | A real client, live, right now | Internal / in development |

They share lineage and some naming conventions (which is why "CAM", "Centum",
and "SRIM 3.2" get used interchangeably) but are separate codebases with
separate databases, separate frontends, and separate GitHub repos.

## What was done, in order

1. **CBOM Excel export fix** (CAM backend, `reporting_module/`) — the Assembly
   Summary's "Ext Part Vol Price" cell wasn't computing `Ext Vol Qty × Ext
   Price`, and was a static snapshot instead of a live formula. Fixed in
   `templates/excel_mappings.py` (the aggregation) and `reports/cbom_vl.py`
   (made it a real `=F{row}*E{row}` Excel formula so it recalculates live).
   Verified against real RFQ-000215 data.

2. **CAM backend + frontend pushed to GitHub** — `github.com/solutionsDigibull/CAM.git`
   (private, `main`, commit `0d54fd9`). Scoped to `apps/web` + `apps/daemon` +
   `packages/agent-core` (desktop excluded per instruction). Zero secrets,
   zero database files, zero BullMQuote-SRIM references included. The live,
   client-serving backend and frontend were never touched, restarted, or
   disrupted to do this — confirmed via `manage_backend.py status` before and
   after. Later independently re-verified byte-for-byte up to date via a
   fresh clone.

3. **MCP Jungle gateway mapped** — a shared Docker-hosted MCP gateway
   (`mcpjungle-server`, v0.4.5, `:8080`) serving 13 registered servers across
   *multiple* projects, not just this one. Only 2 belong to CAM/Centum
   (`centum_reporting`, `centum_intake`). The rest — `postgres_logic`,
   `postgres_metadata` (unrestricted direct SQL into `logic_db`/`file_metadata_db`),
   their `_2` duplicates, `feasibility`, a second `cbom` server on a different
   host, `gerber_integration`, `intake`, `distributor` — belong to this
   BuLLMQuote-SRIM deployment and sibling tools, reachable over this
   machine's NetBird mesh IP, not just localhost. See
   [SECURITY-REPORT.md](SECURITY-REPORT.md).

4. **Architecture dossier built and twice independently verified**, covering
   this Centum/BuLLMQuote-SRIM deployment specifically —
   [`architecture-dossier.html`](architecture-dossier.html), now at **Rev C**:
   - Rev A: a 9-agent audit, prose-heavy.
   - Rev B: rebuilt with 6 engineering-drawing-style diagrams after the
     prose-heavy version was rejected; 7 load-bearing claims independently
     re-verified against live source.
   - Rev C: a second, independent 8-method review council (run via cheap
     models, methodology from the user's own portfolio orchestration system)
     re-tested Rev B's claims. Corrected two of them, confirmed the rest. Full
     detail in [FINDINGS-AND-FIXES.md](FINDINGS-AND-FIXES.md).

## Documents in this set

- **This file** — the index and CAM/Centum relationship.
- [`architecture-dossier.html`](architecture-dossier.html) — full visual
  architecture reference (deployment topology, request-flow sequence diagram,
  gateway schematic, database schematic, FDE pipeline, Dify DMR), Rev C.
- [`EXECUTIVE-SUMMARY.md`](EXECUTIVE-SUMMARY.md) — one page, non-technical.
- [`FINDINGS-AND-FIXES.md`](FINDINGS-AND-FIXES.md) — every bug found, ticket-style,
  with repro steps and suggested fixes.
- [`SECURITY-REPORT.md`](SECURITY-REPORT.md) — the 5 security gaps, standalone.
- [`MIGRATION-RISK-STANDARD-BOM-FLOW.md`](MIGRATION-RISK-STANDARD-BOM-FLOW.md) —
  pre-migration checklist for the latent Jungle→Bifrost routing bug.
- [`SYSTEM-AND-TECH-STACK.md`](SYSTEM-AND-TECH-STACK.md) — every concrete
  version number (OS, Node, Python, Docker, Postgres, DuckDB, NetBird,
  MCP Jungle's full 13-server list, all 14 Docker containers, key package
  versions) read directly off the live machine this session.

## What was explicitly NOT done

- No live file was uploaded through either CAM's or Centum's production UI.
  No browser-automation tooling exists in this environment, and driving a
  real upload→processing run would create real data on a system a client is
  actively using — out of scope without that risk being explicitly accepted
  and an isolated environment (the FDE staging databases) chosen first.
- No live Postgres query was run using the credentials found in source code
  — flagged and declined by this session's own safety controls; the two
  database-permission claims in the dossier (`project2_owner`'s cross-database
  grants) remain carried from an earlier pass, not independently re-queried.
- No code was edited, no service was restarted, in either CAM or Centum, to
  produce any of this documentation.
