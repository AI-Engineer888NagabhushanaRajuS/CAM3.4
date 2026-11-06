"""
Validate all manifests in manifests/ against three rules:
  1. JSON is valid and has required fields (id, name, version, mcp_server, tools)
  2. The mcp_server file referenced by each manifest exists on disk
  3. Every tool name declared in the manifest exists as a function in the mcp_server.py
     (AST check, same logic as generate_manifests.py)

Exit 0 if all manifests pass; exit 1 and print failures otherwise.

Usage:
    python scripts/validate_manifests.py
"""

import ast
import json
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MANIFESTS_DIR = os.path.join(_REPO_ROOT, "manifests")

REQUIRED_FIELDS = {"id", "name", "version", "mcp_server", "tools"}


def _extract_function_names(filepath):
    """Return the set of function names decorated with @mcp.tool() in a Python file."""
    try:
        with open(filepath, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=filepath)
    except (OSError, SyntaxError):
        return None

    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if "tool" in ast.dump(decorator):
                names.add(node.name)
                break
    return names


def validate_manifest(manifest_path):
    """Return list of error strings; empty list means the manifest is valid."""
    errors = []
    rel = os.path.relpath(manifest_path, _REPO_ROOT)

    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return [f"{rel}: invalid JSON — {e}"]

    missing = REQUIRED_FIELDS - manifest.keys()
    if missing:
        errors.append(f"{rel}: missing required fields: {sorted(missing)}")

    server_rel = manifest.get("mcp_server", "")
    server_abs = os.path.join(_REPO_ROOT, server_rel)
    if not os.path.exists(server_abs):
        errors.append(f"{rel}: mcp_server not found: {server_rel}")
        return errors  # can't do tool check without the file

    declared_tool_names = {t["name"] for t in manifest.get("tools", [])}
    if not declared_tool_names:
        return errors

    # Strip the service prefix (everything before __) to get the raw function name
    raw_to_full = {}
    for full in declared_tool_names:
        raw = full.split("__", 1)[-1] if "__" in full else full
        raw_to_full[raw] = full

    actual_fn_names = _extract_function_names(server_abs)
    if actual_fn_names is None:
        errors.append(f"{rel}: could not parse {server_rel}")
        return errors

    for raw, full in raw_to_full.items():
        if raw not in actual_fn_names and full not in actual_fn_names:
            errors.append(
                f"{rel}: tool '{full}' (function '{raw}') not found in {server_rel}"
            )

    return errors


def main():
    if not os.path.isdir(_MANIFESTS_DIR):
        print(f"ERROR: manifests/ directory not found at {_MANIFESTS_DIR}", file=sys.stderr)
        sys.exit(1)

    manifests = sorted(
        os.path.join(_MANIFESTS_DIR, f)
        for f in os.listdir(_MANIFESTS_DIR)
        if f.endswith(".json")
    )

    if not manifests:
        print("No manifests found.", file=sys.stderr)
        sys.exit(1)

    all_errors = []
    for path in manifests:
        errs = validate_manifest(path)
        all_errors.extend(errs)
        status = "PASS" if not errs else f"FAIL ({len(errs)} error(s))"
        rel = os.path.relpath(path, _REPO_ROOT)
        print(f"  [{status}] {rel}")
        for e in errs:
            print(f"        {e}")

    print()
    if all_errors:
        print(f"FAILED: {len(all_errors)} error(s) across {len(manifests)} manifests")
        sys.exit(1)
    else:
        print(f"OK: all {len(manifests)} manifests valid")
        sys.exit(0)


if __name__ == "__main__":
    main()
