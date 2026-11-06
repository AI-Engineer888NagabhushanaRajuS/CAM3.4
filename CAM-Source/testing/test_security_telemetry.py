"""GET /api/security/telemetry and /api/memory/status: aggregation of the audit logs, what is never exposed, auth."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))
from test_attachment_api import api, auth, client, upload  # noqa: E402,F401  (api is a fixture)
from test_scan_engines import FAKE_SIGNATURE, make_docx  # noqa: E402

SECRET = "TOP-SECRET-FILE-BODY-9f3a"
HASH = "ab" * 32


def stamp(days_ago=0, minutes=0):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago, minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def line(name, decision, when=None, reason="Clean on both engines", clam="clean", repel="clean"):
    return json.dumps({"time": when or stamp(), "name": name, "size": 10, "sha256": HASH, "attachment_id": "x" * 12,
                       "clamav": {"verdict": clam, "detail": SECRET}, "repel": {"verdict": repel, "score": 0, "flags": []},
                       "decision": decision, "reason": reason})


def write_audit(api, scope, lines):
    d = os.path.join(api.ATTACHMENT_INBOX, scope, "attachments")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "audit.jsonl"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def get(api, path="/api/security/telemetry", headers=None):
    return client(api).get(path, headers=auth(api, "SECURITY") if headers is None else headers)


def test_aggregates_every_scope_with_counts_and_newest_first(api):
    write_audit(api, "RFQ-A", [line("old.csv", "released", stamp(minutes=30)), line("bad.txt", "quarantined", stamp(minutes=5), "Repel Shield: macro", repel="threat")])
    write_audit(api, "RFQ-B", [line("odd.pdf", "error", stamp(minutes=10), "held", clam="error"), line("gone.csv", "deleted", stamp()),
                               line("new.xlsx", "released", stamp(minutes=1))])
    body = get(api).json()
    assert body["counts"] == {"released": 2, "quarantined": 1, "held": 1, "error": 0}
    assert [r["name"] for r in body["recent"]] == ["new.xlsx", "bad.txt", "odd.pdf", "old.csv"]
    assert body["recent"][1] == {"time": body["recent"][1]["time"], "scope": "RFQ-A", "name": "bad.txt", "decision": "quarantined",
                                 "reason": "Repel Shield: macro", "clamav": "clean", "repel": "threat"}
    assert body["policy"] == {"failClosed": True, "maxFiles": 10, "maxFileBytes": 25 * 1024 * 1024, "maxTotalBytes": 60 * 1024 * 1024}


def test_skips_a_corrupt_line_and_old_decisions(api):
    write_audit(api, "RFQ-A", ["{not json", '{"time": "yesterday", "decision": "released"}', '{"decision": "released"}', "",
                               line("ok.csv", "released"), line("ancient.csv", "quarantined", stamp(days_ago=31))])
    body = get(api).json()
    assert body["counts"] == {"released": 1, "quarantined": 0, "held": 0, "error": 3}   # error = unreadable audit lines
    assert [r["name"] for r in body["recent"]] == ["ok.csv"]


def test_recent_is_capped_at_fifty_but_counts_cover_all(api):
    write_audit(api, "RFQ-A", [line(f"f{i}.csv", "released", stamp(minutes=i)) for i in range(60)])
    body = get(api).json()
    assert body["counts"]["released"] == 60 and len(body["recent"]) == 50 and body["recent"][0]["name"] == "f0.csv"


def test_never_exposes_contents_or_hashes(api):
    write_audit(api, "RFQ-A", [line("a.csv", "released")])
    raw = get(api).text
    assert SECRET not in raw and HASH not in raw and "sha256" not in raw and "attachment_id" not in raw


def test_empty_inbox_and_engine_health(api):
    body = get(api).json()
    assert body["counts"] == {"released": 0, "quarantined": 0, "held": 0, "error": 0} and body["recent"] == []
    clam, repel = body["engines"]
    assert (clam["id"], clam["status"], clam["signatures"]) == ("clamav", "ok", 28173) and "28173" in clam["detail"]
    assert (repel["id"], repel["status"]) == ("repel", "ok")


def test_unavailable_engine_reports_its_reason(api, monkeypatch):
    import scan_engines
    monkeypatch.setattr(scan_engines, "_run", lambda a, t: (_ for _ in ()).throw(FileNotFoundError("no clamscan")))
    scan_engines._clamav_status.cache_clear()
    clam = get(api).json()["engines"][0]
    assert clam["status"] == "unavailable" and "no clamscan" in clam["detail"] and clam["signatures"] is None


def test_real_scan_decisions_show_up(api, tmp_path):
    p = make_docx(tmp_path / "ok.docx", ["Net 45 days payment terms."])
    upload(api, [("ok.docx", open(p, "rb").read()), ("eicar.txt", FAKE_SIGNATURE)])
    body = get(api).json()
    assert body["counts"]["released"] == 1 and body["counts"]["quarantined"] == 1
    assert {r["scope"] for r in body["recent"]} == {"RFQ-APITEST"}


def test_routes_need_a_valid_token(api):
    for path in ("/api/security/telemetry", "/api/memory/status"):
        assert get(api, path, headers={}).status_code == 401
        assert get(api, path, headers={"Authorization": "Bearer nonsense"}).status_code == 401


def test_memory_status_proxies_or_says_unreachable(api, monkeypatch):
    import urllib.request

    class Res:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, *a): return b'{"writesEnabled": false, "provider": "ollama", "maxConcurrent": 1, "running": 0, "queued": 0}'

    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout: Res())
    ok = get(api, "/api/memory/status").json()
    assert ok == {"available": True, "writesEnabled": False, "provider": "ollama", "maxConcurrent": 1, "running": 0, "queued": 0}

    def refuse(url, timeout):
        raise OSError("refused")
    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    down = get(api, "/api/memory/status").json()
    assert down["available"] is False and "not reachable" in down["reason"]
