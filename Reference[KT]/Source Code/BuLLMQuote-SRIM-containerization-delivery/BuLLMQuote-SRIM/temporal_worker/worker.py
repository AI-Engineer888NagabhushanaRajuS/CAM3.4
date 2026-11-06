"""Temporal worker process entry point.

Run: python temporal_worker/worker.py

Requires Temporal server: temporal server start-dev --port 7233
"""

import asyncio
import sys
import os

# Ensure the package directory is in sys.path when run as a script
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

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
    print(f"[Temporal Worker] Starting on task queue '{config.TASK_QUEUE}' @ {config.TEMPORAL_HOST}")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
