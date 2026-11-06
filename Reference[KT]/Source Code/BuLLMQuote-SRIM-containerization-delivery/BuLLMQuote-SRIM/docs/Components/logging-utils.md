# `logging_utils.py`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum intake\reporting_module\logging_utils.py`
**Naming note:** requested as `logging_utilites.py` — no file with that name exists anywhere in the codebase. The real, single logging helper module is `reporting_module\logging_utils.py`, documented here under its actual name.

## Architecture

```mermaid
flowchart LR
    Importer["Any reporting_module file\n(mcp_server.py, exporter.py,\nreporting_pipeline.py, ...)"] -->|"from logging_utils import logger"| Logger["logger = logging.getLogger('cbom_reporting')\nlevel = INFO"]
    Logger --> Handler["logging.FileHandler\n(added once — 'if not logger.handlers' guard)"]
    Handler --> LogFile[["{config.LOGS_DIR}/report_generation.log"\nformat: '%(asctime)s [%(levelname)s] %(message)s'"]]
```

## What it does

A 17-line module providing **one shared logger** (`"cbom_reporting"`) for the entire `reporting_module` package — every stage (CBOM generation, report generation, export, migrations) logs through this same instance rather than each file creating its own.

```python
logger = logging.getLogger("cbom_reporting")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.FileHandler(os.path.join(config.LOGS_DIR, "report_generation.log"))
    _handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(_handler)
```

- **File handler only — no console handler.** The module's own docstring is explicit about why: "it stays quiet in a consuming application unless that application also attaches its own handler to this same logger name." This is a deliberate library-citizenship choice — `reporting_module` doesn't assume it owns the process's stdout.
- **The `if not logger.handlers` guard** makes the module import-idempotent: since `logging.getLogger(name)` always returns the same singleton for a given name, re-importing this module (or importing it from multiple entry points) never attaches duplicate handlers, which would otherwise cause every log line to be written twice (or more).
- **Log destination:** `{config.LOGS_DIR}/report_generation.log` — `config.LOGS_DIR` is `reporting_module\config.py`'s own path constant, so relocating `reporting_module` without an env override breaks this the same way it breaks the module's DB path resolution (a documented platform-wide caveat).
- **Log level:** `INFO` — fixed, not configurable via environment variable today.

## Dependencies

- **Stdlib:** `logging`, `os`.
- **Local:** `config` (for `config.LOGS_DIR`).

## Who imports it

Only files inside `reporting_module\` import `from logging_utils import logger` — confirmed importers: `mcp_server.py` (see [reporting-mcp-server.md](./reporting-mcp-server.md)), `exporter.py`, `reporting_pipeline.py`. The `centum intake` root (`scrub_mcp_server.py`, `fastapi_router.py`, `manage_backend.py`, etc.) has **no equivalent shared logger module** — those files use plain `print()` statements for their own console/log output (see [scrub-mcp-server.md](./scrub-mcp-server.md)'s execution flow, which prints progress at each stage rather than logging through any shared handler).

## Known caveats / gaps

- Not configurable per-deployment (fixed `INFO` level, fixed filename, fixed formatter) — anyone needing DEBUG-level tracing during a live investigation has to edit this file directly rather than set an environment variable.
- Because there's no console handler, `report_generation.log` is the *only* place these log lines land — if `config.LOGS_DIR` isn't writable (e.g. a permissions issue after a relocation), failures here are silent (the standard library swallows handler-level I/O errors by default) rather than surfacing anywhere visible.
- This module has no equivalent in the live `centum intake` root — logging conventions are not actually uniform across the whole live backend, only within `reporting_module`.

## Related documents

- [Reporting/reporting-module.md](../Reporting/reporting-module.md#logging_utilspy) — canonical entry, cross-referenced against the rest of the reporting pipeline.
- [reporting-mcp-server.md](./reporting-mcp-server.md) — the MCP server that imports this logger to record tool-level exceptions (`logger.exception(...)`).
