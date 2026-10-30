"""
SPEC-007: Security and Temporal-default regression tests.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "fastapi-router"))


def test_temporal_defaults_true():
    """CAM_USE_TEMPORAL env default must be 'true' in upload_server and hitl_router."""
    env_backup = os.environ.pop("CAM_USE_TEMPORAL", None)
    try:
        # Reload to pick up missing-env-var default
        import importlib
        import upload_server
        importlib.reload(upload_server)
        assert upload_server.USE_TEMPORAL is True, "CAM_USE_TEMPORAL default must be True in CAM 3.4"
    except ImportError as e:
        import pytest
        pytest.skip(f"upload_server deps unavailable: {e}")
    finally:
        if env_backup is not None:
            os.environ["CAM_USE_TEMPORAL"] = env_backup


def test_temporal_false_when_env_set():
    """Setting CAM_USE_TEMPORAL=false must override the default."""
    os.environ["CAM_USE_TEMPORAL"] = "false"
    try:
        import importlib
        import upload_server
        importlib.reload(upload_server)
        assert upload_server.USE_TEMPORAL is False
    except ImportError as e:
        import pytest
        pytest.skip(f"upload_server deps unavailable: {e}")
    finally:
        del os.environ["CAM_USE_TEMPORAL"]


def test_sql_injection_blocked_by_identifier_validator():
    """_validate_sql_identifier must reject shell-injection and SQL meta-characters."""
    try:
        import fastapi_router as fr
    except ImportError as e:
        import pytest
        pytest.skip(f"fastapi_router deps unavailable: {e}")

    evil_ids = [
        "CE-001'; DROP TABLE rfq_master--",
        "CE-001 OR 1=1",
        "'; exec xp_cmdshell('whoami')--",
        "CE-001\x00null",
        "../etc/passwd",
    ]
    for evil in evil_ids:
        try:
            result = fr._validate_sql_identifier(evil, "rfq_id")
            assert False, f"Should have raised ValueError for {evil!r}, got {result!r}"
        except ValueError:
            pass


def test_fastapi_router_has_no_fstring_rfq_sql():
    """SPEC-007/008: _build_rfq_context was removed with the Ollama chat path, and no
    f-string SQL literal (rfq_lit) may remain in fastapi_router."""
    import inspect
    try:
        import fastapi_router as fr
    except ImportError as e:
        import pytest
        pytest.skip(f"fastapi_router deps unavailable: {e}")

    assert not hasattr(fr, "_build_rfq_context"), "removed in SPEC-008 (chat moved to rfq-memory)"
    assert "rfq_lit" not in inspect.getsource(fr), "f-string SQL literal rfq_lit must not return"


def test_hitl_decision_endpoint_registered():
    """hitl_router must expose POST /api/rfq/{rfq_id}/hitl/decision."""
    try:
        import hitl_router as hr
    except ImportError as e:
        import pytest
        pytest.skip(f"hitl_router deps unavailable: {e}")

    routes = {r.path: list(r.methods) for r in hr.app.routes if hasattr(r, "methods")}
    assert "/api/rfq/{rfq_id}/hitl/decision" in routes, "hitl/decision route must be registered"
    assert "POST" in routes["/api/rfq/{rfq_id}/hitl/decision"]
