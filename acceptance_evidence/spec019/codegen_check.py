"""Live check of the bridge's lint + codegen on every REAL design manifest (the running bridge container, not unit fakes)."""
import glob
import json
import os
import urllib.error
import urllib.request

BRIDGE = "http://localhost:13110"
ROOT = r"C:\CAM[3.4]-RFQ_centum\CAM-Source\manifests"


def call(path, body=None, token=None, method="POST"):
    req = urllib.request.Request(BRIDGE + path, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:
            return e.code, {}


_, tok = call("/auth/token", {"rfq_id": "MANIFESTS"})
token = tok.get("access_token") or tok.get("token")
print("token ok:", bool(token))

kinds = {"agent": "agent/*.json", "skill": "skills/*.json", "reporting": "reporting/*.json", "approved": "repo-approved/*.json"}
tot_files = tot_err = tot_warn = 0
for kind, pat in kinds.items():
    d, _ = pat.split('/')
    for f in sorted(os.path.join(ROOT, d, n) for n in os.listdir(os.path.join(ROOT, d)) if n.endswith('.json')):
        text = open(f, encoding="utf-8").read()
        s, lint = call("/api/manifests/lint", {"kind": kind, "text": text}, token)
        errs = [x for x in lint.get("findings", []) if x["level"] == "error"]
        warns = [x for x in lint.get("findings", []) if x["level"] == "warning"]
        tot_files += 1; tot_err += len(errs); tot_warn += len(warns)
        if s != 200 or errs:
            print("LINT PROBLEM", os.path.basename(f), s, errs[:2])
print(f"lint: {tot_files} real manifests, {tot_err} errors, {tot_warn} warnings")

skill = open(os.path.join(ROOT, "skills", "skill_01_input_standardization.json"), encoding="utf-8").read()
subs = [x["sub_skill_id"] for x in json.loads(skill)["sub_skills"]]
ok_all = True
hashes = {}
for sid in subs:
    s, out = call("/api/manifests/codegen", {"text": skill, "sub_skill_id": sid}, token)
    ok_all &= (s == 200 and out["ast"]["ok"])
    hashes[sid] = out.get("bundle_sha256", "")[:12]
print("codegen skill_01 sub-skills", subs, "all AST ok:", ok_all, "hashes", hashes)
s, again = call("/api/manifests/codegen", {"text": skill, "sub_skill_id": subs[0]}, token)
print("deterministic (same hash twice):", again["bundle_sha256"][:12] == hashes[subs[0]])
changed = skill.replace("Triggered by manual UI upload", "Triggered by manual UI upload or watch folder", 1)
s, c2 = call("/api/manifests/codegen", {"text": changed, "sub_skill_id": subs[0]}, token)
print("hash follows an edit:", c2["bundle_sha256"][:12] != hashes[subs[0]], "->", c2["bundle_sha256"][:12])
first_file = next(iter(again["files"]))
print("generated file:", first_file, "| lines:", again["files"][first_file].count("\n"))
print("\n".join(again["files"][first_file].splitlines()[:32]))
s, bad = call("/api/manifests/codegen", {"text": "{not json"}, token)
print("invalid JSON ->", s, str(bad)[:100])
s, inj = call("/api/manifests/codegen", {"text": skill.replace("The Mail Room", json.dumps("{{ 7*7 }} \"\"\" import os; __import__('os')")[1:-1]), "sub_skill_id": subs[0]}, token)
src = next(iter(inj["files"].values())) if inj.get("files") else ""
print("template-injection text rendered inert:", "49" not in src.split("OFFICE")[0] if src else "n/a", "| AST ok:", inj.get("ast", {}).get("ok"))
