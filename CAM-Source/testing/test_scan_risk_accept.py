"""The user may release a file that only Repel Shield warned about (ClamAV clean), by its sha256; never a ClamAV hit or an engine error."""
import hashlib
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "fastapi-router")))
import scan_engines as se  # noqa: E402


def _file(tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p), hashlib.sha256(data).hexdigest()


def _run(monkeypatch, items, clam_verdict, repel_verdict, accepted=frozenset()):
    monkeypatch.setattr(se, "clamav_scan", lambda paths: {p: {"verdict": clam_verdict, "detail": "x"} for p in paths})
    monkeypatch.setattr(se, "repel_scan", lambda path, name: {"verdict": repel_verdict, "score": 60, "flags": ["external_reference"], "detail": "x"})
    return se.scan_files(items, accepted)


def test_a_repel_warning_is_released_when_its_hash_is_accepted(tmp_path, monkeypatch):
    p, digest = _file(tmp_path, "bom.xlsx", b"workbook-bytes")
    [r] = _run(monkeypatch, [(p, "bom.xlsx")], "clean", "threat", accepted={digest[:12]})
    assert r["decision"] == "released" and r["risk_accepted"] is True
    assert "accepted risk" in r["reason"]


def test_a_warning_without_acceptance_stays_quarantined(tmp_path, monkeypatch):
    p, _ = _file(tmp_path, "bom.xlsx", b"workbook-bytes")
    [r] = _run(monkeypatch, [(p, "bom.xlsx")], "clean", "threat")
    assert r["decision"] == "quarantined" and r["risk_accepted"] is False


def test_a_clamav_virus_is_never_released_even_if_accepted(tmp_path, monkeypatch):
    p, digest = _file(tmp_path, "bom.xlsx", b"virus-bytes")
    [r] = _run(monkeypatch, [(p, "bom.xlsx")], "threat", "threat", accepted={digest[:12]})
    assert r["decision"] == "quarantined" and r["risk_accepted"] is False


def test_an_engine_error_is_never_released_even_if_accepted(tmp_path, monkeypatch):
    p, digest = _file(tmp_path, "bom.xlsx", b"some-bytes")
    [r] = _run(monkeypatch, [(p, "bom.xlsx")], "clean", "error", accepted={digest[:12]})
    assert r["decision"] == "error" and r["risk_accepted"] is False
