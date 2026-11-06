# SPEC-003: Manifest-Code Alignment (1 Manifest Per FastMCP Tool)

**Status:** COMPLETED  
**Branch:** `feat/spec-003-manifest-alignment`  
**Commit target:** `feat: align ISATVON manifests with actual FastMCP tools (1:1 mapping)`  
**Depends on:** SPEC-001

## Context

The system has 6 FastMCP tool modules (reporting + scrub-intake + intake + distributor-pricing +
gerber-integration + rfq-memory). The ISATVON 1.5 draft says "one manifest per tool" but currently:
- Docs describe the flow in prose
- No machine-readable manifest per FastMCP server exists
- The skills registry in PostgreSQL (`quote_routing_profiles`) contains routing sequences but
  not the tool capability descriptions

The ISATVON manifest format (from the architecture docs) is JSON with fields:
`id`, `name`, `version`, `description`, `tools[]`, `routing_profile`, `inputs`, `outputs`.

## What to Build

### 1. Create `manifests/` directory at repo root

```
manifests/
  centum_reporting.json         # reporting_module (mcp_server.py :8105)
  centum_intake.json            # intake/mcp_server.py (:8002 equivalent)
  centum_scrub_intake.json      # scrub-intake/scrub_mcp_server.py
  centum_distributor_pricing.json  # distributor-pricing/mcp_server.py (:8003)
  centum_gerber_integration.json   # gerber-integration/mcp_server.py (:8007)
  centum_rfq_memory.json        # rfq-memory/memory_service.py
  README.md                     # explains the manifest format
```

### 2. Manifest format (JSON Schema)

Each manifest must conform to:
```json
{
  "$schema": "https://digibull.ai/cam/manifest/v1",
  "id": "centum_reporting",
  "name": "Centum Reporting Module",
  "version": "3.4.0",
  "description": "Generates all 16 CBOM report tabs for one RFQ",
  "mcp_server": "mcp-tools/reporting/superset/mcp_server.py",
  "port": 8105,
  "tools": [
    {
      "name": "centum_reporting__cbom",
      "description": "Generate CBOM table from scrub BOM + QW awards data",
      "inputs": {"rfq_id": "string"},
      "outputs": {"cbom_rows": "integer", "issues": "array"}
    },
    {
      "name": "centum_reporting__generate_reports",
      "description": "Generate all 16 report tables for an RFQ",
      "inputs": {"rfq_id": "string"},
      "outputs": {"counts": "object", "issues": "array"}
    },
    {
      "name": "centum_reporting__validate_reports",
      "description": "Validate all 16 report tables against business rules",
      "inputs": {"rfq_id": "string"},
      "outputs": {"passed": "integer", "failed": "integer", "details": "array"}
    },
    {
      "name": "centum_reporting__export_reports",
      "description": "Export DuckDB report tables to Excel workbook",
      "inputs": {"rfq_id": "string", "output_path": "string"},
      "outputs": {"file_path": "string", "tab_count": "integer"}
    },
    {
      "name": "centum_reporting__resolve_final_selection",
      "description": "HITL gate: resolve supplier selection conflicts",
      "inputs": {"rfq_id": "string"},
      "outputs": {"conflicts_resolved": "integer"}
    },
    {
      "name": "centum_reporting__enrich_erp",
      "description": "Enrich CBOM with ERP data (InforLN extract)",
      "inputs": {"rfq_id": "string"},
      "outputs": {"enriched_rows": "integer"}
    }
  ],
  "routing_profile": "Standard_BOM_Flow",
  "dependencies": ["postgresql:logic_db", "duckdb:cbom.duckdb", "duckdb:reports.duckdb"]
}
```

### 3. Auto-discover tools from mcp_server.py

Write a script `scripts/generate_manifests.py` that:
- Reads each `mcp_server.py` / `scrub_mcp_server.py`
- Uses Python AST to find all `@mcp.tool()` decorators
- Extracts function name, docstring, parameters (type hints)
- Generates the `tools[]` array automatically
- Writes the manifest JSON (with a TODO comment for fields it can't auto-discover)

```python
# scripts/generate_manifests.py
import ast, json, os, sys

def extract_mcp_tools(filepath):
    """Parse a Python file and extract all @mcp.tool()-decorated functions."""
    with open(filepath) as f:
        tree = ast.parse(f.read())
    tools = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call) and 'tool' in ast.dump(decorator):
                    docstring = ast.get_docstring(node) or ""
                    params = {arg.arg: str(arg.annotation) for arg in node.args.args if arg.arg != 'self'}
                    tools.append({"name": node.name, "description": docstring[:200], "inputs": params})
    return tools
```

### 4. Validate manifests in CI (script)

Create `scripts/validate_manifests.py`:
```python
# For each manifest in manifests/, verify:
# 1. The mcp_server file referenced exists
# 2. All tool names in the manifest exist in the mcp_server.py file
# 3. JSON is valid against the schema
```

### 5. Update `fastapi_router.py` to use manifests

The `DUCKDB_SCOPED_TOOLS` and `SCRUB_TOOLS` sets in `fastapi_router.py` are hardcoded.
Replace them with a manifest-driven loader:

```python
# In fastapi_router.py, add a loader:
import json, pathlib

_MANIFESTS_DIR = pathlib.Path(__file__).parent.parent / "manifests"

def _load_tool_routing_sets():
    """Load tool routing categories from manifests instead of hardcoding."""
    duckdb_tools = set()
    scrub_tools = set()
    for mf in _MANIFESTS_DIR.glob("*.json"):
        manifest = json.loads(mf.read_text())
        if "duckdb:cbom.duckdb" in manifest.get("dependencies", []):
            for tool in manifest.get("tools", []):
                duckdb_tools.add(tool["name"])
        if manifest["id"] == "centum_scrub_intake":
            for tool in manifest.get("tools", []):
                scrub_tools.add(tool["name"])
    return duckdb_tools, scrub_tools

DUCKDB_SCOPED_TOOLS, SCRUB_TOOLS = _load_tool_routing_sets()
```

## Files to Create/Modify

- `manifests/centum_reporting.json` (new)
- `manifests/centum_intake.json` (new)
- `manifests/centum_scrub_intake.json` (new)
- `manifests/centum_distributor_pricing.json` (new)
- `manifests/centum_gerber_integration.json` (new)
- `manifests/centum_rfq_memory.json` (new)
- `manifests/README.md` (new)
- `scripts/generate_manifests.py` (new)
- `scripts/validate_manifests.py` (new)
- `fastapi_router.py` (modify DUCKDB_SCOPED_TOOLS loading)

## Acceptance Criteria

1. `python scripts/validate_manifests.py` exits 0 (all manifests valid)
2. All 6 FastMCP mcp_server.py files have corresponding manifests
3. Every tool in `DUCKDB_SCOPED_TOOLS` is declared in a manifest with `"dependencies": ["duckdb:cbom.duckdb"]`
4. `fastapi_router.py` imports `DUCKDB_SCOPED_TOOLS` from manifest-loader, not hardcoded set
5. `python -c "from fastapi_router import DUCKDB_SCOPED_TOOLS; print(len(DUCKDB_SCOPED_TOOLS))"` prints 6
6. All files committed to `feat/spec-003-manifest-alignment` branch

## How to Find Tool Names

Read these files to discover the actual @mcp.tool() names:
- `mcp-tools/reporting/superset/mcp_server.py` → centum_reporting__* tools
- `mcp-tools/intake/mcp_server.py` → centum_intake__* tools
- `mcp-tools/scrub-intake/scrub_mcp_server.py` → centum_intake__standardize_* tools
- `mcp-tools/distributor-pricing/mcp_server.py` → distributor_pricing__* tools
- `mcp-tools/gerber-integration/mcp_server.py` → gerber__* tools
- `mcp-tools/rfq-memory/memory_service.py` → rfq_memory__* tools (may not be MCP)

The current hardcoded sets in fastapi_router.py are ground truth for what's real now:
```python
DUCKDB_SCOPED_TOOLS = {
    "centum_reporting__cbom", "centum_reporting__enrich_erp",
    "centum_reporting__enrich_costing_sheet", "centum_reporting__resolve_final_selection",
    "centum_reporting__generate_reports", "centum_reporting__export_reports",
}
SCRUB_TOOLS = {
    "centum_intake__standardize_scrub_bom", "centum_intake__standardize_quote_win",
    "centum_intake__standardize_erp", "centum_intake__standardize_costing_sheet",
}
```
