# System & tech stack inventory — Centum / BuLLMQuote-SRIM

Every version number below was read directly off the live machine this
session (`--version` / `VersionInfo` / `pip show` / install-path checks), not
copied from memory or an older document. Where something could not be
checked without a live database connection, it's marked as such.

## Host system

| | |
|---|---|
| Hostname | DESKTOP-M17LKNB |
| OS | Windows 11 Pro, Build 26200 (10.0.26200) |
| Hardware | Dell, x64, BIOS 1.41.0 (2026-03-31) |
| CPU | 1 physical processor installed |
| RAM | 65,272 MB (~64 GB) |
| Deployment model | Bare desktop, no cloud. Remote access via NetBird WireGuard mesh only. |

## Core runtimes

| Runtime | Version |
|---|---|
| Node.js | v26.4.0 |
| npm | 11.17.0 |
| pnpm | 10.33.0 |
| Python | 3.10.11 |
| Git | 2.54.0.windows.1 |
| Docker Engine | 29.4.3 (build 055a478) |
| Docker Compose | v5.1.3 |
| Docker Desktop | 4.74.0.227015 (WSL2 backend, `docker-desktop` distro) |
| NetBird | 0.75.0.0 |

## Databases

| Database | Engine / version | Where it runs | Confirmed how |
|---|---|---|---|
| `logic_db_2`, `file_metadata_db_2`, `logic_db`, `file_metadata_db`, `cognee_memory_db`, `srim` | PostgreSQL **18** | Bare-metal Windows service, `:5432` | Install path `C:\Program Files\PostgreSQL\18` confirmed directly — version number NOT confirmed via `SELECT version()` (would require a live DB connection with the credential found in source, declined by this session's safety controls) |
| `cbom.duckdb`, `reports.duckdb`, `input_db.duckdb`, `bom_storage.duckdb` | DuckDB, Python binding **1.5.3** | Embedded files, under `centum intake\database\` and hardcoded paths — see [FINDINGS-AND-FIXES.md](FINDINGS-AND-FIXES.md) | `python -c "import duckdb; print(duckdb.__version__)"` on the active interpreter |
| `mcpjungle-db` | Postgres image `postgres:17` | Docker container, `:5432` published to host (shares the port number with the bare-metal instance above — they are different processes; the container's internal Postgres is NOT the same instance the application connects to) | `docker ps -a` |
| Dify's internal Postgres | `postgres:15-alpine` | Docker container `docker-db_postgres-1`, internal only, not published to host | `docker ps -a` |
| Cognee vector store | LanceDB (file-based, under `database/cognee_data/`) | Not Postgres, not pgvector | `mcp-tools/rfq-memory/config.py` |
| Cognee embeddings | Ollama, `nomic-embed-text`, 768-dim | Local, `localhost:11434` | `mcp-tools/rfq-memory/config.py` |

## MCP Jungle gateway

| | |
|---|---|
| Image | `ghcr.io/mcpjungle/mcpjungle:latest-stdio` |
| Version | **v0.4.5** |
| Container | `mcpjungle-server`, port `:8080`, published |
| Endpoint | `http://100.121.36.255:8080/mcp` (NetBird mesh IP — reachable beyond localhost) |
| Registered servers | **13** (confirmed via `mcpjungle list servers`) — only 2 belong to Centum/CAM |
| Registered tools | **66** (per its own dashboard) |

Full server list (see [SECURITY-REPORT.md](SECURITY-REPORT.md) for the
access-control concern on two of these):

| # | Server | Transport | Target | Belongs to |
|---|---|---|---|---|
| 1 | `postgres_logic` | stdio | `logic_db`, access-mode **unrestricted** | shared infra |
| 2 | `postgres_metadata` | stdio | `file_metadata_db`, access-mode **unrestricted** | shared infra |
| 3 | `feasibility` | streamable_http | `host.docker.internal:8002` | sibling project |
| 4 | `cbom` | streamable_http | `192.168.1.26:8002` (different host — not this repo's CBOM server) | sibling project |
| 5 | `Pydantic` | stdio (mcp-remote) | `gitmcp.io/pydantic/pydantic.git` | dev reference, unrelated |
| 6 | `nuitka_test` | streamable_http | `192.168.1.20:8000` | test/dev, unrelated |
| 7 | `centum_reporting` | streamable_http | `100.121.36.255:8005` (stale — real port is 8105, see Findings) | **this repo** |
| 8 | `centum_intake` | streamable_http | `100.121.36.255:8004` | **this repo** |
| 9 | `postgres_logic_2` | stdio | `logic_db_2`, access-mode **unrestricted** | shared infra |
| 10 | `postgres_metadata_2` | stdio | `file_metadata_db_2`, access-mode **unrestricted** | shared infra |
| 11 | `gerber_integration` | streamable_http | `100.121.36.255:8007` | sibling project |
| 12 | `intake` | streamable_http | `100.121.36.255:8002` | sibling project |
| 13 | `distributor` | streamable_http | `100.121.36.255:8003` | sibling project |

## Docker Desktop — full container inventory (14 containers)

| Container | Image | Role |
|---|---|---|
| `mcpjungle-server` | `ghcr.io/mcpjungle/mcpjungle:latest-stdio` | MCP gateway, see above |
| `mcpjungle-db` | `postgres:17` | MCP Jungle's own metadata store |
| `bifrost` | `bifrost-custom:v2.2.3` | MCP/LLM gateway for `RFQ_Flow`, `:8010` |
| `docker-nginx-1` | `nginx:latest` | reverse proxy, `:80`/`:443` |
| `docker-web-1` | `langgenius/dify-web:1.14.2` | Dify frontend |
| `docker-api-1` | `langgenius/dify-api:1.14.2` | Dify API |
| `docker-worker-1` | `langgenius/dify-api:1.14.2` | Dify background worker |
| `docker-worker_beat-1` | `langgenius/dify-api:1.14.2` | Dify scheduled-task worker |
| `docker-api_websocket-1` | `langgenius/dify-api:1.14.2` | Dify websocket worker |
| `docker-plugin_daemon-1` | `langgenius/dify-plugin-daemon:0.6.1-local` | Dify plugin runtime |
| `docker-sandbox-1` | `langgenius/dify-sandbox:0.2.15` | Dify code-execution sandbox |
| `docker-redis-1` | `redis:6-alpine` | Dify cache/queue |
| `docker-weaviate-1` | `semitechnologies/weaviate:1.27.0` | Dify's own vector store (unrelated to this platform's RAG) |
| `docker-db_postgres-1` | `postgres:15-alpine` | Dify's internal Postgres, not published to host |
| `docker-ssrf_proxy-1` | `ubuntu/squid:latest` | Dify sandbox's outbound proxy |
| `docker-init_permissions-1` | `busybox:latest` | one-shot init container, exits immediately |

Note: 10 of these belong to Dify, 2 to MCP Jungle, 1 to Bifrost, 1 is the
shared nginx proxy — the dossier's "10-container Dify stack" count matches
once the 3 shared/infra containers (Jungle ×2, Bifrost ×1) are set aside.

## Key backend Python package versions (active interpreter)

| Package | Version |
|---|---|
| fastapi | 0.137.0 |
| uvicorn | 0.49.0 |
| psycopg2-binary | 2.9.12 |
| PyJWT | 2.13.0 |
| openpyxl | 3.1.5 |
| pandas | 2.3.3 |
| fastmcp | 3.4.2 |
| cognee | **1.4.2, deliberately pinned** — `mcp-tools/rfq-memory/requirements.txt` documents in detail why: cognee 1.5.0–1.5.4 ship an Alembic migration that unconditionally imports `kuzu`, which fails to load its native library on Windows/Python 3.10. Do not bump without re-running that compatibility check. |

`gerber_integration`'s own stack (separate `requirements.txt`): `gerbonara>=1.6,<2`, `pydantic>=2.7`, `pyyaml>=6.0`, `pymupdf`.

## Frontend stack (accomplish-ui)

React 18, hash-based React Router, Zustand, Vite, `node-postgres` (`pg`),
`@superset-ui/embedded-sdk`, Uppy (FDE upload widget). Package-manager-level
versions are the Node/npm/pnpm versions above — accomplish-ui is a pnpm
workspace monorepo (`apps/web`, `apps/daemon`, `apps/desktop` present but
unused in this deployment, `packages/agent-core`).

## What could not be confirmed without a live, credentialed connection

- The exact running `SELECT version()` string for the bare-metal Postgres
  instance (install path confirms major version 18; the live server's actual
  running version/minor patch was not queried).
- Whether the live JWT secret has actually been rotated off the shipped
  insecure default (`fastmcp-router/auth.py` reads it from the environment;
  the value itself requires a check on the running process, not a code read).
- `project2_owner`'s actual Postgres role grants (see [SECURITY-REPORT.md](SECURITY-REPORT.md)).

All three require connecting to the live system with real credentials — this
session's safety controls declined to do that using a credential found in
source code, and it was not worked around. If these are needed, they should
be checked directly by whoever holds the credentials.
