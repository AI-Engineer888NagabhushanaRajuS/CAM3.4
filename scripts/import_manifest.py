"""
SPEC-013: manifest importer + registry writer ("Manifest pipeline" diagram, Lane 1 step 3 + the bridge).

    validate (strict shape) -> canonical sha256 -> store in manifests/ -> [register tools in the
    runtime registry, ONE transaction] -> verify -> optional Jungle registration command.

Everything is a dry-run unless --apply. Registry/routing rows are written only for the tools you
name with --register (never "all tools in the manifest": that would put chat/planned tools into a
live routing profile).

Usage:
    python scripts/import_manifest.py NEW.json                         # validate + hash, no writes
    python scripts/import_manifest.py NEW.json --apply                 # + store in manifests/
    python scripts/import_manifest.py NEW.json --register a__x b__y --profile Standard_BOM_Flow
    python scripts/import_manifest.py NEW.json --register a__x --apply --db-env STAGING_LOGIC_DB_URL
    python scripts/import_manifest.py --rollback manifests/_receipts/<file>.json --apply
    python scripts/import_manifest.py NEW.json --jungle-registry http://jungle:8080 --host 10.0.0.5 --apply

Registry schema per Reference[KT] docs/Database/logic-database.md (a past live introspection; not re-verified):
    quote_routing_profiles(profile_id pk, profile_name UNIQUE, routing_sequence jsonb array of tool-name strings, ...)
    system_skills_registry(skill_code PK, skill_index UNIQUE, skill_name, macro_category_name, mcp_tool_name NOT NULL,
                           input_template, requires_llm, is_active, macro_category nullable)
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_manifests as vm  # noqa: E402  (reuse REQUIRED_FIELDS + AST tool discovery)

REPO_ROOT = vm._REPO_ROOT
MANIFESTS_DIR = vm._MANIFESTS_DIR
RECEIPTS_DIR = os.path.join(MANIFESTS_DIR, "_receipts")  # not *.json at manifests/ top level: loaders ignore it

_ID = re.compile(r"^[a-z][a-z0-9_]*$")
_TOOL = re.compile(r"^[a-z][a-z0-9_]*__[a-z][a-z0-9_]*$")
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
_PROFILE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
# system_skills_registry NOT NULL columns without a default (Reference docs/Database/logic-database.md)
_REGISTRY_FIELDS = ("skill_code", "skill_index", "macro_category_name")


# --- validate ---------------------------------------------------------------

def check_shape(manifest, manifests_dir=MANIFESTS_DIR, repo_root=REPO_ROOT):
    """Return a list of error strings for a manifest dict; [] means it is safe to import."""
    if not isinstance(manifest, dict):
        return ["manifest must be a JSON object"]
    missing = (vm.REQUIRED_FIELDS | {"port"}) - manifest.keys()
    if missing:
        return [f"missing required fields: {sorted(missing)}"]

    errors = []
    mid, port, tools = manifest["id"], manifest["port"], manifest["tools"]
    if not (isinstance(mid, str) and _ID.match(mid)):
        errors.append(f"id {mid!r} must match {_ID.pattern}")
    if not (isinstance(manifest["version"], str) and _SEMVER.match(manifest["version"])):
        errors.append(f"version {manifest['version']!r} must be semver x.y.z")
    if not (isinstance(port, int) and not isinstance(port, bool) and 0 < port < 65536):
        errors.append(f"port {port!r} must be an integer 1-65535")
    if not isinstance(tools, list) or (not tools and not manifest.get("planned_tools")):
        return errors + ["tools must be a non-empty list (an empty list is only valid with planned_tools)"]

    names = []
    for t in tools:
        n = t.get("name") if isinstance(t, dict) else None
        if isinstance(n, str) and _TOOL.match(n):
            names.append(n)
        else:
            errors.append(f"tool name {n!r} must match <prefix>__<function> ({_TOOL.pattern})")
    for n in sorted({n for n in names if names.count(n) > 1}):
        errors.append(f"duplicate tool name {n!r}")

    root = os.path.realpath(repo_root)
    server = manifest["mcp_server"]
    path = None if not isinstance(server, str) or os.path.isabs(server) else os.path.realpath(os.path.join(root, server))
    if path is None or os.path.commonpath([path, root]) != root:
        errors.append(f"mcp_server {server!r} must be a relative path inside the repo")
    elif not os.path.isfile(path):
        errors.append(f"mcp_server not found: {server}")
    else:
        fns = vm._extract_function_names(path)
        if fns is None:
            errors.append(f"could not parse {server}")
        else:
            for n in names:
                if n.split("__", 1)[1] not in fns and n not in fns:
                    errors.append(f"tool {n!r} has no @tool function in {server}")

    for fname in sorted(os.listdir(manifests_dir)):  # one manifest per tool, one server per port
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(manifests_dir, fname), encoding="utf-8") as f:
                other = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(other, dict) or other.get("id") == mid:
            continue
        if other.get("port") == port:
            errors.append(f"port {port} already used by manifest {other.get('id')!r}")
        taken = set(names) & {t.get("name") for t in (other.get("tools") or []) if isinstance(t, dict)}
        for n in sorted(taken):
            errors.append(f"tool {n!r} already declared by manifest {other.get('id')!r}")
    return errors


# --- hash + store -----------------------------------------------------------

def canonical_hash(manifest):
    blob = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def store_manifest(manifest, manifests_dir=MANIFESTS_DIR, write=True):
    """Write manifests/<id>.json. status: created | unchanged | updated (compared by canonical hash)."""
    if not _ID.match(str(manifest.get("id", ""))):
        raise ValueError("refusing to store a manifest with an unsafe id")
    path = os.path.join(manifests_dir, manifest["id"] + ".json")
    new, status = canonical_hash(manifest), "created"
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            status = "unchanged" if canonical_hash(json.load(f)) == new else "updated"
    if write and status != "unchanged":
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    return {"id": manifest["id"], "sha256": new, "status": status, "path": path}


# --- registry writer (the bridge) -------------------------------------------

def register_tools(conn, profile, tools, apply=False, receipt_dir=RECEIPTS_DIR):
    """Register tools in system_skills_registry and append them to profile's routing_sequence.

    One transaction under an advisory lock; idempotent (existing rows / sequence entries are left
    alone). skill_code, skill_index and macro_category_name must be on the manifest tool: skill_index is
    globally UNIQUE and inactive skills already occupy the next indexes, so it is never guessed; a taken
    index/code raises.
    apply=False runs the same statements and rolls back, so the plan is exactly what apply would do.
    The receipt is written BEFORE the commit and is what rollback_receipt() consumes.
    """
    if not _PROFILE.match(profile):
        raise ValueError(f"bad profile name {profile!r}")
    tools = list({t["name"]: t for t in tools}.values())
    for t in tools:
        if not _TOOL.match(t["name"]):
            raise ValueError(f"bad tool name {t['name']!r}")
    names = [t["name"] for t in tools]

    with conn:  # commit on success, roll back on any exception
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext('cam_registry_writer'))")
            cur.execute("SELECT routing_sequence FROM quote_routing_profiles WHERE profile_name = %s FOR UPDATE",
                        (profile,))
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"routing profile {profile!r} not found")
            old_seq = list(row[0])
            cur.execute("SELECT mcp_tool_name FROM system_skills_registry WHERE mcp_tool_name = ANY(%s)", (names,))
            have = {r[0] for r in cur.fetchall()}

            seq, added_registry = list(old_seq), []
            for t in tools:
                name = t["name"]
                if name not in have:
                    missing = [k for k in _REGISTRY_FIELDS if t.get(k) in (None, "")]
                    if missing:
                        raise ValueError(f"{name}: the registry needs {missing} on the manifest tool")
                    idx = t["skill_index"]
                    if not isinstance(idx, int) or isinstance(idx, bool):
                        raise ValueError(f"{name}: skill_index must be an integer, got {idx!r}")
                    cur.execute("SELECT 1 FROM system_skills_registry WHERE skill_index = %s OR skill_code = %s",
                                (idx, t["skill_code"]))
                    if cur.fetchone():
                        raise ValueError(f"{name}: skill_index {idx} or skill_code {t['skill_code']!r} is already "
                                         "used; resolve manually")
                    skill_name = t.get("skill_name") or (t.get("description") or name).split(".")[0].strip()[:80] or name
                    cur.execute(
                        "INSERT INTO system_skills_registry (skill_code, skill_index, skill_name, macro_category_name, "
                        "mcp_tool_name, macro_category, requires_llm) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (t["skill_code"], idx, skill_name, t["macro_category_name"], name,
                         t.get("macro_category"), bool(t.get("requires_llm", False))))
                    added_registry.append(name)
                if name not in seq:
                    seq.append(name)

            added_seq = seq[len(old_seq):]
            if added_seq:
                cur.execute("UPDATE quote_routing_profiles SET routing_sequence = %s::jsonb, updated_at = CURRENT_TIMESTAMP "
                            "WHERE profile_name = %s", (json.dumps(seq), profile))
            receipt = {
                "profile": profile, "previous_routing_sequence": old_seq,
                "added_registry": added_registry, "added_to_sequence": added_seq,
                "changed": bool(added_registry or added_seq), "dry_run": not apply,
            }
            if apply and receipt["changed"]:
                os.makedirs(receipt_dir, exist_ok=True)
                receipt["receipt_file"] = os.path.join(receipt_dir, f"{profile}-{int(time.time() * 1000)}.json")
                with open(receipt["receipt_file"], "w", encoding="utf-8") as f:
                    json.dump(receipt, f, indent=2)
            if not apply:
                conn.rollback()
    return receipt


def rollback_receipt(conn, receipt):
    """Undo register_tools(): remove exactly what the receipt says was added (idempotent).

    Targeted removal, not "restore previous_routing_sequence": a Skills Settings edit made after
    the apply is kept. The old value stays in the receipt for audit.
    """
    if isinstance(receipt, (str, os.PathLike)):
        with open(receipt, encoding="utf-8") as f:
            receipt = json.load(f)
    with conn, conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtext('cam_registry_writer'))")
        cur.execute("SELECT routing_sequence FROM quote_routing_profiles WHERE profile_name = %s FOR UPDATE",
                    (receipt["profile"],))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"routing profile {receipt['profile']!r} not found")
        seq = [t for t in row[0] if t not in receipt["added_to_sequence"]]
        if seq != row[0]:
            cur.execute("UPDATE quote_routing_profiles SET routing_sequence = %s::jsonb WHERE profile_name = %s",
                        (json.dumps(seq), receipt["profile"]))
        if receipt["added_registry"]:
            # keep rows another profile's sequence still references (this profile's edit is already applied above)
            cur.execute("DELETE FROM system_skills_registry r WHERE r.mcp_tool_name = ANY(%s) AND NOT EXISTS "
                        "(SELECT 1 FROM quote_routing_profiles q WHERE q.routing_sequence ? r.mcp_tool_name)",
                        (receipt["added_registry"],))


def verify_registration(conn, profile, names):
    """Read-back check (the 3.4 'parity in staging' step). Returns problem strings; [] = registered."""
    with conn, conn.cursor() as cur:
        cur.execute("SELECT mcp_tool_name FROM system_skills_registry WHERE mcp_tool_name = ANY(%s)", (list(names),))
        have = {r[0] for r in cur.fetchall()}
        cur.execute("SELECT routing_sequence FROM quote_routing_profiles WHERE profile_name = %s", (profile,))
        row = cur.fetchone()
    if row is None:
        return [f"routing profile {profile!r} not found"]
    problems = []
    for n in names:
        if n not in have:
            problems.append(f"{n}: no system_skills_registry row")
        if n not in row[0]:
            problems.append(f"{n}: not in {profile}.routing_sequence")
    return problems


# --- gateway (Jungle) --------------------------------------------------------

def jungle_register_argv(manifest, registry_url, host):
    """The Jungle registration command (3.3: Reference infra/mcp-jungle/register-centum-servers.sh).

    Jungle names a server by the tool prefix (`<server>__<tool>`), not by the manifest id.
    Version difference: the 3.3 script also passes `--transport streamable_http`; the Jungle build
    installed here (ghcr.io/mcpjungle/mcpjungle:latest-stdio) has no such flag and treats --url as
    streamable HTTP, so it is omitted. Verified by registering scrub + reporting against that build.
    """
    prefixes = {t["name"].split("__", 1)[0] for t in manifest["tools"]}
    if len(prefixes) != 1:
        raise ValueError(f"Jungle needs one server name per server; manifest has prefixes {sorted(prefixes)}")
    return ["mcpjungle", "--registry", registry_url, "register", "--name", prefixes.pop(),
            "--url", f"http://{host}:{manifest['port']}/mcp"]


# --- CLI ----------------------------------------------------------------------

def _connect(env_name):
    import psycopg2
    return psycopg2.connect(os.environ[env_name])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("manifest", nargs="?", help="path to the manifest JSON to import")
    ap.add_argument("--apply", action="store_true", help="persist changes (default: dry-run)")
    ap.add_argument("--register", nargs="+", metavar="TOOL", help="tools to add to the registry + routing profile")
    ap.add_argument("--profile", default="Standard_BOM_Flow")
    ap.add_argument("--db-env", default="LOGIC_DB_URL", help="env var holding the Postgres URL (STAGING_LOGIC_DB_URL for staging)")
    ap.add_argument("--jungle-registry", help="MCP Jungle registry URL; prints (or with --apply runs) the register command")
    ap.add_argument("--host", help="host Jungle should reach the server on (required with --jungle-registry)")
    ap.add_argument("--rollback", metavar="RECEIPT", help="undo a previous --register using its receipt file")
    args = ap.parse_args(argv)
    mode = "APPLY" if args.apply else "DRY-RUN"

    if args.rollback:
        if args.apply:
            conn = _connect(args.db_env)
            try:
                rollback_receipt(conn, args.rollback)
            finally:
                conn.close()
        print(f"[{mode}] rollback {args.rollback}")
        return 0
    if not args.manifest:
        ap.error("manifest path required")

    with open(args.manifest, encoding="utf-8") as f:
        manifest = json.load(f)
    errors = check_shape(manifest)
    if errors:
        print("INVALID:\n  " + "\n  ".join(errors), file=sys.stderr)
        return 1
    stored = store_manifest(manifest, write=False)
    print(f"[{mode}] manifest {stored['id']} {stored['status']} sha256={stored['sha256']}")

    if args.register:
        by_name = {t["name"]: t for t in manifest["tools"]}
        unknown = [n for n in args.register if n not in by_name]
        if unknown:
            print(f"--register names not in the manifest: {unknown}", file=sys.stderr)
            return 1
        conn = _connect(args.db_env)
        try:
            receipt = register_tools(conn, args.profile, [by_name[n] for n in args.register], apply=args.apply)
            print(f"[{mode}] registry +{receipt['added_registry']} sequence +{receipt['added_to_sequence']}")
            if args.apply:
                print("receipt:", receipt.get("receipt_file", "(nothing changed)"))
                problems = verify_registration(conn, args.profile, args.register)
                print("verify:", "OK" if not problems else problems)
                if problems:
                    return 1
        finally:
            conn.close()
    if args.apply:  # manifest last: a failed registry step must not leave a stored-but-unregistered tool
        store_manifest(manifest)

    if args.jungle_registry:
        if not args.host:
            print("--host is required with --jungle-registry", file=sys.stderr)
            return 1
        cmd = jungle_register_argv(manifest, args.jungle_registry, args.host)
        print(f"[{mode}] " + " ".join(cmd))
        if args.apply:
            try:
                subprocess.run(cmd, check=True)
            except (OSError, subprocess.CalledProcessError) as e:
                print(f"mcpjungle registration failed (manifest and registry already applied): {e}", file=sys.stderr)
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
