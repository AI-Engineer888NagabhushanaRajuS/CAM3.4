"""The release gate of the export (mcp_server.release_gate): ready only when the report checks, the CBOM line rules and the engine all pass."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mcp-tools", "reporting", "superset")))
import mcp_server  # noqa: E402

GOOD_ENGINE = {"status": "ok", "complete": True}
GOOD_VALIDATION = {"passed": True, "checks": [{"name": "x", "passed": True, "detail": ""}]}


def test_everything_passing_is_release_ready():
    assert mcp_server.release_gate({"validation": GOOD_VALIDATION, "engine_check": GOOD_ENGINE, "data_violations": []}) == (True, [])


def test_a_failed_report_check_blocks_the_release():
    ready, why = mcp_server.release_gate({"validation": {"passed": False, "checks": [{"name": "no_dup", "passed": False, "detail": "2 dups"}]},
                                          "engine_check": GOOD_ENGINE, "data_violations": []})
    assert not ready and any("no_dup" in w for w in why)


def test_a_check_that_did_not_run_blocks_the_release():
    ready, why = mcp_server.release_gate({"validation": {"passed": False, "checks": []}, "engine_check": GOOD_ENGINE, "data_violations": []})
    assert not ready and "report validation did not run" in why


def test_a_bad_cbom_line_blocks_the_release():
    ready, why = mcp_server.release_gate({"validation": GOOD_VALIDATION, "engine_check": GOOD_ENGINE,
                                          "data_violations": [{"row": 3, "part": "R9", "message": "part_qty: missing"}]})
    assert not ready and any("R9" in w for w in why)


def test_an_incomplete_or_disabled_engine_check_blocks_the_release():
    for engine in ({"status": "ok", "complete": False}, {"status": "skipped", "reason": "disabled"}, {"status": "failed"}):
        ready, _ = mcp_server.release_gate({"validation": GOOD_VALIDATION, "engine_check": engine, "data_violations": []})
        assert not ready, engine
