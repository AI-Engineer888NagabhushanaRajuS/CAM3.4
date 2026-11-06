import itertools
import json
import requests
from config import MCP_JUNGLE_URL

# Monotonically increasing request IDs — safe for concurrent calls.
_request_id = itertools.count(1)


def create_session():
    """
    Initializes a persistent session with the MCP Jungle gateway,
    negotiating capabilities and completing the full protocol handshake.
    """
    session = requests.Session()

    session.headers.update({
        "Content-Type": "application/json",
        "MCP-Protocol-Version": "2025-11-25"
    })

    # Step 1: Send the initialize request with full multi-server capabilities
    init_payload = {
        "jsonrpc": "2.0",
        "id": next(_request_id),
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {
                "roots": {
                    "listChanged": True
                },
                "sampling": {}
            },
            "clientInfo": {
                "name": "python-tool-client",
                "version": "1.0.0"
            }
        }
    }

    response = session.post(
        MCP_JUNGLE_URL,
        json=init_payload,
        timeout=30
    )
    response.raise_for_status()

    # Extract and persist the Session ID assigned by the gateway
    session_id = response.headers.get("Mcp-Session-Id")
    if session_id:
        session.headers["Mcp-Session-Id"] = session_id

    # Step 2: Send the mandatory 'initialized' notification to finalize the handshake.
    # Without this, the gateway will not attach external server tools to this session.
    initialized_notification = {
        "jsonrpc": "2.0",
        "method": "notifications/initialized"
    }
    session.post(
        MCP_JUNGLE_URL,
        json=initialized_notification,
        timeout=30
    )

    return session


def list_tools(session):
    payload = {
        "jsonrpc": "2.0",
        "id": next(_request_id),
        "method": "tools/list",
        "params": {
            "server_id": "postgres-mcp"  # Tells the gateway to fetch tools from this specific SSE server
        }
    }
    response = session.post(MCP_JUNGLE_URL, json=payload, timeout=30)
    return response.json()


def call_tool(session, tool_name, arguments):
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
    response = session.post(MCP_JUNGLE_URL, json=payload, timeout=300)
    return response.json()


if __name__ == "__main__":
    # Create the authenticated gateway connection
    session = create_session()

    print("\n=== AVAILABLE TOOLS ===")
    tools = list_tools(session)
    print(json.dumps(tools, indent=2))
