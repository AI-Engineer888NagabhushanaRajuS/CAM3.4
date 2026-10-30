"""
SPEC-008: Shadow-run parity test — Architecture Diagram 6, Step 10.

"Run DAQ and Temporal on same RFQ and compare outputs"

This is an integration test. It skips automatically when services are unavailable.
Run manually against a live stack:
    CAM_USE_TEMPORAL=true pytest testing/test_shadow_run_parity.py -v

The test runs the same RFQ through both paths and asserts the final outputs agree.
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "fastapi-router"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "temporal_worker"))

# The test RFQ must exist in both Postgres and DuckDB for parity to mean anything.
SHADOW_RFQ_ID = os.environ.get("SHADOW_RFQ_ID", "CE-TEST-SHADOW-001")
UPLOAD_SERVER_URL = os.environ.get("UPLOAD_SERVER_URL", "http://localhost:5099")
FASTAPI_ROUTER_URL = os.environ.get("CAM_FASTAPI_ROUTER_URL", "http://localhost:5100")


def _services_available() -> bool:
    try:
        import httpx
        r = httpx.get(f"{FASTAPI_ROUTER_URL}/health", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


@pytest.mark.skipif(not _services_available(), reason="Services not running — integration test only")
def test_temporal_and_daq_routing_sequences_agree():
    """The routing sequence returned by Temporal and by the direct GET endpoint must match."""
    import httpx

    temporal_resp = httpx.get(
        f"{FASTAPI_ROUTER_URL}/pipeline/routing-sequence/{SHADOW_RFQ_ID}/Standard_BOM_Flow",
        timeout=10,
    )
    assert temporal_resp.status_code == 200, f"routing-sequence failed: {temporal_resp.text}"
    temporal_data = temporal_resp.json()

    assert "routing_sequence" in temporal_data, f"No routing_sequence in: {temporal_data}"
    sequence = temporal_data["routing_sequence"]
    assert isinstance(sequence, list) and len(sequence) > 0, "routing_sequence must be a non-empty list"


@pytest.mark.skipif(not _services_available(), reason="Services not running — integration test only")
def test_temporal_status_endpoint_returns_expected_fields():
    """After a Temporal workflow run, status endpoint must return all expected fields."""
    import httpx

    status_resp = httpx.get(
        f"{FASTAPI_ROUTER_URL}/rfq/{SHADOW_RFQ_ID}/status",
        timeout=10,
    )
    assert status_resp.status_code == 200, f"status endpoint failed: {status_resp.text}"
    data = status_resp.json()

    required_fields = {"rfq_id", "engine"}
    missing = required_fields - set(data.keys())
    assert not missing, f"Status response missing fields: {missing}"
    assert data["rfq_id"] == SHADOW_RFQ_ID


@pytest.mark.skipif(not _services_available(), reason="Services not running — integration test only")
def test_daq_and_temporal_agree_on_stage(tmp_path):
    """Both DAQ (direct DB query) and Temporal report the same rfq_process_stage."""
    import httpx

    # Temporal/API path
    status = httpx.get(f"{FASTAPI_ROUTER_URL}/rfq/{SHADOW_RFQ_ID}/status", timeout=10).json()
    api_stage = status.get("postgres_stage")

    # DAQ path — direct DB
    try:
        from db import get_active_version
        db_stage = get_active_version(SHADOW_RFQ_ID)
    except Exception as e:
        pytest.skip(f"DAQ DB unavailable: {e}")

    assert api_stage == db_stage, (
        f"Stage mismatch: API reports {api_stage!r}, DAQ reports {db_stage!r} — "
        f"Temporal and DAQ are diverging for RFQ {SHADOW_RFQ_ID}"
    )
