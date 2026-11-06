"""LIVE proof of dynamic propagation on a proof RFQ: edit one final_* value -> reports regenerate -> cell diff across sheets -> revert.
Usage: python -I propagate_check.py RFQ-CENTUM-PROOF-24 [apply]   (without 'apply' it only picks a row and prints the plan)"""
import json
import sys
import time
import urllib.error
import urllib.request

BRIDGE = "http://localhost:13110"
RFQ = sys.argv[1]
APPLY = len(sys.argv) > 2 and sys.argv[2] == "apply"


def call(path, body=None, token=None, method=None, timeout=420):
    req = urllib.request.Request(BRIDGE + path, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})},
                                 method=method or ("POST" if body is not None else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:
            return e.code, {"detail": str(e)}


_, tok = call("/auth/token", {"rfq_id": RFQ})
token = tok.get("access_token") or tok.get("token")
s, prev = call(f"/api/bom/preview/{RFQ}", token=token)
rows = prev if isinstance(prev, list) else prev.get("rows") or prev.get("data") or prev.get("items") or []
print("preview status", s, "rows", len(rows), "| keys of first row:", sorted(rows[0].keys())[:14] if rows else None)
cand = [r for r in rows if isinstance(r.get("final_price_conv"), (int, float)) and r["final_price_conv"] > 0 and r.get("bom_item_id")]
print("rows with a numeric final_price_conv:", len(cand))
row = cand[0]
before = row["final_price_conv"]
after = round(before * 1.10 + 0.01, 4)
print(f"picked bom_item_id={row['bom_item_id']} volume={row.get('volume_no')} final_price_conv {before} -> {after}")
s, ex0 = call(f"/api/rfq/{RFQ}/exports", token=token)
print("exports before:", [(e["filename"][-24:], e["diff_summary"]) for e in ex0][:3])
if not APPLY:
    sys.exit(0)

edit = {"edits": [{"bom_item_id": row["bom_item_id"], **({"volume_no": row["volume_no"]} if row.get("volume_no") is not None else {}), "set": {"final_price_conv": after}}], "note": "SPEC-020 live proof"}
t0 = time.time()
s, out = call(f"/api/rfq/{RFQ}/edit-and-regenerate", edit, token)
print(f"\nEDIT status {s} in {time.time()-t0:.1f}s  ok={out.get('ok')} applied={out.get('applied')}")
print("items:", out.get("items"))
print("before:", out.get("before"), "| after:", out.get("after"))
d = out.get("diff")
if d:
    print("TOTAL CHANGED CELLS:", d["total_changed_cells"], "across", len(d["sheets"]), "sheets")
    for sh in d["sheets"]:
        print(f"  {sh['sheet']}: {sh['changed']} changed; e.g.", sh["examples"][:2])
else:
    print("diff:", d, out.get("diff_note"), out.get("diff_error"), out.get("detail"))
s, ex1 = call(f"/api/rfq/{RFQ}/exports", token=token)
print("exports after (newest first):", [(e["filename"][-24:], e["diff_summary"]) for e in ex1][:3])
# the new version downloads by its exact name; the old one still does
for e in ex1[:2]:
    req = urllib.request.Request(BRIDGE + f"/api/rfq/{RFQ}/exports/{e['filename']}/download", headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=60) as r:
        print("download", e["filename"][-24:], r.status, len(r.read()), "bytes")

# REVERT: put the original value back (this regenerates once more, another kept version)
t0 = time.time()
edit["edits"][0]["set"]["final_price_conv"] = before
edit["note"] = "SPEC-020 live proof: revert"
s, back = call(f"/api/rfq/{RFQ}/edit-and-regenerate", edit, token)
print(f"\nREVERT status {s} in {time.time()-t0:.1f}s ok={back.get('ok')} changed cells:", (back.get("diff") or {}).get("total_changed_cells"))
s, prev2 = call(f"/api/bom/preview/{RFQ}", token=token)
rows2 = prev2 if isinstance(prev2, list) else prev2.get("rows") or prev2.get("data") or prev2.get("items") or []
now = next(r for r in rows2 if r.get("bom_item_id") == row["bom_item_id"] and r.get("volume_no") == row.get("volume_no"))["final_price_conv"]
print("value restored in the database:", now == before, f"({now} vs original {before})")
