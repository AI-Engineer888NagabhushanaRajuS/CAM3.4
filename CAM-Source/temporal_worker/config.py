"""Temporal connection config. All values overridable via environment variables."""
import os

TEMPORAL_HOST = os.getenv("CAM_TEMPORAL_HOST", "localhost:7233")
TASK_QUEUE = os.getenv("CAM_TEMPORAL_TASK_QUEUE", "cam-rfq-pipeline")
NAMESPACE = os.getenv("CAM_TEMPORAL_NAMESPACE", "default")
# Routing profile for an upload that does not name one (the upload form's `profile` field overrides it)
DEFAULT_PROFILE = os.getenv("CAM_DEFAULT_PROFILE", "Standard_BOM_Flow")
FASTAPI_ROUTER_URL = os.getenv("CAM_FASTAPI_ROUTER_URL", "http://localhost:5100")
