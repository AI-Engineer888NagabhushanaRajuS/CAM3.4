"""reporting_module -- self-contained CBOM/16-report generation + Excel export engine.

Supports two usage modes:

1. Standalone (this is how it's used today): `python mcp_server.py` from inside this
   folder, or point an MCP-compatible client at it as a stdio server.
2. Imported as a package from a consuming application: `import reporting_module` (with
   this folder's PARENT directory on sys.path) gives you `reporting_module.cbom` /
   `reporting_module.generate_reports` / `reporting_module.export_reports` directly,
   without needing to launch a separate MCP server process.

Both modes resolve internal imports the same way -- this file adds its own directory to
sys.path (idempotently) before importing the public functions, exactly like mcp_server.py
does for itself.
"""

import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import exporter  # noqa: E402
import reporting_pipeline  # noqa: E402
from logging_utils import logger  # noqa: E402

__all__ = ["cbom", "generate_reports", "export_reports"]


def cbom(rfq_id: str) -> dict:
    """Same contract as the `cbom` MCP tool (see mcp_server.py) -- returns a result dict
    on both success and failure, never raises.
    """
    try:
        return reporting_pipeline.run_cbom(rfq_id)
    except Exception as e:
        logger.exception(f"cbom failed for rfq_id={rfq_id!r}")
        return {"status": "failed", "rfq_id": rfq_id, "error": str(e)}


def generate_reports(rfq_id: str) -> dict:
    """Same contract as the `generate_reports` MCP tool (see mcp_server.py) -- returns a
    result dict on both success and failure, never raises, so it's a drop-in substitute
    for a consuming application that wants to call this in-process instead of over MCP.
    """
    try:
        return reporting_pipeline.run_pipeline(rfq_id)
    except Exception as e:
        logger.exception(f"generate_reports failed for rfq_id={rfq_id!r}")
        return {"status": "failed", "rfq_id": rfq_id, "error": str(e)}


def export_reports(rfq_id: str) -> dict:
    """Same contract as the `export_reports` MCP tool (see mcp_server.py)."""
    try:
        return exporter.export_excel(rfq_id)
    except Exception as e:
        logger.exception(f"export_reports failed for rfq_id={rfq_id!r}")
        return {"status": "failed", "rfq_id": rfq_id, "error": str(e)}
