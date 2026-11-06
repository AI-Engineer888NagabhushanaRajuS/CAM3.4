#!/bin/sh
# Reproduces Centum/BuLLMQuote-SRIM's own 2 MCP Jungle server registrations on
# a fresh MCP Jungle instance. Does NOT include the other 11 servers visible
# on this machine's shared gateway (postgres_logic/_metadata and their _2
# duplicates, feasibility, cbom, Pydantic, nuitka_test, gerber_integration,
# intake, distributor) -- those belong to other projects/tenants sharing this
# host's gateway and are out of scope for Centum's own reproducible config.
# Neither of Centum's 2 servers carries an embedded credential -- both are
# plain streamable_http URLs, confirmed via `mcpjungle list servers` this
# session (not re-extracted from the gateway's own config export, which also
# contains OTHER servers' live DATABASE_URI credentials and was deliberately
# not copied out of the container for that reason).
#
# Usage: ./register-centum-servers.sh [registry-url]
#   Defaults to http://127.0.0.1:8080 if no registry URL is given --
#   point this at a NEW MCP Jungle instance's registry, not the shared one.

REGISTRY="${1:-http://127.0.0.1:8080}"

mcpjungle --registry "$REGISTRY" register \
  --name centum_reporting \
  --transport streamable_http \
  --url "http://CENTUM_REPORTING_HOST:8105/mcp"
  # Port corrected to the real bound port (8105), not the stale 8005
  # registration found on the shared gateway -- see docs/FINDINGS-AND-FIXES.md.
  # Replace CENTUM_REPORTING_HOST with wherever reporting_mcp_server actually
  # runs relative to this new MCP Jungle instance (a k8s Service DNS name once
  # containerized, e.g. "reporting-mcp-server.centum.svc.cluster.local").

mcpjungle --registry "$REGISTRY" register \
  --name centum_intake \
  --transport streamable_http \
  --url "http://CENTUM_INTAKE_HOST:8004/mcp"
  # This is scrub_mcp_server's registered name/port on the shared gateway --
  # see docs/SYSTEM-AND-TECH-STACK.md. Replace CENTUM_INTAKE_HOST the same way.

echo "Registered centum_reporting and centum_intake against $REGISTRY."
echo "Run 'mcpjungle --registry $REGISTRY list servers' to confirm."
