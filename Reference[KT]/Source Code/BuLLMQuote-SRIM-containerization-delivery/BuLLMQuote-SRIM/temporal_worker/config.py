"""Temporal worker configuration. All values override-able via environment variables."""

import os

# Temporal server address
TEMPORAL_HOST = os.getenv("TEMPORAL_HOST", "localhost:7233")

# Temporal namespace (default is fine for local dev)
NAMESPACE = os.getenv("TEMPORAL_NAMESPACE", "default")

# Task queue name — must match between worker and client
TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "cam-rfq-pipeline")

# fastapi_router base URL (same target as Dify)
FASTAPI_ROUTER_URL = os.getenv("FASTAPI_ROUTER_URL", "http://localhost:5000")
