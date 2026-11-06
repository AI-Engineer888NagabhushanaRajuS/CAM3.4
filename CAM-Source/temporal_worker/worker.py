"""Temporal worker process — run this to start processing RFQ workflows.

Usage:
    python temporal_worker/worker.py

Environment variables (see config.py):
    CAM_TEMPORAL_HOST        default: localhost:7233
    CAM_TEMPORAL_TASK_QUEUE  default: cam-rfq-pipeline
    CAM_TEMPORAL_NAMESPACE   default: default
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from temporalio.client import Client
from temporalio.worker import Worker

import activities
import config
from workflow import RFQWorkflow


async def main():
    client = await Client.connect(config.TEMPORAL_HOST, namespace=config.NAMESPACE)
    worker = Worker(
        client,
        task_queue=config.TASK_QUEUE,
        workflows=[RFQWorkflow],
        activities=[activities.get_routing_sequence, activities.execute_tool],
    )
    print(f"[Temporal Worker] Connected to {config.TEMPORAL_HOST}", flush=True)
    print(f"[Temporal Worker] Listening on task queue '{config.TASK_QUEUE}'", flush=True)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
