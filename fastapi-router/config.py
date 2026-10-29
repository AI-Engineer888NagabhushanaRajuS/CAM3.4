"""Single configuration point for tool_calling.py's connection to the Bifrost
MCP gateway (replaces MCP Jungle for RFQ_Flow -- Standard_BOM_Flow still uses
MCP Jungle directly, unmigrated, since its own scrub_mcp_server tools aren't
registered in Bifrost yet). Bifrost's management API (client/tool listing,
basic-auth-protected) is confirmed reachable at http://localhost:8010 this
session; tool EXECUTION is a separate, unauthenticated, per-client endpoint
at {BIFROST_URL}/mcp/{endpoint_slug} -- see tool_calling.py's own docstring
for why (Bifrost is stateless, no MCP Jungle-style session handshake needed).
"""

import os

BIFROST_URL = os.environ.get("BIFROST_URL", "http://localhost:8010")

# Bifrost's endpoint_slug is an independently-registered value, NOT a
# derivable transform of the client name (e.g. "Production_Logic_DB" ->
# "production-postgres-db" -- confirmed empirically via Bifrost's own
# /api/mcp/clients, not guessed). Must be an explicit lookup table.
BIFROST_ENDPOINT_SLUGS = {
    "intake": "intake",
    "gerber_integration": "gerber-integration",
    "distributor": "distributor",
    "Production_Logic_DB": "production-postgres-db",
    "Production_FileMetedata_DB": "production-filemetedata-db",
}
