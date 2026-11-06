import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.db_config import DB_PATH  # noqa: E402

# ---------------------------------------------------------------------------
# MCP gateway (gerber-integration only) -- Bifrost, replacing MCP Jungle.
# endpoint_slug is an independently-registered Bifrost value, not derivable
# from the client name -- see fastmcp-router/config.py's own
# BIFROST_ENDPOINT_SLUGS comment for why this must be an explicit table,
# not a transform.
# ---------------------------------------------------------------------------
BIFROST_URL = "http://localhost:8010"
BIFROST_ENDPOINT_SLUGS = {
    "intake": "intake",
    "gerber_integration": "gerber-integration",
    "distributor": "distributor",
    "Production_Logic_DB": "production-postgres-db",
    "Production_FileMetedata_DB": "production-filemetedata-db",
}
