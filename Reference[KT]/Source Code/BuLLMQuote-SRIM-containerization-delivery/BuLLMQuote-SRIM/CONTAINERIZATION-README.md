# Centum/BuLLMQuote-SRIM containerization -- start here

Everything in this delivery implements
`C:\Users\ADMIN\.claude\plans\swirling-strolling-shore.md` (Phases 0-3: build
and validate a containerized, Kubernetes-ready copy of Centum alongside the
live system, with zero disruption to CAM or Centum's own running
bare-metal processes). Scope is Centum/BuLLMQuote-SRIM only -- CAM (the
separate, live, client-serving deployment) was never touched, restarted, or
had its data modified at any point.

## What's actually been run and verified this session, not just written

- A real k3d Kubernetes cluster (`centum`) was created, every manifest in
  `k8s/` applied against its real API server, and 2 real bugs were caught
  and fixed by doing this (a missing ConfigMap, and a `enableServiceLinks`
  env-var collision that crashed Superset) -- not just YAML that looks right.
- `docker compose config` validates the full `docker-compose.yml` cleanly.
- Phase 0 (DuckDB data migration) ran for real: 3 files copied via DuckDB's
  own consistent-snapshot mechanism, row counts verified identical to CAM's
  live data, and a real report export was generated from the local copy and
  spot-checked against values already verified correct earlier this session.
- CAM's `manage_backend.py status` was checked ALL HEALTHY repeatedly
  throughout, including right before this file was written.

## What's written but not yet runtime-proven

- `mcp-tools/scrub-intake/` -- structurally migrated, imports cleanly, but
  no live Ollama/Postgres run was exercised against it.
- The full `centum/*` image set building successfully end-to-end (in
  progress / check `k8s/build-images.sh`'s own output for the latest result).
- `kubectl rollout undo` recovering a broken image -- needs the images built
  first; see `k8s/README.md`'s "Known gaps" section.
- Postgres seeding and the resulting row-count verification -- blocked on
  you running the `pg_dump` commands yourself (your password, never
  given to this session) and dropping the output in `database/pg_dump_seed/`.

## Map of what's where

| Path | What it is |
|---|---|
| `docker-compose.yml` | Real, working Compose stack -- the fastest way to run everything locally |
| `docker/` | Every Dockerfile (shared Python template + web/daemon production builds) |
| `k8s/` | Full k3d/Kubernetes manifests, build script, and its own README with the exact port map and known gaps |
| `infra/postgres/init-restore.sh` | One-time Postgres seed script (Compose and k8s both use it) |
| `infra/mcp-jungle/register-centum-servers.sh` | Reproduces Centum's 2 MCP Jungle registrations elsewhere -- deliberately excludes the other 11 servers on the shared gateway that belong to other projects |
| `database/sync_from_cam.py` + `register_sync_task.ps1` | Keeps Centum's local DuckDB copy fresh from CAM's live data, read-only |
| `mcp-tools/scrub-intake/` | `scrub_mcp_server` migrated into this repo (containerization Phase 2) |
| `requirements.txt` | Consolidated Python deps for every containerized service |
| `docs/` | The broader architecture dossier and findings from earlier this session -- not containerization-specific, but the context all of this was built on |

## The one thing only you can do

Run the `pg_dump`/`pg_dumpall` commands (given earlier this session) yourself
and drop the output in `database/pg_dump_seed/`. Nothing else in this delivery
can complete Phase 1 without that -- your Postgres password was never shared
with this session, by design.
