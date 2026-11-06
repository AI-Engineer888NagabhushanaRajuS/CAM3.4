# Accomplish Frontend

## Table of Contents

- [Scope of this document](#scope-of-this-document)
- [What accomplish-ui actually is](#what-accomplish-ui-actually-is)
- [Monorepo structure](#monorepo-structure)
- [apps/web — the browser frontend](#appsweb--the-browser-frontend)
- [apps/daemon — the backend-for-frontend](#appsdaemon--the-backend-for-frontend)
- [apps/desktop](#appsdesktop)
- [packages/agent-core](#packagesagent-core)
- [How this platform's backend and frontend actually connect](#how-this-platforms-backend-and-frontend-actually-connect)
- [Build process](#build-process)
- [Environment variables](#environment-variables)
- [Dead-code audit performed on apps/web](#dead-code-audit-performed-on-appsweb)
- [Related documents](#related-documents)

## Scope of this document

This is **folder-level** documentation, not a full per-file reference (per
an explicit scoping decision — accomplish-ui is a large, separately
maintained monorepo of ~1,315 files, most of which are generic to its own
product and not specific to the BOM/RFQ platform this documentation set
otherwise covers in full per-file detail). A full per-file pass, if wanted,
should be scoped as its own follow-up effort.

## What accomplish-ui actually is

**Important, confirmed finding**: accomplish-ui is a **separate,
general-purpose product** ("Accomplish" — described in its own `README.md`
as "the open source AI coworker that lives on your desktop"), NOT a
purpose-built frontend for this BOM/RFQ platform. It is:
- Its own independent **git repository**, hosted at
  `github.com/solutionsDigibull/SRIM-UI.git` (a fork/instance of the
  upstream Accomplish project maintained by Digibull), with its own CI
  (`.github/`), Husky git hooks, CONTRIBUTING.md, and Vitest test suites.
- The original checkout lives at
  `C:\Users\ADMIN\Downloads\accomplish-ui\accomplish-ui\`; the copy inside
  this consolidated repo (`BuLLMQuote-SRIM\accomplish-ui\`) was made
  without `.git\` history, specifically to avoid a nested-repo situation
  before this monorepo has its own git history — the original checkout at
  Downloads remains the one with full history.
- The literal string "SRIM 3.2" appears exactly once anywhere in this
  platform's combined codebase — as a comment label inside this repo's
  `apps/web/src/client/components/settings/DeveloperSection.tsx`,
  describing a set of quick-add preset URLs for connecting Accomplish to
  this platform's own MCP/orchestration services (fastapi_router, MCP
  Jungle, etc.). It is a UI convenience label for connecting this generic
  product to this specific platform, not evidence that this platform has
  an internal version number.

## Monorepo structure

```
accomplish-ui/
├── apps/
│   ├── web/       -- React/Vite browser frontend, port 5180 in this platform's deployment
│   ├── daemon/     -- Node/Express backend-for-frontend, port 9234
│   └── desktop/    -- Electron desktop shell
├── packages/
│   └── agent-core/ -- shared agent/MCP-tool logic used by daemon and/or desktop
├── docs/           -- this project's OWN documentation (separate from BuLLMQuote-SRIM/docs/)
├── CLAUDE.md, AGENTS.md, CONTRIBUTING.md, README.md, SECURITY.md, TRADEMARKS.md
├── Dockerfile
└── pnpm-workspace.yaml, package.json  -- pnpm workspace root
```

pnpm workspace, `packageManager: pnpm@10.33.0` pinned in the root
`package.json` (confirmed matching version installed and used during this
platform's own consolidation work).

## apps/web — the browser frontend

**Package name**: `@accomplish/web`. **Stack**: React 19, Vite 8, TypeScript,
Tailwind CSS, Radix UI primitives, React Router 7, Zustand (state), AG-Grid
(data grids), `@superset-ui/embedded-sdk` (embeds Superset dashboards
directly in the UI — see
[Reporting/reporting-module.md](../Reporting/reporting-module.md)'s
Superset section for the other side of that integration).

```
apps/web/src/client/
├── App.tsx, main.tsx, router.tsx   -- app root, entry point, route table
├── pages/                           -- Home, Execution, History, LoginPage, admin/, execution/, home/
├── components/                      -- feature modules (costing-sheets, execution, rfq, settings, TaskLauncher, TaskInputBar, ...)
├── ui/                              -- Shadcn/Radix UI primitives (buttons, dialogs, dropdowns, ~50 components)
├── hooks/                           -- custom React hooks
├── stores/                          -- Zustand state stores (daemonStore, taskStore, workspaceStore, ...)
├── lib/                             -- shared utilities (session/auth, theming, file handling)
├── config/                          -- client-side endpoint configuration, feature flags
├── constants/, helpers/, i18n/      -- i18next-based internationalization
└── styles/                          -- Tailwind + custom global CSS
```

Routing: React Router 7 (`router.tsx`). Notable pages relevant to this
platform's own workflows: `pages/rfq/RfqCreateForm.tsx` (calls into
`window.accomplish` bridge APIs — an Electron-provided global, meaning some
functionality only works when running inside the desktop shell, not a
plain browser tab), `pages/execution/RfqIntakeProgressPanel.tsx`.

State management: Zustand stores, notably `daemonStore.ts` (connection
state to the `apps/daemon` backend) and `taskStore.ts`.

## apps/daemon — the backend-for-frontend

Node/Express service (package `@accomplish/daemon`, confirmed by
`apps/daemon/package.json`'s scripts: `build`, `start`, `dev`, `typecheck`,
`test`). Runs on port 9234 in this platform's deployment (see
[Backend/overview.md](../Backend/overview.md)'s service map).

Key source files (top level of `src/`):
- `daemon-routes.ts` / `browser-api-server.ts` — HTTP route definitions.
  **Confirmed**: `browser-api-server.ts` is the file implementing `POST
  /api/internal/trigger-hitl` — the endpoint the Dify DMR workflow calls to
  notify the frontend of a pending human review (see
  [DMR/dynamic-master-router.md](../DMR/dynamic-master-router.md), step 4d,
  and [APIs/endpoints.md](../APIs/endpoints.md)).
- `task-service.ts` / `task-service-events.ts` / `task-service-helpers.ts` /
  `task-callbacks.ts` / `task-config-builder.ts` / `task-event-forwarding.ts`
  — the task/agent execution pipeline (Accomplish's own generic
  task-running system, not specific to BOM/RFQ workflows).
- `superset-client.ts` — `getSupersetGuestToken(dashboardUuid)` and
  `getSupersetDomain()` — the daemon's side of embedding Superset
  dashboards via guest tokens (see
  [Reporting/reporting-module.md](../Reporting/reporting-module.md)).
- `auth/`, `auth-server.ts`, `google-account-service.ts` — Accomplish's own
  authentication (PAT, email/password, Google OAuth — confirmed via
  `apps/web/src/client/lib/session.ts`'s exports:
  `loginWithPat`/`loginWithEmailPassword`/`loginWithGoogle`). This governs
  access to the Accomplish product itself, not to this platform's own
  backend services (`fastapi_router.py` etc. have no auth layer of their
  own — see [Architecture/overview.md](../Architecture/overview.md#security)).
- `scheduler-service.ts`, `secrets-service.ts`, `settings-service.ts`,
  `skills-service.ts`, `storage-service.ts`, `connector-service.ts`,
  `whatsapp/` — generic Accomplish product features unrelated to the
  BOM/RFQ platform.
- `opencode/` — integration with the `@opencode-ai/sdk` dependency
  (confirmed in `package.json`) — Accomplish's own AI-agent execution
  backend, generic to the product, not BOM-platform-specific.
- `db.ts` — local storage (confirmed dependencies: `better-sqlite3` for
  local data, `pg` for Postgres, `duckdb` — **Inference**: this `duckdb`
  dependency may be what's blocked by this machine's Application Control
  policy, per `bom_qa_lookup_server.py`'s own documented reason for
  existing as a separate Python process rather than living in this daemon
  — see [Backend/file-reference.md](../Backend/file-reference.md#bom_qa_lookup_serverpy)).

## apps/desktop

Electron shell wrapping `apps/web`. Not investigated in detail for this
documentation pass (out of scope — this platform's own deployment uses
`apps/web` directly via its dev server, not the packaged desktop app; see
[Backend/overview.md](../Backend/overview.md)'s service map, which lists
`web_frontend` pointing at `apps/web`, not `apps/desktop`).

## packages/agent-core

A shared package (contains its own `src/`, `tests/`, `mcp-tools/`
subfolder) used by the daemon and/or desktop app for core agent/MCP-tool
logic. **Inference**: the `mcp-tools/` subfolder here is Accomplish's own
generic MCP tool integration layer (for connecting Accomplish to arbitrary
MCP servers, including this platform's own MCP Jungle gateway via the
DeveloperSection.tsx presets mentioned above) — distinct from, and not to
be confused with, this platform's own `intake`/`distributor_pricing`/
`scrub_mcp_server`/`reporting_module` FastMCP tool servers documented in
[MCP/fastmcp-tools.md](../MCP/fastmcp-tools.md).

## How this platform's backend and frontend actually connect

Two real, confirmed integration points, both already documented in detail
elsewhere:
1. **Upload → Dify trigger**: the UI's upload flow calls
   `upload_server.py`'s `POST /api/rfq/upload` (and the QuoteWin/Costing
   Sheet follow-ups), which in turn triggers the Dify DMR workflow (see
   [APIs/endpoints.md](../APIs/endpoints.md) and
   [DMR/dynamic-master-router.md](../DMR/dynamic-master-router.md)).
2. **HITL notification**: the Dify workflow calls this daemon's `POST
   /api/internal/trigger-hitl` directly (not through `upload_server.py`)
   to signal a pending human review.
3. **Q&A shortcut**: the daemon's task-service consults
   `bom_qa_lookup_server.py`'s `POST /ask` for known question shapes before
   falling back to a full LLM/MCP tool-calling loop (see
   [Backend/file-reference.md](../Backend/file-reference.md#bom_qa_lookup_serverpy)).
4. **Reporting dashboards**: `apps/web`'s `@superset-ui/embedded-sdk` +
   the daemon's `superset-client.ts` embed Superset dashboards directly in
   the UI, using guest tokens minted by the daemon.

No other direct HTTP integration between `apps/web`/`apps/daemon` and this
platform's own backend services (`duck_db_api.py`, `hitl_router.py`,
`fastapi_router.py`'s own endpoints) was confirmed during this
documentation pass — if the UI also calls those directly (e.g. for the BOM
preview/batch-update endpoints in
[APIs/endpoints.md](../APIs/endpoints.md)), that wiring lives inside
`apps/web/src/client/config/endpoints.ts` and the relevant page/component
code, which is out of scope for this folder-level pass — flagged as a gap
for a future full per-file frontend audit rather than asserted either way.

## Build process

`apps/web`: `pnpm run build` → `tsc -p tsconfig.client.json --noEmit && vite
build`. Confirmed working from a fresh copy during this platform's own
consolidation work — `vite build` succeeds cleanly (7,379 modules
transformed); `tsc` surfaces some pre-existing type errors that were
confirmed to also exist in the original, untouched upstream checkout (not
introduced by this platform's own work) — see
[DeveloperGuide/getting-started.md](../DeveloperGuide/getting-started.md)
for the exact error list and how to reproduce this finding.

`apps/daemon`: `pnpm run build` → a custom `scripts/build.cjs`
(`tsup`-based, per `tsup.config.ts`).

## Environment variables

`apps/daemon/.env` and `apps/web/.env` exist in the original checkout
(deliberately excluded from the copy into this consolidated repo, along
with `.env.example` templates preserved) — see
[Deployment/deployment.md](../Deployment/deployment.md) for the copy
policy. Exact variable names/values are out of scope here since they're
Accomplish-product-level configuration (API keys, OAuth client IDs, etc.),
not BOM/RFQ-platform-specific.

## Dead-code audit performed on apps/web

A `knip`-based dead-code audit was run against `apps/web` specifically
during this platform's consolidation work (not against `apps/daemon`,
`apps/desktop`, or `packages/agent-core`, which were copied as-is without
auditing). 31 files were confirmed dead (an orphaned "settings panel"
feature cluster — Skills, Scheduler, Workspaces, Sandbox, CloudBrowsers,
KnowledgeNotes panels — apparently superseded by newer
`RoutingProfilePanel`/`ProjectTrackingPanel` components, per an in-code
comment found during the audit) and removed from the copy in
`BuLLMQuote-SRIM\accomplish-ui\` only — **the original checkout at
Downloads was left completely untouched**, so this removal is specific to
the consolidated repo's own copy. A further 15 files and various unused
exports were flagged but deliberately left in place (not individually
verified with the same rigor). Full detail of exactly what was removed and
why is in this consolidated repo's own root `README.md`
(`BuLLMQuote-SRIM\README.md`), not duplicated here.

## Related documents

- [Backend/overview.md](../Backend/overview.md) — where `web_frontend`/`daemon` sit in this platform's own service map
- [APIs/endpoints.md](../APIs/endpoints.md) — `POST /api/internal/trigger-hitl` and the upload endpoints this UI calls
- [DMR/dynamic-master-router.md](../DMR/dynamic-master-router.md)
- [Reporting/reporting-module.md](../Reporting/reporting-module.md) — the Superset embedding this UI performs
- [Deployment/deployment.md](../Deployment/deployment.md) — the copy/audit process this repo's own `accomplish-ui/` went through
