from __future__ import annotations

import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from deal_platform.activities.context import load_context_config
from deal_platform.activities.extraction import extract_terms
from deal_platform.activities.memory import load_agent_memory, save_agent_memory
from deal_platform.activities.transactional import db_read, db_write
from deal_platform.db.connection import DatabaseConnection
from deal_platform.db.schema import initialize_db
from deal_platform.workflows.deal_agent import TASK_QUEUE, DealAgentWorkflow


async def run_worker(temporal_address: str = "localhost:7233") -> None:
    """Start a single worker that handles both workflows and activities."""
    # Ensure DB schema exists
    initialize_db(DatabaseConnection())

    client = await Client.connect(temporal_address)
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[DealAgentWorkflow],
        activities=[
            load_agent_memory,
            save_agent_memory,
            extract_terms,
            load_context_config,
            db_read,
            db_write,
        ],
    )
    print(f"Worker started on task queue '{TASK_QUEUE}' (server: {temporal_address})")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(run_worker())
