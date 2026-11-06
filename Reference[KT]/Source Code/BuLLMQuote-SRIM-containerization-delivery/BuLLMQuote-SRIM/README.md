# BuLLMQuote-SRIM

A BOM/RFQ costing automation platform (internal codename **SRIM 3.2**). It
ingests a Bill of Materials plus related quote/costing documents for an RFQ,
runs them through standardization → CBOM (Costed BOM) generation →
enrichment → human-reviewed final selection → report generation → Excel
export, and exposes results through a web frontend and Apache Superset
dashboards.

This repository is a **new, in-progress consolidation** of several
previously-scattered, independently-versioned SRIM codebases into a single
monorepo. This is Phase 1 of that migration — only the frontend and part of
the backend have been migrated so far. See `CLAUDE.md` for the full
architecture writeup (request flow, MCP tool inventory, database schema,
etc.) — read that first if you're extending the platform.

## Status

| Folder | Status | Source |
|---|---|---|
| `accomplish-ui/` | **Populated** | Copied from `C:\Users\ADMIN\Downloads\accomplish-ui\accomplish-ui\` (fresh copy, no git history — see below), audited with `knip` |
| `fastmcp-router/` | **Populated (partially working)** | 9 files copied from `centum intake\` — see `fastmcp-router/README.md` for per-file status |
| `mcp-tools/reporting/superset/` | **Populated (needs a DB path override)** | `reporting_module` copied from `centum intake\reporting_module\` — see `mcp-tools/reporting/superset/README.md` |
| `mcp-tools/distributor-pricing/` | **Populated** | FastMCP tool server for distributor pricing lookups (DigiKey/Mouser/Element14) |
| `mcp-tools/rfq-memory/` | **Populated** | RFQ memory/context service (OpenRouter-backed) |
| `database/` | **Populated (partially)** | `Bom_storage.duckdb` copied from `C:\SRIM-DB-SETUP\Databases\` — a different schema from what `mcp-tools/reporting/superset/` expects, see `database/README.md` |
| `deployment/` | Placeholder | See `deployment/README.md` |
| `dify-orchestration/` | Placeholder | See `dify-orchestration/README.md` |
| `docs/` | Populated | Full architecture documentation set — see `docs/README.md` |
| `mcp-tools/intake/` | Placeholder | See `mcp-tools/intake/README.md` |
| `mcp-tools/bom-processing/` | Placeholder | See `mcp-tools/bom-processing/README.md` |
| `testing/` | Placeholder | See `testing/README.md` |

## Important: the live backend is NOT here yet

The actual, currently-running backend (10 services: FastAPI routers, MCP
servers, the DuckDB-based reporting pipeline, etc.) still lives at
`C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum intake\` and is orchestrated
by that folder's own `manage_backend.py`. **Nothing in that directory was
touched or moved by this migration** — this repo is a separate copy that
doesn't yet talk to the real backend end-to-end.

## Prerequisites

- **Python 3.11+** — for `fastmcp-router/` and `mcp-tools/*` (FastMCP tool
  servers, FastAPI routers)
- **Node.js 20+ and pnpm** — for `accomplish-ui/` (Electron desktop shell +
  Vite web app + Node daemon)
- **PostgreSQL** — hosts `logic_db` and `file_metadata_db` (see
  `docs/Database/logic-database.md` for schema)
- **DuckDB** — embedded, no separate server; used by `database/` and the
  reporting pipeline
- **Windows** — `manage_backend.py` and several scripts hardcode absolute
  Windows paths; this platform has only been run on Windows so far

## Clone & environment setup

```
git clone https://github.com/solutionsDigibull/BuLLMQuote_SRIM.git
cd BuLLMQuote_SRIM
```

None of the services below ship with hardcoded credentials or fallback
defaults — every required secret must be supplied via an untracked `.env`
file (git-ignored by this repo's `.gitignore`). Copy each `.env.example` to
`.env` in the same folder and fill in real values before running that
service:

| Folder | `.env.example` → `.env` | Required variables |
|---|---|---|
| `fastmcp-router/` | `fastmcp-router/.env.example` | `LOGIC_DB_URL`, `FILE_METADATA_DB_URL`, `DIFY_BASE_URL`, `DIFY_API_KEY`, `JWT_SECRET` |
| `mcp-tools/distributor-pricing/` | `mcp-tools/distributor-pricing/.env.example` | `DIGIKEY_CLIENT_ID`, `DIGIKEY_CLIENT_SECRET`, `MOUSER_API_KEY`, `ELEMENT14_API_KEY`, `ELEMENT14_STORE`, `MYSQL_PASSWORD` |
| `mcp-tools/rfq-memory/` | `mcp-tools/rfq-memory/.env.example` | `OPENROUTER_API_KEY` |
| `accomplish-ui/apps/daemon/` | (create one if missing) | `DATABASE_URL`, `FILE_METADATA_DB_URL`, plus any Superset/integration keys — see `accomplish-ui/apps/daemon/README.md` if present |

`LOGIC_DB_URL` / `FILE_METADATA_DB_URL` / `DATABASE_URL` are standard
Postgres connection strings, e.g.:

```
postgresql://<user>:<password>@localhost:5432/logic_db
```

Create the two Postgres databases (`logic_db`, `file_metadata_db`) and their
tables per `docs/Database/logic-database.md` before starting any service
that touches them.

Install dependencies:

```
# Python services
cd fastmcp-router && pip install -r requirements.txt
cd ../mcp-tools/distributor-pricing && pip install -r requirements.txt
cd ../rfq-memory && pip install -r requirements.txt

# Frontend
cd ../../accomplish-ui && pnpm install
```

(If a `requirements.txt` is missing in a given folder, check that folder's
own `README.md` — some are partial migrations, see the Status table above.)

## Running the frontend

```
INSTALL.bat
LAUNCH-WEB.bat
```

This launches `accomplish-ui`'s web app (Vite dev server) and its daemon.
See `accomplish-ui/CLAUDE.md` for the full command reference (`pnpm dev`,
`pnpm build`, test commands, etc.) if you need to work on the frontend
directly rather than just running it.

## Running the backend services

The Python services under `fastmcp-router/` and `mcp-tools/*` are
independent FastMCP/FastAPI processes — each is started separately once its
`.env` is configured, e.g.:

```
cd fastmcp-router
python upload_server.py
```

There is no single "start everything" script in this repo yet — the live
system's equivalent (`manage_backend.py`) still lives in the original
`centum intake\` location and hardcodes paths specific to that machine (see
`docs/Backend/overview.md` and `docs/Deployment/deployment.md`). Porting a
working `manage_backend.py` into this repo is tracked as a follow-up.

## accomplish-ui dead-code audit (apps/web)

`knip` was run against `apps/web` (the browser frontend only — `apps/daemon`,
`apps/desktop`, and `packages/agent-core` were copied as-is, not audited).
31 files confirmed dead via cross-referencing (verified none were reachable
from `SettingsDialog.tsx`, `App.tsx`, or `router.tsx`, and none were imported
by anything outside their own cluster) were removed — a self-contained,
orphaned "settings panel" feature cluster (Skills, Scheduler, Workspaces,
Sandbox, CloudBrowsers, KnowledgeNotes panels and their helpers) apparently
superseded by `RoutingProfilePanel`/`ProjectTrackingPanel`/etc., plus an
orphaned page (`SrimNodes.tsx`), an orphaned component
(`AgentActivityStrip.tsx`, only referenced via a commented-out import), and
one dead barrel file (`components/skills/index.ts` — its own export,
`CreateSkillModal`, is actually still used, just imported directly rather
than through this barrel).

A further 15 files, 1 dependency group, 34 unused exports, 7 unused exported
types, and 4 duplicate-export pairs were flagged by knip but **left in place**
— not individually verified with the same rigor, so treated as "review before
removing," not "confirmed dead." Re-run `npx knip --workspace apps/web` from
this repo's `accomplish-ui/` to see the current list.

Verified post-removal: `npx knip` shows no new files became unused (the
removal didn't orphan anything else), `tsc -p tsconfig.client.json --noEmit`
produces the exact same 15 pre-existing errors as the untouched original
checkout (nothing new introduced), and `vite build` + the dev server both
succeed cleanly from this copy.

## accomplish-ui git history

The original checkout at
`C:\Users\ADMIN\Downloads\accomplish-ui\accomplish-ui\` is its own git repo
(remote: `github.com/solutionsDigibull/SRIM-UI.git`) with full history. The
copy in this repo's `accomplish-ui/` was made **without** `.git/`, to avoid a
nested-repo situation inside this monorepo. The original checkout is
untouched and still has full history if needed.

## Where to go for more detail

- [`CLAUDE.md`](./CLAUDE.md) — full platform architecture: request flow, MCP
  tool inventory, database schema, extension guide
- [`docs/README.md`](./docs/README.md) — full documentation index (per-topic
  deep dives referenced from `CLAUDE.md`)
- [`docs/DeveloperGuide/getting-started.md`](./docs/DeveloperGuide/getting-started.md)
  — known limitations and debugging a stuck pipeline

## Contributing / documentation policy

Any change that alters behavior, adds/removes a file, changes an API, a
database schema, or an architectural fact must update the corresponding
documentation in the same change — see `CLAUDE.md`'s "Documentation
Maintenance Policy" section at the top of that file for the full table of
what maps to what.
