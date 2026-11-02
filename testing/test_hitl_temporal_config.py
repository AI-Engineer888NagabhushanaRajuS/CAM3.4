"""hitl_router imports temporal_worker/client.py after fastapi-router's config.py is already
loaded. Both folders have a config.py, so the bare `import config` in client.py must still
resolve to temporal_worker/config.py; otherwise every HITL decision fails with
"module 'config' has no attribute 'TEMPORAL_HOST'" and no signal reaches the workflow.
"""
import os
import subprocess
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def test_temporal_client_config_survives_fastapi_router_config_import():
    script = (
        "import sys\n"
        f"sys.path.insert(0, {os.path.join(REPO, 'fastapi-router')!r})\n"
        "import config  # fastapi-router config loaded first, as hitl_router.py does\n"
        f"sys.path.insert(0, {os.path.join(REPO, 'temporal_worker')!r})\n"
        "import client\n"
        "assert hasattr(client.config, 'TEMPORAL_HOST'), client.config.__file__\n"
        "print('ok', client.config.__file__)\n"
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, cwd=REPO)
    assert result.returncode == 0, result.stderr[-800:]
    assert "temporal_worker" in result.stdout
