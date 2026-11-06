"""
SPEC-009: PostHog per-tab failure alert tests.
"""
import sys
import os
from unittest.mock import patch, MagicMock

REPORTING_DIR = os.path.join(os.path.dirname(__file__), "..", "mcp-tools", "reporting", "superset")
sys.path.insert(0, REPORTING_DIR)


def _make_validate_result(failures: list[str]) -> dict:
    """Build a validate_all_reports()-shaped result for testing."""
    details = [{"table": t, "passed": False, "checks": []} for t in failures]
    details += [{"table": "ok_tab", "passed": True, "checks": []}]
    return {
        "rfq_id": "CE-TEST-001",
        "total": len(details),
        "passed": len(details) - len(failures),
        "failed": len(failures),
        "details": details,
    }


def test_posthog_not_called_when_key_absent():
    """When POSTHOG_API_KEY is not set, no HTTP call should be made."""
    try:
        import reporting_pipeline as rp
    except ImportError as e:
        import pytest
        pytest.skip(f"reporting_pipeline unavailable: {e}")

    os.environ.pop("POSTHOG_API_KEY", None)
    result = _make_validate_result(["tab_a", "tab_b"])

    with patch("httpx.post") as mock_post:
        rp._emit_posthog_tab_failures("CE-TEST-001", result)
        mock_post.assert_not_called()


def test_posthog_not_called_when_no_failures():
    """When all tabs pass, no PostHog event should be emitted."""
    try:
        import reporting_pipeline as rp
    except ImportError as e:
        import pytest
        pytest.skip(f"reporting_pipeline unavailable: {e}")

    os.environ["POSTHOG_API_KEY"] = "phc_test_key"
    try:
        result = {
            "rfq_id": "CE-TEST-001",
            "total": 2,
            "passed": 2,
            "failed": 0,
            "details": [
                {"table": "tab_a", "passed": True, "checks": []},
                {"table": "tab_b", "passed": True, "checks": []},
            ],
        }
        with patch("httpx.post") as mock_post:
            rp._emit_posthog_tab_failures("CE-TEST-001", result)
            mock_post.assert_not_called()
    finally:
        del os.environ["POSTHOG_API_KEY"]


def test_posthog_called_with_correct_event_when_tabs_fail():
    """When tabs fail and POSTHOG_API_KEY is set, emit rfq_tab_validation_failed."""
    try:
        import reporting_pipeline as rp
    except ImportError as e:
        import pytest
        pytest.skip(f"reporting_pipeline unavailable: {e}")

    os.environ["POSTHOG_API_KEY"] = "phc_test_key"
    try:
        result = _make_validate_result(["summary_report", "missing_notes_report"])

        mock_response = MagicMock()
        with patch("httpx.post", return_value=mock_response) as mock_post:
            rp._emit_posthog_tab_failures("CE-TEST-001", result)

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        payload = call_kwargs[1]["json"] if call_kwargs[1] else call_kwargs[0][1]

        assert payload["event"] == "rfq_tab_validation_failed"
        props = payload["properties"]
        assert props["rfq_id"] == "CE-TEST-001"
        assert props["failed_count"] == 2
        assert "summary_report" in props["failed_tabs"]
        assert "missing_notes_report" in props["failed_tabs"]
    finally:
        del os.environ["POSTHOG_API_KEY"]


def test_posthog_failure_is_nonfatal():
    """If httpx.post raises, _emit_posthog_tab_failures must not propagate the exception."""
    try:
        import reporting_pipeline as rp
    except ImportError as e:
        import pytest
        pytest.skip(f"reporting_pipeline unavailable: {e}")

    os.environ["POSTHOG_API_KEY"] = "phc_test_key"
    try:
        result = _make_validate_result(["failing_tab"])
        with patch("httpx.post", side_effect=Exception("network error")):
            # Must not raise
            rp._emit_posthog_tab_failures("CE-TEST-001", result)
    finally:
        del os.environ["POSTHOG_API_KEY"]
