"""[BuLLMQuote-SRIM MIGRATION NOTE -- ported 2026-08-11, now points at this repo]
This copy IS the current orchestrator -- run it from here, not from the old
C:\\Users\\ADMIN\\Documents\\SRIM\\Tools\\I n D\\centum intake\\ location. All
paths below resolve relative to this repo (BuLLMQuote-SRIM), pointed at the
copies that have actually been migrated so far:
  - upload_server / fastapi_router / hitl_router / bom_qa_lookup_server /
    python_bridge (duck_db_api.py): this same fastmcp-router/ directory.
  - reporting_mcp_server: mcp-tools/reporting/superset/mcp_server.py.
  - intake_mcp_server / distributor_pricing_mcp_server (RFQ_Flow's own tool
    servers, ports 8002/8003): mcp-tools/intake/ and
    mcp-tools/distributor-pricing/.
  - web_frontend / daemon: accomplish-ui/apps/web and accomplish-ui/apps/daemon
    (this repo's own accomplish-ui copy, not the old Downloads checkout).

NOT migrated yet, so NOT in SERVICES below:
  - scrub_mcp_server -- only exists at the old centum intake location today;
    mcp-tools/bom-processing/ (its intended new home, per that folder's own
    README) is still an empty placeholder. Add it back here once it's copied
    over.

Known gap, worked around below rather than fixed here (see
mcp-tools/reporting/superset/config.py's own MIGRATION NOTE for the full
explanation): database/ hasn't been migrated into this repo yet, so
reporting/superset's and duck_db_api.py's/bom_qa_lookup_server.py's default
DB path resolution (`../database`, correct from the old location, wrong from
here) would silently point at a nonexistent folder. REPORTING_DATABASE_DIR is
set explicitly for every service that imports reporting_module's config.py,
pointed at the still-live old database directory, exactly as that file's own
docstring prescribes as the interim fix. Remove _REPORTING_DB_ENV once
database/ is migrated into this repo's own top-level database/ folder.
[END MIGRATION NOTE]

Master process/health orchestration for the BuLLMQuote-SRIM backend.

Starts, stops, health-checks, and continuously monitors every backend service this
project needs, plus the external infrastructure they depend on (Postgres, Ollama, the
Bifrost MCP gateway -- replacing MCP Jungle for RFQ_Flow as of the Bifrost migration;
MCP Jungle itself is still running, untouched, for Standard_BOM_Flow, but no longer
health-checked here). Designed to be the one script anyone runs to bring the backend up
and to know, at any moment, whether it's actually healthy -- not just "the process
exists," but "the port answers."

Usage:
    python manage_backend.py start              # start every service not already running
    python manage_backend.py stop               # stop every service this script started
    python manage_backend.py restart            # stop, then start
    python manage_backend.py status              # one-shot health/process report, exit 0 if all healthy else 1
    python manage_backend.py monitor [--interval SECONDS] [--auto-restart]
                                                  # continuous loop, reprints status each interval;
                                                  # --auto-restart relaunches any service whose process died

State (PIDs, log paths, start times) is persisted to .backend_services_state.json so
`status`/`stop`/`monitor` work correctly even when invoked as a separate process from
whichever `start` call actually launched things.
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

import psutil

# Single canonical source for the Postgres connection strings -- see db.py's
# own comment for why these are read-from-env-with-a-fallback rather than a
# hard requirement. Every service env block below that needs a DB URL
# references these instead of re-declaring its own copy of the string.
from db import LOGIC_DB_URL, FILE_METADATA_DB_URL

# Line-buffer stdout regardless of invocation context -- when this script's output is
# piped/redirected (e.g. `monitor` output tee'd to a log file, or run as a background
# process), Python defaults to full block-buffering, which can delay status lines by
# many cycles until the buffer fills. Monitoring output needs to appear in real time.
sys.stdout.reconfigure(line_buffering=True)

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(PROJECT_ROOT)  # BuLLMQuote-SRIM itself

# reporting_module was migrated to mcp-tools/reporting/superset/ -- NOT a
# "reporting_module" subdirectory of this folder (that was the old layout).
REPORTING_DIR = os.path.join(REPO_ROOT, "mcp-tools", "reporting", "superset")

# RFQ_Flow's own tool servers -- ports 8002/8003, not managed by the old
# centum-intake manage_backend.py at all (this repo's mcp-tools/ is their
# first home under any orchestrator).
INTAKE_MCP_DIR = os.path.join(REPO_ROOT, "mcp-tools", "intake")
DISTRIBUTOR_PRICING_DIR = os.path.join(REPO_ROOT, "mcp-tools", "distributor-pricing")
# RFQ_Flow's optional Gerber ZIP feature-extraction step (gerber__extract_features,
# system_skills_registry skill_index 18). Used to call out to a separate,
# externally-managed Gerber-parsing engine (pcba-mcp-server) via MCP Jungle
# for extract_pcb_specs/extract_checklist -- as of 2026-09-02 that logic has
# been ported directly into this directory (extraction_pipeline.py), so this
# service is now fully self-contained: no second process, no second MCP
# Jungle registration. Still does its own DB write into bom_storage.duckdb's
# gerber_geometry/gerber_checklist tables, unchanged.
GERBER_INTEGRATION_DIR = os.path.join(REPO_ROOT, "mcp-tools", "gerber-integration")
# gerbonara>=1.6 (the ported extraction logic's own dependency) requires
# Python 3.12+; this repo's own shared environment (PYTHON = sys.executable
# above) is 3.10, so this service gets its own dedicated venv rather than
# forcing an incompatible gerbonara downgrade. Created via
# `py -3.14 -m venv .venv` from this directory, with
# requirements.txt (+ fastmcp/duckdb/requests, the same non-gerbonara-specific
# deps the old shared environment already provided) installed into it.
GERBER_INTEGRATION_VENV_PYTHON = os.path.join(GERBER_INTEGRATION_DIR, ".venv", "Scripts", "python.exe")

# Cognee-backed RFQ chat memory service -- ingestion + JWT-verified chat
# retrieval for the middle-pane RFQ chat feature. Runs on this repo's
# shared Python environment (cognee==1.4.2 is pinned in its own
# requirements.txt -- see that file's own comment for why: 1.5.0-1.5.4 all
# fail to even start on this Windows/Python 3.10 machine, confirmed via
# direct testing, unrelated to any config choice here). Two independent
# uvicorn listeners in one process (see memory_service.py's own docstring):
# a LAN-facing JWT-gated chat port and a loopback-only internal
# ingest/reset port -- manage_backend.py only health-checks the LAN one,
# since the loopback one is deliberately unreachable from this process too.
RFQ_MEMORY_DIR = os.path.join(REPO_ROOT, "mcp-tools", "rfq-memory")

# The actual Gerber/PCB-parsing engine (pcba-mcp-server) that
# gerber_integration_mcp_server used to call out to via MCP Jungle -- a
# separate project with its own venv, kept at its own location rather than
# copied into this repo. Previously started manually and left forgotten
# (exactly why it went down once with nobody noticing); briefly brought
# under this script's own management as an interim fix on 2026-09-02, then
# superseded the same day by porting its logic directly into
# gerber_integration_mcp_server above. Kept here, commented out, rather than
# deleted outright, in case the port ever needs to be reverted.
# PCBA_MCP_SERVER_DIR = r"C:\Users\ADMIN\Downloads\PCBA-FE\PCBA-FE\pcba-mcp-server"
# PCBA_MCP_SERVER_PYTHON = os.path.join(PCBA_MCP_SERVER_DIR, ".venv", "Scripts", "python.exe")
# PCBA_MCP_TOKEN = os.environ.get("PCBA_MCP_TOKEN", "")

# The frontend (accomplish-ui's @accomplish/web app) is this repo's OWN copy --
# accomplish-ui/, a sibling of fastmcp-router/ and mcp-tools/ -- not the old
# separate checkout under C:\Users\ADMIN\Downloads\accomplish-ui\accomplish-ui.
ACCOMPLISH_UI_ROOT = os.path.join(REPO_ROOT, "accomplish-ui")
FRONTEND_DIR = os.path.join(ACCOMPLISH_UI_ROOT, "apps", "web")
# pnpm's own .bin shim is a .CMD wrapper on Windows and an extensionless POSIX
# shell script everywhere else -- os.name selects the right one so this still
# resolves on Linux/Hetzner instead of looking for a file that can't exist
# there. The "invoke the .bin shim directly, not via `pnpm dev`" strategy
# itself (see the PID-tracking comment further below) stays unchanged.
_VITE_BIN_NAME = "vite.CMD" if os.name == "nt" else "vite"
FRONTEND_VITE_BIN = os.path.join(FRONTEND_DIR, "node_modules", ".bin", _VITE_BIN_NAME)
# The frontend's login page calls its local daemon (not a cloud service) at
# http://<host>:9334/auth/login -- confirmed via apps/web/src/client/config/endpoints.ts's
# dev-mode fallback and apps/daemon/src/browser-api-server.ts's BrowserApi listener. This
# is what was missing when login failed with "Cannot reach authentication server".
# (Port bumped from 9234 to 9334 so this stack can run alongside CAM's centum-intake
# stack, which still uses 9234 -- see the daemon SERVICES entry's env block below.)
DAEMON_DIR = os.path.join(ACCOMPLISH_UI_ROOT, "apps", "daemon")
DESKTOP_DIR = os.path.join(ACCOMPLISH_UI_ROOT, "apps", "desktop")
STATE_FILE = os.path.join(PROJECT_ROOT, ".backend_services_state.json")
LOG_DIR = os.path.join(PROJECT_ROOT, "service_logs")
PYTHON = sys.executable

# See the top-of-file MIGRATION NOTE: database/ isn't migrated into this repo
# yet, so anything importing reporting_module's config.py needs this pointed
# at the still-live old database directory or it'll fail on first DB access
# (even though the process itself starts and its health check still passes).
# REPORTING_DATABASE_DIR env var overrides this -- required on Linux/Hetzner,
# where the Windows fallback path below cannot exist at all.
_OLD_DATABASE_DIR = os.environ.get(
    "REPORTING_DATABASE_DIR",
    r"C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum intake\database",
)
_REPORTING_DB_ENV = {"REPORTING_DATABASE_DIR": _OLD_DATABASE_DIR}

# ---------------------------------------------------------------------------
# Service inventory -- every uvicorn/FastMCP process this project defines, plus the
# frontend's Vite dev server. Confirmed by grepping every top-level .py file for
# uvicorn.run()/mcp.run() calls; this is the complete, real list, not a guess from
# memory. Each entry runs via `[PYTHON, script]` by default; set `cmd` instead of
# `script` to run something else directly (e.g. the frontend's vite binary --
# invoked directly rather than through `pnpm dev`, since pnpm's own cmd.exe wrapper
# chain on Windows exits once it hands off to the real vite/node process, silently
# orphaning it from the tracked PID -- vite.CMD invoked directly keeps one stable,
# terminate()-able process tree, confirmed by testing both).
# ---------------------------------------------------------------------------
SERVICES = [
    {
        "name": "upload_server",
        "script": os.path.join(PROJECT_ROOT, "upload_server.py"),
        "cwd": PROJECT_ROOT,
        "host": "127.0.0.1",
        # Bumped off CAM's centum-intake stack's port (3000) so both stacks can
        # run side by side on this machine -- see the +100 offset scheme used
        # for every port in this SERVICES list below.
        "port": 3100,
        "health_path": "/docs",
        "health_kind": "http_2xx",
    },
    {
        "name": "fastapi_router",
        "script": os.path.join(PROJECT_ROOT, "fastapi_router.py"),
        "cwd": PROJECT_ROOT,
        "host": "127.0.0.1",
        "port": 5100,
        "health_path": "/docs",
        "health_kind": "http_2xx",
    },
    {
        "name": "hitl_router",
        "script": os.path.join(PROJECT_ROOT, "hitl_router.py"),
        "cwd": PROJECT_ROOT,
        "host": "127.0.0.1",
        "port": 5102,
        "health_path": "/docs",
        "health_kind": "http_2xx",
    },
    # scrub_mcp_server (port 8004) is NOT migrated into this repo yet -- see the
    # top-of-file MIGRATION NOTE. It still only exists at the old centum-intake
    # location; add it back here once mcp-tools/bom-processing/ is populated.
    {
        "name": "reporting_mcp_server",
        "script": os.path.join(REPORTING_DIR, "mcp_server.py"),
        "cwd": REPORTING_DIR,
        "host": "100.121.36.255",
        # NOTE: MCP Jungle's own external tool registry still points at :8005
        # for this server -- that registration must be updated separately
        # (outside this repo) or DMR calls routed through MCP Jungle to this
        # tool will fail after this port change.
        "port": 8105,
        "health_path": "/",
        "health_kind": "http_any",
        "env": _REPORTING_DB_ENV,
    },
    {
        # RFQ_Flow's own BOM-import tool server -- not managed by the old
        # centum-intake manage_backend.py at all.
        "name": "intake_mcp_server",
        "script": os.path.join(INTAKE_MCP_DIR, "mcp_server.py"),
        "cwd": INTAKE_MCP_DIR,
        "host": "100.121.36.255",
        "port": 8002,
        "health_path": "/",
        "health_kind": "http_any",
    },
    {
        # RFQ_Flow's own distributor-pricing tool server (DigiKey/Element14/
        # Mouser enrichment, single-source price selection, Quote summary).
        "name": "distributor_pricing_mcp_server",
        "script": os.path.join(DISTRIBUTOR_PRICING_DIR, "mcp_server.py"),
        "cwd": DISTRIBUTOR_PRICING_DIR,
        "host": "100.121.36.255",
        "port": 8003,
        "health_path": "/",
        "health_kind": "http_any",
        # currency.py (in this tool server) reads LOGIC_DB_URL directly -- point
        # it at BuLLMQuote's own logic_db_2, not CAM's shared logic_db.
        "env": {"LOGIC_DB_URL": LOGIC_DB_URL},
    },
    {
        # RFQ_Flow's optional Gerber ZIP feature-extraction wrapper -- see
        # GERBER_INTEGRATION_DIR's own comment above. As of 2026-09-02 this is
        # fully self-contained (extraction_pipeline.py does the real Gerber
        # parsing in-process) -- no more MCP Jungle hop to a second server.
        # User-approved binding: this machine's NetBird mesh IP (unchanged
        # from when this DID need to reach the external Gerber PCBA server
        # over that mesh -- kept as-is since nothing forces a rebind now).
        # Uses its own dedicated venv (GERBER_INTEGRATION_VENV_PYTHON, see
        # that constant's own comment above) instead of this repo's shared
        # Python -- gerbonara>=1.6 needs 3.12+, the shared environment is 3.10.
        "name": "gerber_integration_mcp_server",
        "cmd": [GERBER_INTEGRATION_VENV_PYTHON, "mcp_server.py"],
        "cwd": GERBER_INTEGRATION_DIR,
        "host": "100.121.36.255",
        "port": 8007,
        "health_path": "/",
        "health_kind": "http_any",
    },
    {
        # Scripted BOM/RFQ Q&A lookup for the demo chatbot -- a plain HTTP JSON
        # endpoint (POST /ask), NOT an MCP server and NOT in any LLM/agent loop.
        # accomplish-ui's daemon (apps/daemon/src/task-service.ts) calls this
        # directly, before a chat message is ever handed to OpenCode/Ollama, and
        # short-circuits with the answer if it matches a known question shape.
        # Lives here as a separate Python process purely because Node's native
        # duckdb bindings are blocked by this machine's Application Control
        # policy. Every connection this server opens is fully READ_ONLY (see its
        # own module docstring) -- never competes with the pipeline's own writes.
        "name": "bom_qa_lookup_server",
        "script": os.path.join(PROJECT_ROOT, "bom_qa_lookup_server.py"),
        "cwd": PROJECT_ROOT,
        "host": "100.121.36.255",
        "port": 8106,
        "health_path": "/",
        "health_kind": "http_2xx",
        "env": _REPORTING_DB_ENV,
    },
    {
        # Cognee-backed RFQ chat memory -- see RFQ_MEMORY_DIR's own comment
        # above. Only the LAN-facing chat port (8108) is health-checked
        # here; the loopback-only internal ingest/reset port (8109, see
        # memory_service.py) is intentionally not reachable from anywhere
        # health checks run, including this script.
        "name": "rfq_memory_server",
        "script": os.path.join(RFQ_MEMORY_DIR, "memory_service.py"),
        "cwd": RFQ_MEMORY_DIR,
        "host": "100.121.36.255",
        "port": 8108,
        "health_path": "/health",
        "health_kind": "http_2xx",
        "env": {"LOGIC_DB_URL": LOGIC_DB_URL, "FILE_METADATA_DB_URL": FILE_METADATA_DB_URL},
    },
    {
        # The frontend's "Python Bridge" (VITE_PYTHON_BRIDGE_URL) -- BOM preview,
        # inline-edit save, alternates, and export downloads. Wraps
        # reporting_module's own database.connect()/final_selection functions
        # directly rather than duplicating that logic.
        "name": "python_bridge",
        "script": os.path.join(PROJECT_ROOT, "duck_db_api.py"),
        "cwd": PROJECT_ROOT,
        "host": "100.121.36.255",
        "port": 3110,
        "health_path": "/docs",
        "health_kind": "http_2xx",
        "env": _REPORTING_DB_ENV,
    },
    {
        "name": "web_frontend",
        "cmd": [FRONTEND_VITE_BIN],
        "cwd": FRONTEND_DIR,
        "host": "100.121.36.255",
        # vite.config.ts reads process.env.PORT first (strictPort: false), so
        # this env var is what actually moves Vite off CAM's frontend port
        # (5180) -- the "port" field below only drives the health-check probe
        # and must match it.
        "env": {"PORT": "5281"},
        "port": 5281,
        "health_path": "/",
        # Vite serves a real 200 HTML page at "/" (unlike the FastMCP servers above,
        # which have no root route and 404 there).
        "health_kind": "http_2xx",
    },
    {
        # Local Apache Superset install backing the embedded dashboard on the
        # frontend's 9th wizard stage (Reports & Analytics) -- see
        # apps/daemon/src/superset-client.ts. A venv-installed Flask app, not a
        # project script -- run via its own console-script entry point (a real .exe,
        # not a .cmd shim, so no shell=True is needed here) with the exact same flags
        # already validated against the live install.
        #
        # SUPERSET_CONFIG_PATH is required here -- relying on cwd-based config
        # discovery (no explicit env var) is NOT reliable across every launch
        # context: it silently fell back to Superset's insecure default
        # SECRET_KEY (refusing to start) both after a system reboot and after a
        # plain `manage_backend.py restart`, even though the exact same command
        # had worked earlier in the same session. Setting this explicitly here
        # removes that flakiness for good.
        "name": "superset",
        "cmd": [
            # SUPERSET_BIN overrides this -- on Linux/Hetzner there is no
            # venv\Scripts\superset.exe; a real install would set this to
            # e.g. /opt/superset/venv/bin/superset.
            os.environ.get("SUPERSET_BIN", r"C:\Superset\venv\Scripts\superset.exe"),
            "run",
            "-h", "0.0.0.0", "-p", "8188", "--with-threads", "--reload", "--debugger",
        ],
        "cwd": os.environ.get("SUPERSET_CWD", r"C:\Superset"),
        "env": {
            "SUPERSET_CONFIG_PATH": os.environ.get(
                "SUPERSET_CONFIG_PATH", r"C:\Superset\superset_config.py"
            )
        },
        "host": "127.0.0.1",
        "port": 8188,
        "health_path": "/health",
        "health_kind": "http_2xx",
    },
    {
        "name": "daemon",
        "cwd": DAEMON_DIR,
        # tsup (the daemon's TypeScript bundler) is only resolvable via PATH when pnpm
        # itself injects node_modules/.bin -- run through pnpm for this one-shot build
        # step (it exits on its own, so pnpm's cmd.exe-wrapper-orphans-the-child problem
        # that ruled out `pnpm dev` for web_frontend doesn't apply here).
        "pre_build_cmd": ["pnpm", "run", "build"],
        # The actual long-lived process: run the built bundle directly with node.exe
        # (a real executable, unlike pnpm's/vite's .cmd shims) for one stable,
        # terminate()-able PID -- same reasoning as web_frontend above.
        #
        # --data-dir gives this daemon its own PID lock/socket/DB, scoped away
        # from the dev-mode default of ~/.accomplish (see index.ts's
        # getPidFilePath(dataDir)/getSocketPath(dataDir)) -- without this, this
        # daemon fails to start with PidLockError whenever CAM's own daemon
        # (which still uses the ~/.accomplish default) is already running.
        "cmd": ["node", "dist/index.js", "--data-dir", os.path.join(os.path.expanduser("~"), ".accomplish-bullmquote")],
        # Matches apps/daemon/scripts/dev.cjs's own dev-mode env: ACCOMPLISH_APP_PATH
        # points the OpenCode CLI resolver at apps/desktop (without it, task:start
        # throws "OpenCode runtime is not available"); ACCOMPLISH_DAEMON_DEV enables
        # dev-only behavior (the daemon's own .env already sets ACCOMPLISH_TEST_LOGIN=1
        # for the fixed-credentials login bypass).
        #
        # ACCOMPLISH_BACKEND_PORT moves the daemon itself off CAM's port (9234) --
        # see packages/agent-core/src/common/constants.ts's own comment: this env
        # var is the documented way to do that, no source constant edit needed.
        # BOM_QA_LOOKUP_URL / PYTHON_SERVICE_URL / SUPERSET_URL point the daemon at
        # this stack's own renumbered bom_qa_lookup_server, python_bridge, and
        # superset instead of their (already-wrong-host) source-code fallback
        # defaults -- see task-service.ts, browser-api-server.ts, superset-client.ts.
        # DATABASE_URL / FILE_METADATA_DB_URL point db.ts's two pools at
        # BuLLMQuote's own logic_db_2/file_metadata_db_2 instead of their
        # source-code fallback defaults (CAM's shared logic_db/file_metadata_db).
        "env": {
            "ACCOMPLISH_DAEMON_DEV": "1",
            "ACCOMPLISH_APP_PATH": DESKTOP_DIR,
            "ACCOMPLISH_BACKEND_PORT": "9334",
            "BOM_QA_LOOKUP_URL": "http://100.121.36.255:8106",
            "PYTHON_SERVICE_URL": "http://100.121.36.255:3110",
            "SUPERSET_URL": "http://127.0.0.1:8188",
            # RFQ chat feature (BuLLMQuote-SRIM) -- see task-service.ts's own
            # provider-chain gating comment. Off by default everywhere else;
            # explicitly on here now that the Cognee dataset-isolation
            # blocker is resolved (docs/RfqChat/cognee-isolation-investigation.md).
            "ACCOMPLISH_ENABLE_RFQ_CHAT": "1",
            "PYTHON_BRIDGE_URL": "http://100.121.36.255:3110",
            "RFQ_MEMORY_CHAT_URL": "http://100.121.36.255:8108",
            "CAM_HITL_ROUTER_URL": "http://127.0.0.1:5102",
            # Node's `pg` driver expects the `postgres://` scheme prefix (vs.
            # `postgresql://` used elsewhere in this repo) -- same underlying
            # credential, sourced from db.py's single canonical constant
            # rather than a third hardcoded copy of the same string.
            "DATABASE_URL": LOGIC_DB_URL.replace("postgresql://", "postgres://", 1),
            "FILE_METADATA_DB_URL": FILE_METADATA_DB_URL.replace("postgresql://", "postgres://", 1),
        },
        "host": "localhost",
        "port": 9334,
        "health_path": "/health",
        "health_kind": "http_2xx",
    },
    {
        # CAM 3.4: Temporal workflow worker -- runs RFQWorkflow activities.
        # Only started when CAM_USE_TEMPORAL=true; exit-0 immediately when
        # Temporal is not configured (worker.py checks and self-exits cleanly).
        "name": "temporal_worker",
        "script": os.path.join(REPO_ROOT, "temporal_worker", "worker.py"),
        "cwd": os.path.join(REPO_ROOT, "temporal_worker"),
        "host": "127.0.0.1",
        "port": 7233,  # Temporal gRPC frontend -- health-checked via TCP connect
        "health_path": None,
        "health_kind": "tcp",
        "skip_port_precheck": True,  # 7233 is Temporal server, not the worker; don't block start
        "env": {
            "CAM_USE_TEMPORAL": os.environ.get("CAM_USE_TEMPORAL", "true"),
            "CAM_TEMPORAL_HOST": os.environ.get("CAM_TEMPORAL_HOST", "localhost:7233"),
            "CAM_FASTAPI_ROUTER_URL": os.environ.get("CAM_FASTAPI_ROUTER_URL", "http://localhost:5100"),
        },
    },
]

# External infrastructure the services above depend on but that this script does not
# start itself (Postgres runs as a system service; Ollama and the MCP Jungle gateway are
# separately managed) -- health-checked anyway, since a service process being "up" can
# still mean every real request fails if one of these is down.
EXTERNAL_DEPENDENCIES = [
    {"name": "postgres (logic_db/file_metadata_db)", "kind": "tcp", "host": "localhost", "port": 5432},
    {"name": "ollama", "kind": "http_2xx", "url": "http://localhost:11434/api/tags"},
    # MCP Jungle is no longer health-checked here -- RFQ_Flow's tool calls
    # (fastapi_router.py/intake/gerber-integration/distributor-pricing) now
    # go through Bifrost instead. Its containers are still running,
    # untouched, since Standard_BOM_Flow still points at it (unmigrated --
    # see the top-of-file MIGRATION NOTE on scrub_mcp_server).
    {"name": "bifrost_gateway", "kind": "http_2xx", "url": "http://localhost:8010/health"},
]


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


# ---------------------------------------------------------------------------
# Low-level checks
# ---------------------------------------------------------------------------

def _tcp_open(host, port, timeout=1.5):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _http_get(url, timeout=2.5):
    """Returns (reached: bool, status_code: int|None, detail: str). `reached=True`
    whenever the server sent back an HTTP response at all, regardless of status code --
    distinguishing "process is up but this path 404s" from "nothing is listening."""
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, resp.status, "ok"
    except urllib.error.HTTPError as e:
        return True, e.code, f"HTTP {e.code}"
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
        return False, None, str(e.reason if isinstance(e, urllib.error.URLError) else e)


def check_dependency(dep):
    """Returns (healthy: bool, detail: str) for one entry in EXTERNAL_DEPENDENCIES."""
    if dep["kind"] == "tcp":
        ok = _tcp_open(dep["host"], dep["port"])
        return ok, ("port open" if ok else "connection failed")
    if dep["kind"] == "http_2xx":
        reached, status, detail = _http_get(dep["url"])
        ok = reached and status is not None and 200 <= status < 300
        return ok, (f"HTTP {status}" if reached else detail)
    if dep["kind"] == "http_any":
        reached, status, detail = _http_get(dep["url"])
        return reached, (f"HTTP {status}" if reached else detail)
    return False, "unknown dependency kind"


def check_service_health(svc):
    """Returns (healthy: bool, detail: str) using the service's own declared health check."""
    if svc["health_kind"] == "tcp":
        ok = _tcp_open(svc["host"], svc["port"])
        return ok, ("port open" if ok else "connection failed")
    url = f"http://{svc['host']}:{svc['port']}{svc['health_path']}"
    reached, status, detail = _http_get(url)
    if svc["health_kind"] == "http_2xx":
        ok = reached and status is not None and 200 <= status < 300
        return ok, (f"HTTP {status}" if reached else detail)
    if svc["health_kind"] == "http_any":
        return reached, (f"HTTP {status}" if reached else detail)
    return False, "unknown health check kind"


def is_pid_alive(pid):
    try:
        return psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


# ---------------------------------------------------------------------------
# Start / stop
# ---------------------------------------------------------------------------

def start_service(svc, state):
    existing = state.get(svc["name"])
    if existing and is_pid_alive(existing["pid"]):
        print(f"  [{svc['name']}] already running (pid {existing['pid']}) -- skipping")
        return

    if not svc.get("skip_port_precheck") and _tcp_open(svc["host"], svc["port"], timeout=0.5):
        print(f"  [{svc['name']}] WARNING: port {svc['port']} is already in use by something "
              f"this script didn't launch (no tracked PID) -- not starting a duplicate")
        return

    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, f"{svc['name']}.log")
    log_file = open(log_path, "a", encoding="utf-8")
    log_file.write(f"\n===== started {_now()} =====\n")
    log_file.flush()

    # Optional one-shot build step that runs to completion BEFORE the tracked,
    # long-lived process starts (e.g. daemon's tsup bundle) -- shell=True so PATH-based
    # tool resolution (pnpm's own node_modules/.bin injection) works, same as pnpm
    # itself needing shell=True on Windows (a bare Popen(["pnpm", ...]) fails there --
    # pnpm is a .cmd shim, not a real executable). This process is expected to exit on
    # its own, so it's run synchronously and not tracked in `state`.
    if svc.get("pre_build_cmd"):
        print(f"  [{svc['name']}] running pre-build step: {' '.join(svc['pre_build_cmd'])}")
        result = subprocess.run(
            svc["pre_build_cmd"], cwd=svc["cwd"], shell=True,
            stdout=log_file, stderr=subprocess.STDOUT,
        )
        log_file.flush()
        if result.returncode != 0:
            print(f"  [{svc['name']}] pre-build step FAILED (exit {result.returncode}) -- see {log_path}")
            return

    # Default: run a Python script with this interpreter. A service can override with
    # an explicit "cmd" (argv list) instead of "script" -- e.g. web_frontend's vite
    # binary / daemon's node.exe invocation, neither of which is a Python script.
    argv = svc.get("cmd") or [PYTHON, svc["script"]]

    # Merge any service-specific env overrides (e.g. daemon's ACCOMPLISH_DAEMON_DEV)
    # on top of this process's own environment, rather than replacing it wholesale --
    # PATH/USERPROFILE/etc. must still reach the child.
    env = {**os.environ, **svc["env"]} if svc.get("env") else None

    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    try:
        proc = subprocess.Popen(
            argv,
            cwd=svc["cwd"],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            env=env,
        )
    except FileNotFoundError as exc:
        print(f"  [{svc['name']}] SKIPPED -- executable not found: {exc}")
        return
    state[svc["name"]] = {
        "pid": proc.pid,
        "started_at": _now(),
        "log_file": log_path,
        "port": svc["port"],
    }
    save_state(state)
    print(f"  [{svc['name']}] started (pid {proc.pid}), logging to {log_path}")


def wait_for_health(svc, timeout=30, interval=1.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        ok, detail = check_service_health(svc)
        if ok:
            return True, detail
        time.sleep(interval)
    return check_service_health(svc)


def stop_service(name, state):
    entry = state.get(name)
    if not entry:
        print(f"  [{name}] not tracked (no recorded PID) -- nothing to stop")
        return
    pid = entry["pid"]
    if not is_pid_alive(pid):
        print(f"  [{name}] already stopped")
        state.pop(name, None)
        save_state(state)
        return
    try:
        proc = psutil.Process(pid)
        children = proc.children(recursive=True)
        for child in children:
            child.terminate()
        proc.terminate()
        gone, alive = psutil.wait_procs([proc] + children, timeout=8)
        for p in alive:
            p.kill()
        print(f"  [{name}] stopped (pid {pid})")
    except psutil.NoSuchProcess:
        print(f"  [{name}] already gone")
    state.pop(name, None)
    save_state(state)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_status(state, verbose=True):
    """Returns True iff every service and every external dependency is healthy."""
    all_healthy = True

    if verbose:
        print(f"\n=== Backend status @ {_now()} ===\n")
        print("Services:")
    for svc in SERVICES:
        entry = state.get(svc["name"])
        pid = entry["pid"] if entry else None
        proc_alive = pid is not None and is_pid_alive(pid)
        healthy, detail = check_service_health(svc)
        all_healthy = all_healthy and healthy
        if verbose:
            status_word = "HEALTHY" if healthy else ("PROCESS UP, NOT RESPONDING" if proc_alive else "DOWN")
            pid_str = f"pid {pid}" if pid else "no tracked pid"
            print(f"  [{status_word:26s}] {svc['name']:24s} {svc['host']}:{svc['port']:<5} "
                  f"({pid_str}) -- {detail}")

    if verbose:
        print("\nExternal dependencies:")
    for dep in EXTERNAL_DEPENDENCIES:
        healthy, detail = check_dependency(dep)
        all_healthy = all_healthy and healthy
        if verbose:
            status_word = "HEALTHY" if healthy else "DOWN"
            print(f"  [{status_word:26s}] {dep['name']:34s} -- {detail}")

    if verbose:
        print(f"\nOverall: {'ALL HEALTHY' if all_healthy else 'ONE OR MORE ISSUES -- see above'}\n")

    return all_healthy


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_start(args):
    state = load_state()
    print("Starting backend services...")
    for svc in SERVICES:
        start_service(svc, state)

    print("\nWaiting for services to become healthy...")
    for svc in SERVICES:
        ok, detail = wait_for_health(svc, timeout=30)
        word = "OK" if ok else "NOT RESPONDING"
        print(f"  [{word:14s}] {svc['name']} -- {detail}")

    print_status(state)


def cmd_stop(args):
    state = load_state()
    print("Stopping backend services...")
    for svc in SERVICES:
        stop_service(svc["name"], state)
    print("Done.")


def cmd_restart(args):
    cmd_stop(args)
    time.sleep(1)
    cmd_start(args)


def cmd_status(args):
    state = load_state()
    healthy = print_status(state)
    sys.exit(0 if healthy else 1)


def cmd_monitor(args):
    print(f"Monitoring every {args.interval}s (auto-restart {'ON' if args.auto_restart else 'OFF'}). "
          f"Press Ctrl+C to stop.\n")
    consecutive_failures = {svc["name"]: 0 for svc in SERVICES}
    try:
        while True:
            state = load_state()
            print_status(state)

            if args.auto_restart:
                for svc in SERVICES:
                    healthy, _ = check_service_health(svc)
                    entry = state.get(svc["name"])
                    proc_alive = entry is not None and is_pid_alive(entry["pid"])
                    if not proc_alive:
                        print(f"  [{svc['name']}] process is gone -- restarting")
                        start_service(svc, state)
                        consecutive_failures[svc["name"]] = 0
                    elif not healthy:
                        consecutive_failures[svc["name"]] += 1
                        if consecutive_failures[svc["name"]] >= 3:
                            print(f"  [{svc['name']}] unhealthy for 3 consecutive checks -- restarting")
                            stop_service(svc["name"], state)
                            start_service(svc, state)
                            consecutive_failures[svc["name"]] = 0
                    else:
                        consecutive_failures[svc["name"]] = 0

            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nMonitor stopped.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("start", help="Start every backend service not already running")
    sub.add_parser("stop", help="Stop every backend service this script started")
    sub.add_parser("restart", help="Stop then start every service")
    sub.add_parser("status", help="One-shot health/process report (exit 0 if all healthy, else 1)")

    monitor_parser = sub.add_parser("monitor", help="Continuously monitor health/process status")
    monitor_parser.add_argument("--interval", type=int, default=30, help="Seconds between checks (default 30)")
    monitor_parser.add_argument("--auto-restart", action="store_true",
                                 help="Automatically restart a service if its process dies or it fails 3 consecutive health checks")

    args = parser.parse_args()
    {
        "start": cmd_start,
        "stop": cmd_stop,
        "restart": cmd_restart,
        "status": cmd_status,
        "monitor": cmd_monitor,
    }[args.command](args)


if __name__ == "__main__":
    main()
