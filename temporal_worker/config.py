"""Temporal connection config. All values overridable via environment variables."""
import os

TEMPORAL_HOST = os.getenv("CAM_TEMPORAL_HOST", "localhost:7233")
TASK_QUEUE = os.getenv("CAM_TEMPORAL_TASK_QUEUE", "cam-rfq-pipeline")
NAMESPACE = os.getenv("CAM_TEMPORAL_NAMESPACE", "default")
FASTAPI_ROUTER_URL = os.getenv("CAM_FASTAPI_ROUTER_URL", "http://localhost:5100")
