# CAM 3.4 ISATVON Manifests

One manifest per FastMCP service. Machine-readable capability declarations used by:
- `fastapi_router.py` to load `DUCKDB_SCOPED_TOOLS` and `SCRUB_TOOLS` at startup
- `scripts/validate_manifests.py` for CI verification

## Format

Each manifest is JSON conforming to `https://digibull.ai/cam/manifest/v1`:

| Field | Required | Description |
|-------|----------|-------------|
| `id` | yes | Unique service identifier (used as MCP Jungle registration name prefix) |
| `name` | yes | Human-readable service name |
| `version` | yes | Semver version |
| `mcp_server` | yes | Relative path from repo root to the mcp_server.py file |
| `fastmcp_name` | yes | Name passed to `FastMCP(...)` constructor |
| `port` | yes | Port the service runs on |
| `tools[]` | yes | List of tool descriptors (name, description, inputs, outputs) |
| `duckdb_scoped_tools` | no | Tool names that require special DuckDB routing in fastapi_router.py |
| `scrub_tools` | no | Tool names for scrub-intake routing path |
| `routing_profile` | no | Which Dify/Temporal workflow this service participates in |
| `dependencies` | no | Runtime dependencies: `postgresql:<db>`, `duckdb:<file>` |
| `hitl_gate` | no | Boolean on a tool descriptor — marks HITL pause points |

## Services

| Manifest | FastMCP Name | Port | Tools |
|----------|-------------|------|-------|
| `centum_reporting.json` | cbom-reporting | 8105 | 7 (incl. validate_reports) |
| `centum_scrub_intake.json` | ScrubIntake | 8004 | 4 |
| `centum_intake.json` | Intake | 8002 | 2 |
| `centum_distributor_pricing.json` | DistributorPricing | 8003 | 5 |
| `centum_gerber_integration.json` | Gerber-Integration | 8007 | 1 |
| `centum_rfq_memory.json` | rfq-memory | 8008 | 2 (planned) |

## Usage

```bash
# Validate all manifests
python scripts/validate_manifests.py

# Regenerate tool lists from mcp_server.py AST
python scripts/generate_manifests.py
```
