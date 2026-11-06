# CAM 3.4 — Credentials & Service Map

**KEEP THIS FILE OUT OF GIT** (add `SECRETS.md` to `.gitignore` if not already)

---

## PostgreSQL (Native, Port 5432)

| Role | Password | Purpose |
|------|----------|---------|
| `postgres` | `$CAM_PG_SUPERUSER_PASSWORD` | Superuser / admin |
| `solutions@digibull.ai` | `$CAM_PG_APP_PASSWORD` | CAM 3.4 app user |

Passwords are never written in this file. Set them as environment variables (or in the git-ignored `fastapi-router/.env`); see `CAM-Source/.env.example` for names.

| Database | Owner | Used by |
|----------|-------|---------|
| `logic_db_2` | `solutions@digibull.ai` | Skills registry, routing profiles, advisory locks |
| `file_metadata_db_2` | `solutions@digibull.ai` | RFQ tracking, file telemetry |
| `staging_logic_db_2` | `solutions@digibull.ai` | FDE staging (optional) |
| `staging_file_metadata_db_2` | `solutions@digibull.ai` | FDE staging (optional) |

**Connection strings (in `.env`):**
```
LOGIC_DB_URL=postgresql://solutions%40digibull.ai:<URL-encoded CAM_PG_APP_PASSWORD>@localhost:5432/logic_db_2
FILE_METADATA_DB_URL=postgresql://solutions%40digibull.ai:<URL-encoded CAM_PG_APP_PASSWORD>@localhost:5432/file_metadata_db_2
```

---

## Superset (Port 8188)

| Field | Value |
|-------|-------|
| URL | http://localhost:8188 |
| Admin user | `admin` |
| Admin password | `admin` |
| Config path | `C:\Superset\superset_config.py` |

---

## Web Frontend

| Field | Value |
|-------|-------|
| URL | http://localhost:5281 |
| Login (dev bypass) | Fixed credentials via `ACCOMPLISH_TEST_LOGIN=1` in daemon `.env` |

---

## Daemon (Port 9334)

| Field | Value |
|-------|-------|
| URL | http://localhost:9334 |
| Data dir | `~/.accomplish-bullmquote` |

---

## Bifrost MCP Gateway (Port 8010)

External dependency — started separately, not managed by `manage_backend.py`.

| Field | Value |
|-------|-------|
| Health | http://localhost:8010/health |

---

## Temporal Workflow Server (Port 7233)

External dependency — started separately.

| Field | Value |
|-------|-------|
| gRPC | localhost:7233 |
| UI | http://localhost:8233 (if UI is enabled) |

---

## Ollama LLM (Port 11434)

| Field | Value |
|-------|-------|
| API | http://localhost:11434 |
| Model used | `qwen3:8b` (RFQ chat synthesis) |

---

## RFQ Memory Service (Port 8108)

| Field | Value |
|-------|-------|
| Chat URL | http://100.121.36.255:8108 |
| Ingest URL | http://127.0.0.1:8109 (loopback only) |
| Auth | JWT, secret in `fastapi-router/.env` as `JWT_SECRET` |

---

## Service Port Map

| Service | Port | Health URL |
|---------|------|-----------|
| upload_server | 3100 | http://127.0.0.1:3100/docs |
| fastapi_router | 5100 | http://127.0.0.1:5100/docs |
| hitl_router | 5102 | http://127.0.0.1:5102/docs |
| reporting_mcp_server | 8105 | http://100.121.36.255:8105/ |
| intake_mcp_server | 8002 | http://100.121.36.255:8002/ |
| distributor_pricing_mcp_server | 8003 | http://100.121.36.255:8003/ |
| gerber_integration_mcp_server | 8007 | http://100.121.36.255:8007/ |
| bom_qa_lookup_server | 8106 | http://100.121.36.255:8106/ |
| rfq_memory_server | 8108 | http://100.121.36.255:8108/health |
| python_bridge | 3110 | http://100.121.36.255:3110/docs |
| web_frontend | 5281 | http://100.121.36.255:5281/ |
| superset | 8188 | http://127.0.0.1:8188/health |
| daemon | 9334 | http://localhost:9334/health |

---

## How to Start Everything

```powershell
cd C:\CAM[3.4]-RFQ_centum\CAM-Source\fastapi-router
python manage_backend.py start
python manage_backend.py status
```

## How to Stop Everything

```powershell
cd C:\CAM[3.4]-RFQ_centum\CAM-Source\fastapi-router
python manage_backend.py stop
```
