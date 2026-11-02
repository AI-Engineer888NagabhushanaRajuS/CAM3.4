"""
SPEC-015 defects D6 and D7: the router must reach each MCP server at its own host.

- D6: each tool server is its own container. The router builds one URL per manifest, so the
  host must be overridable per manifest (CAM_MCP_HOST_<MANIFEST_ID>), and compose must set it.
- D7: the rfq-memory manifest port must match the service (8108).
"""
import importlib.util
import json
import os

import yaml

ROOT = os.path.join(os.path.dirname(__file__), "..")
MANIFESTS = os.path.join(ROOT, "manifests")


def _load_router_config(monkeypatch, env):
    """Load fastapi-router/config.py under a unique name with the given env."""
    for key in [k for k in os.environ if k.startswith("CAM_MCP_HOST")]:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    spec = importlib.util.spec_from_file_location(
        "router_config_under_test", os.path.join(ROOT, "fastapi-router", "config.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_host_is_overridable_per_server(monkeypatch):
    cfg = _load_router_config(monkeypatch, {"CAM_MCP_HOST_CENTUM_INTAKE": "intake-mcp-server"})
    url = cfg.MCP_URLS["centum_intake"]
    assert url.startswith("http://intake-mcp-server:"), url
    assert url.endswith(":8002/mcp"), url
    assert cfg.TOOL_URLS["centum_intake__scan_local_file"] == url
    assert len(cfg.MCP_URLS) >= 5, "manifest scan returned suspiciously few servers"


def test_default_host_still_used_without_override(monkeypatch):
    cfg = _load_router_config(monkeypatch, {})
    assert cfg.MCP_URLS["centum_intake"].startswith(f"http://{cfg.MCP_HOST}:")


def test_compose_sets_a_host_for_every_mcp_manifest():
    with open(os.path.join(ROOT, "docker-compose.yml"), encoding="utf-8") as fh:
        compose = yaml.safe_load(fh)
    router_env = compose["services"]["fastapi-router"]["environment"]
    manifest_ids = []
    for name in os.listdir(MANIFESTS):
        if name.endswith(".json"):
            with open(os.path.join(MANIFESTS, name), encoding="utf-8") as fh:
                data = json.load(fh)
            if data.get("tools"):  # rfq-memory is HTTP, not MCP; the router never calls it
                manifest_ids.append(data["id"])
    assert len(manifest_ids) >= 5, manifest_ids
    for mid in manifest_ids:
        key = f"CAM_MCP_HOST_{mid.upper()}"
        assert key in router_env, f"compose missing {key}"
        assert router_env[key] in compose["services"], f"{key} points at unknown service {router_env[key]}"


def test_rfq_memory_manifest_port_matches_service():
    with open(os.path.join(MANIFESTS, "centum_rfq_memory.json"), encoding="utf-8") as fh:
        assert json.load(fh)["port"] == 8108  # D7: service listens on 8108 (compose, config.py)
