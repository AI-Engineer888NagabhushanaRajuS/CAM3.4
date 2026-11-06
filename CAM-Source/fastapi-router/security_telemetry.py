"""Read-only security telemetry for the Settings -> Security tab: engine health, the twin-verdict decisions of the last
30 days (aggregated from every <inbox>/<scope>/attachments/audit.jsonl) and the memory service's write status.

Exposes names, verdicts and reasons only. File bytes and hashes are never read into the answer, and a line that does not
parse is skipped (and counted) rather than failing the page.
"""
import glob
import json
import os
import re
import urllib.request
from datetime import datetime, timedelta, timezone

WINDOW_DAYS = 30
RECENT_LIMIT = 50
_DECISIONS = {"released": "released", "quarantined": "quarantined", "error": "held"}   # audit decision -> count key


def engines():
    import scan_engines
    clam, repel = scan_engines.clamav_status(), scan_engines.repel_status()
    sigs = re.search(r"signatures (\d+)", clam.get("version") or "")
    return [
        {"id": "clamav", "label": clam["label"], "status": clam["status"],
         "detail": clam["version"] if clam["status"] == "ok" else clam.get("detail") or "unavailable",
         "signatures": int(sigs.group(1)) if sigs else None},
        {"id": "repel", "label": repel["label"], "status": repel["status"], "detail": f"Rule set {repel['version']}",
         "signatures": None},
    ]


def _verdict(engine):
    return engine.get("verdict") if isinstance(engine, dict) else None


def decisions(inbox, now=None):
    """({released, quarantined, held, error}, newest-first recent list). `error` counts audit lines that could not be read."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=WINDOW_DAYS)
    counts = {"released": 0, "quarantined": 0, "held": 0, "error": 0}
    rows = []
    for path in glob.glob(os.path.join(glob.escape(inbox), "*", "attachments", "audit.jsonl")):
        scope = os.path.basename(os.path.dirname(os.path.dirname(path)))
        try:
            if datetime.fromtimestamp(os.path.getmtime(path), timezone.utc) < cutoff:
                continue
            with open(path, encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except OSError:
            counts["error"] += 1
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                when = datetime.fromisoformat(rec["time"].replace("Z", "+00:00"))
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
                key = _DECISIONS.get(rec["decision"])
            except (ValueError, KeyError, TypeError, AttributeError):
                counts["error"] += 1
                continue
            if key is None or when < cutoff:     # `deleted` and anything unknown are not scan decisions
                continue
            counts[key] += 1
            repel = rec.get("repel")
            rows.append({"time": rec["time"], "scope": scope, "name": str(rec.get("name", ""))[:200],
                         "decision": rec["decision"], "reason": str(rec.get("reason") or "")[:300],
                         "clamav": _verdict(rec.get("clamav")), "repel": _verdict(repel), "_when": when})
    rows.sort(key=lambda r: r["_when"], reverse=True)
    return counts, [{k: v for k, v in r.items() if k != "_when"} for r in rows[:RECENT_LIMIT]]


def telemetry(inbox, policy):
    counts, recent = decisions(inbox)
    return {"engines": engines(), "counts": counts, "recent": recent, "policy": {"failClosed": True, **policy}}


def memory_status(url, timeout=2):
    """The memory service's own status, or {available: False, reason} when it cannot be reached."""
    try:
        with urllib.request.urlopen(f"{url}/internal/memory/status", timeout=timeout) as res:
            return {"available": True, **json.load(res)}
    except Exception as e:
        return {"available": False, "reason": f"memory service not reachable ({type(e).__name__})"}
