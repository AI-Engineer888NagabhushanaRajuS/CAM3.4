"""AST-based manifest generator: reads each mcp_server.py and extracts @mcp.tool()-decorated
functions to regenerate the tools[] array in manifests/*.json.

Usage:
    python scripts/generate_manifests.py [--dry-run]

Reads manifests/ to find which mcp_server file each manifest points to, then updates the
tools[] array in-place (preserving all other manifest fields).
"""

import ast
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MANIFESTS_DIR = REPO_ROOT / "manifests"


def extract_mcp_tools(filepath: pathlib.Path) -> list:
    """Parse a Python file and extract all @mcp.tool-decorated functions."""
    src = filepath.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        print(f"  WARNING: SyntaxError parsing {filepath}: {e}", file=sys.stderr)
        return []

    tools = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if _is_mcp_tool_decorator(dec):
                docstring = (ast.get_docstring(node) or "").strip()
                # First 200 chars of docstring as description
                description = docstring[:200].replace("\n", " ") if docstring else ""
                inputs = {}
                for arg in node.args.args:
                    if arg.arg in ("self", "cls"):
                        continue
                    ann = _annotation_to_str(arg.annotation) if arg.annotation else "any"
                    inputs[arg.arg] = ann
                tools.append({
                    "name": node.name,
                    "description": description,
                    "inputs": inputs,
                    "outputs": {"result": "object"},  # conservative default
                })
                break
    return tools


def _is_mcp_tool_decorator(dec) -> bool:
    if isinstance(dec, ast.Attribute) and dec.attr == "tool":
        return True
    if isinstance(dec, ast.Call):
        func = dec.func
        if isinstance(func, ast.Attribute) and func.attr == "tool":
            return True
        if isinstance(func, ast.Name) and func.id == "tool":
            return True
    return False


def _annotation_to_str(ann) -> str:
    if ann is None:
        return "any"
    if isinstance(ann, ast.Name):
        return ann.id
    if isinstance(ann, ast.Constant):
        return str(ann.value)
    if isinstance(ann, ast.Subscript):
        return ast.unparse(ann) if hasattr(ast, "unparse") else "object"
    return "any"


def run(dry_run=False):
    manifests = sorted(MANIFESTS_DIR.glob("*.json"))
    if not manifests:
        print("No manifests found in", MANIFESTS_DIR)
        return 1

    any_changed = False
    for mf_path in manifests:
        manifest = json.loads(mf_path.read_text(encoding="utf-8"))
        server_rel = manifest.get("mcp_server")
        if not server_rel:
            print(f"  SKIP {mf_path.name}: no mcp_server field")
            continue

        server_path = REPO_ROOT / server_rel
        if not server_path.exists():
            print(f"  WARN {mf_path.name}: mcp_server not found: {server_path}")
            continue

        discovered = extract_mcp_tools(server_path)
        if not discovered:
            print(f"  WARN {mf_path.name}: no @mcp.tool functions found in {server_rel}")
            continue

        # Merge: keep existing tool entries' inputs/outputs if they exist, add new ones
        existing = {t["name"]: t for t in manifest.get("tools", [])}
        module_id = manifest["id"]
        merged = []
        for t in discovered:
            tool_name = f"{module_id}__{t['name']}"
            entry = dict(existing.get(tool_name, {}))
            entry["name"] = tool_name
            if t["description"]:
                entry["description"] = t["description"]
            if "inputs" not in entry:
                entry["inputs"] = t["inputs"]
            if "outputs" not in entry:
                entry["outputs"] = t["outputs"]
            merged.append(entry)

        manifest["tools"] = merged
        new_text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
        old_text = mf_path.read_text(encoding="utf-8")
        if new_text != old_text:
            any_changed = True
            if dry_run:
                print(f"  DRY-RUN would update: {mf_path.name} ({len(merged)} tools)")
            else:
                mf_path.write_text(new_text, encoding="utf-8")
                print(f"  Updated {mf_path.name} ({len(merged)} tools)")
        else:
            print(f"  OK {mf_path.name} (no changes, {len(merged)} tools)")

    return 0


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    sys.exit(run(dry_run=dry))
