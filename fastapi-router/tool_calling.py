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
    """tool_name is `<client>-<tool>` (Bifrost's own naming, stored verbatim
    in system_skills_registry/quote_routing_profiles -- see the Bifrost
    migration plan). Splitting on the FIRST '-' is safe/unambiguous: none of
    the registered client names (intake, gerber_integration, distributor,
    Production_Logic_DB, Production_FileMetedata_DB) contain a literal '-'
    themselves, only '_'. endpoint_slug is looked up, not derived -- it's an
    independently-registered value in Bifrost (e.g. Production_Logic_DB ->
    production-postgres-db is not a mechanical transform of the client name).
    """
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
    """Debug helper -- lists every tool registered under one Bifrost client
    (e.g. 'intake', 'distributor'). Only used by this file's own __main__
    block below."""
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

    # 30s was too short for LLM-backed tools (e.g. standardize_quote_win on a
    # large file can take well over a minute) -- observed timing out mid-call
    # in practice, silently losing the tool's result. 300s matches the
    # generous timeout the Dify workflow's own HTTP nodes already use for the
    # same calls.
    response = requests.post(_endpoint_url(tool_name), json=payload, timeout=300)
    return response.json()


if __name__ == "__main__":
    import json

    print("\n=== AVAILABLE TOOLS (intake) ===")
    print(json.dumps(list_tools("intake"), indent=2))
