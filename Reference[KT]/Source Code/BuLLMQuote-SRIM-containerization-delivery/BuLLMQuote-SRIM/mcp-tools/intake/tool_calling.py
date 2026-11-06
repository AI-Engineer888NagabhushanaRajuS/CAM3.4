import itertools
import requests
from config import BIFROST_URL, BIFROST_ENDPOINT_SLUGS

# Monotonically increasing request IDs — safe for concurrent calls.
_request_id = itertools.count(1)

# Bifrost has no MCP Jungle-style session/handshake concept at all --
# confirmed empirically: a bare `tools/call` POST with no prior `initialize`
# request already reaches the real tool and returns its real response.
# create_session()/notifications-initialized handshake is therefore gone,
# not just unused -- there is nothing on the Bifrost side to initialize.


def _endpoint_url(tool_name):
    """tool_name is `<client>-<tool>` (Bifrost's own naming). Splitting on
    the FIRST '-' is safe/unambiguous: no registered client name contains a
    literal '-', only '_'. endpoint_slug is looked up, not derived -- see
    config.py's own BIFROST_ENDPOINT_SLUGS comment."""
    client, _, _ = tool_name.partition("-")
    endpoint_slug = BIFROST_ENDPOINT_SLUGS.get(client)
    if not endpoint_slug:
        raise ValueError(
            f"No Bifrost endpoint_slug registered for client '{client}' "
            f"(parsed from tool_name '{tool_name}'). Known clients: "
            f"{sorted(BIFROST_ENDPOINT_SLUGS)}"
        )
    return f"{BIFROST_URL}/mcp/{endpoint_slug}"


def list_tools(tool_name_prefix_client):
    """Debug helper -- lists every tool registered under one Bifrost client.
    Only used by this file's own __main__ block below."""
    url = f"{BIFROST_URL}/mcp/{BIFROST_ENDPOINT_SLUGS[tool_name_prefix_client]}"
    payload = {
        "jsonrpc": "2.0",
        "id": next(_request_id),
        "method": "tools/list",
        "params": {},
    }
    response = requests.post(url, json=payload, timeout=30)
    return response.json()


def call_tool(tool_name, arguments):
    payload = {
        "jsonrpc": "2.0",
        "id": next(_request_id),
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments,
        }
    }

    response = requests.post(_endpoint_url(tool_name), json=payload, timeout=30)
    return response.json()


if __name__ == "__main__":
    import json

    print("\n=== AVAILABLE TOOLS (intake) ===")
    print(json.dumps(list_tools("intake"), indent=2))
