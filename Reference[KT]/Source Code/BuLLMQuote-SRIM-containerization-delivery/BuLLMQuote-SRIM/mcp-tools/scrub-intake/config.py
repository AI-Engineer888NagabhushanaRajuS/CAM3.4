"""Single configuration point for tool_calling.py's connection to the MCP Jungle
gateway. MCP Jungle's dashboard/REST management API is confirmed reachable at
http://localhost:8080 this session; its MCP protocol endpoint is the same host,
path /mcp.
"""

import os

MCP_JUNGLE_URL = os.environ.get("MCP_JUNGLE_URL", "http://localhost:8080/mcp")
