"""
Auto-discover @mcp.tool() functions from FastMCP server files and print a
tool-list JSON fragment for inclusion in the corresponding manifest.

Usage:
    python scripts/generate_manifests.py [mcp_server.py ...]

If no paths are given, scans the known server files relative to repo root.
Writes discovered tool stubs to stdout — paste into the manifest's "tools"
array and fill in the TODO fields manually.
"""

import ast
import json
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_SERVER_FILES = [
    "mcp-tools/reporting/superset/mcp_server.py",
    "mcp-tools/scrub-intake/scrub_mcp_server.py",
    "mcp-tools/intake/mcp_server.py",
    "mcp-tools/distributor-pricing/mcp_server.py",
    "mcp-tools/gerber-integration/mcp_server.py",
    "mcp-tools/rfq-memory/memory_service.py",
]


def extract_mcp_tools(filepath):
    """Parse a Python file and extract all @mcp.tool()-decorated functions."""
    with open(filepath, encoding="utf-8") as f:
        source = f.read()

    try:
        tree = ast.parse(source, filename=filepath)
    except SyntaxError as e:
        print(f"  PARSE ERROR: {e}", file=sys.stderr)
        return []

    tools = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        is_mcp_tool = False
        for decorator in node.decorator_list:
            dump = ast.dump(decorator)
            if "tool" in dump and ("mcp" in dump or "tool" in dump):
                is_mcp_tool = True
                break
        if not is_mcp_tool:
            continue

        docstring = ast.get_docstring(node) or ""
        params = {}
        for arg in node.args.args:
            if arg.arg in ("self", "ctx"):
                continue
            annotation = "string"
            if arg.annotation:
                try:
                    annotation = ast.unparse(arg.annotation)
                except Exception:
                    annotation = "string"
            params[arg.arg] = annotation

        tools.append({
            "name": node.name,
            "description": docstring[:200].replace("\n", " ").strip(),
            "inputs": params,
            "outputs": {"TODO": "fill in from docstring"},
        })
    return tools


def main():
    paths = sys.argv[1:] if len(sys.argv) > 1 else [
        os.path.join(_REPO_ROOT, p) for p in _SERVER_FILES
    ]

    for path in paths:
        rel = os.path.relpath(path, _REPO_ROOT)
        print(f"\n# {rel}")
        if not os.path.exists(path):
            print(f"  MISSING: {path}")
            continue
        tools = extract_mcp_tools(path)
        if not tools:
            print("  (no @mcp.tool() functions found)")
            continue
        print(json.dumps(tools, indent=2))


if __name__ == "__main__":
    main()
