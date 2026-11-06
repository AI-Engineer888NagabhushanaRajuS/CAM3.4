# ISATVON Manifests — CAM 3.4

One JSON manifest per FastMCP tool module. Machine-readable capability descriptions that drive `fastapi_router.py`'s tool routing sets without hardcoding.

## Format

```json
{
  "$schema": "https://digibull.ai/cam/manifest/v1",
  "id": "centum_reporting",
  "name": "...",
  "version": "3.4.0",
  "description": "...",
  "mcp_server": "relative/path/to/mcp_server.py",
  "port": 8105,
  "routing": "bifrost|jungle|rest",
  "tools": [{"name": "...", "description": "...", "inputs": {}, "outputs": {}}],
  "routing_profile": "Standard_BOM_Flow|RFQ_Assistant",
  "dependencies": ["postgresql:...", "duckdb:...", "cognee:..."]
}
```

## Tool name convention

`{module_id}__{function_name}` — two underscores separate the module from the function.

## Dependency keys

| Key | Meaning |
|-----|---------|
| `duckdb:cbom.duckdb` | reads/writes cbom.duckdb — must hold DUCKDB file lock |
| `duckdb:reports.duckdb` | reads/writes reports.duckdb |
| `duckdb:input_db.duckdb` | reads input_db.duckdb (READ_ONLY) |
| `postgresql:logic_db` | reads logic_db (currency rates, skills registry) |
| `postgresql:file_metadata_db` | reads file_metadata_db (upload telemetry) |
| `cognee:graph_store` | reads/writes cognee knowledge graph |

## Scripts

- `scripts/generate_manifests.py` — AST-based tool extractor; regenerates `tools[]` from source
- `scripts/validate_manifests.py` — validates all manifests (run in CI)
