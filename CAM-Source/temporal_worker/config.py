"""Temporal connection config. All values overridable via environment variables."""
import os

TEMPORAL_HOST = os.getenv("CAM_TEMPORAL_HOST", "localhost:7233")
TASK_QUEUE = os.getenv("CAM_TEMPORAL_TASK_QUEUE", "cam-rfq-pipeline")
NAMESPACE = os.getenv("CAM_TEMPORAL_NAMESPACE", "default")
# Routing profile for an upload that does not name one (the upload form's `profile` field overrides it)
DEFAULT_PROFILE = os.getenv("CAM_DEFAULT_PROFILE", "Standard_BOM_Flow")
FASTAPI_ROUTER_URL = os.getenv("CAM_FASTAPI_ROUTER_URL", "http://localhost:5100")
# Tool calls (activities) that run at the same time. The tool servers share one DuckDB file lock and one local model, so
# more calls than this only queue behind each other until their HTTP timeouts fire (30 s routing lookup, 10 min tool call),
# and the retries then pile up as duplicated work: 25 RFQs started together all ended Failed that way. Temporal holds the
# rest in its own queue for free, and a queued activity's timeout has not started yet.
MAX_CONCURRENT_ACTIVITIES = int(os.getenv("CAM_WORKER_MAX_ACTIVITIES", "4"))
# How long execute_tool waits for the router's answer. It must outlast the router's own limit on the tool call
# (fastapi-router TOOL_CALL_TIMEOUT, 900 s) and stay under the workflow's start_to_close (20 min). It was 600 s: an export
# under load (5.4 min for the workbook alone on 2026-11-18, plus the formula engine) was cut at 10 min while the router was
# still waiting for it, Temporal retried, and the same export ran again (B18, B19).
TOOL_HTTP_TIMEOUT = float(os.getenv("CAM_TOOL_HTTP_TIMEOUT", "1080"))
