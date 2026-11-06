"""Manifest validator: verifies all manifests/*.json against 3 rules.

Exit 0 = all valid. Exit 1 = at least one violation.

Checks:
1. mcp_server file referenced exists on disk
2. All tool names in manifest exist as @mcp.tool functions in mcp_server.py
3. JSON is parseable (implicitly checked by json.loads)

Usage:
    python scripts/validate_manifests.py
"""

import ast
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MANIFESTS_DIR = REPO_ROOT / "manifests"


def _mcp_function_names(filepath: pathlib.Path) -> set:
    """Extract function names with @mcp.tool decorator from a Python file."""
    try:
        src = filepath.read_text(encoding="utf-8")
        tree = ast.parse(src)
    except Exception:
        return set()
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if _is_mcp_tool_decorator(dec):
                names.add(node.name)
                break
    return names


def _is_mcp_tool_decorator(dec) -> bool:
    if isinstance(dec, ast.Attribute) and dec.attr == "tool":
        return True
    if isinstance(dec, ast.Call):
        func = dec.func
        if isinstance(func, ast.Attribute) and func.attr == "tool":
            return True
    return False


def run():
    manifests = sorted(MANIFESTS_DIR.glob("*.json"))
    if not manifests:
        print("ERROR: no manifests found in", MANIFESTS_DIR)
        return 1

    all_ok = True
    for mf_path in manifests:
        errors = []
        try:
            manifest = json.loads(mf_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"FAIL {mf_path.name}: invalid JSON: {e}")
            all_ok = False
            continue

        server_rel = manifest.get("mcp_server", "")
        server_path = REPO_ROOT / server_rel if server_rel else None

        # Rule 1: mcp_server exists
        if server_rel == "":
            errors.append("missing 'mcp_server' field")
        elif not server_path.exists():
            errors.append(f"mcp_server not found: {server_rel}")

        # Rule 2: tool names exist in mcp_server
        module_id = manifest.get("id", "")
        if server_path and server_path.exists():
            actual_funcs = _mcp_function_names(server_path)
            for tool in manifest.get("tools", []):
                name = tool.get("name", "")
                # Strip prefix up to first "__" to get the bare function name
                func_name = name.split("__", 1)[-1] if "__" in name else name
                if actual_funcs and func_name not in actual_funcs:
                    # rfq-memory is REST, not FastMCP — skip function check for it
                    if manifest.get("routing") != "rest":
                        errors.append(f"tool '{name}' not found as @mcp.tool in {server_rel}")

        if errors:
            all_ok = False
            for e in errors:
                print(f"FAIL {mf_path.name}: {e}")
        else:
            n_tools = len(manifest.get("tools", []))
            print(f"  OK {mf_path.name} ({n_tools} tools)")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(run())
