"""
Temporal Worker for ComfyUI Workflows

This worker connects to Temporal Server and executes workflows and activities.
Run this alongside the FastAPI gateway.
"""

import asyncio
import sys
import logging
from pathlib import Path
from datetime import datetime

# Add parent to path
sys.path.append(str(Path(__file__).parent.parent))

from temporalio.client import Client
from temporalio.worker import Worker


def setup_worker_logging(log_dir: Path = None, log_level: str = "INFO"):
    """Simple logging setup for worker (no Rich to avoid Temporal sandbox issues)"""
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"worker_{timestamp}.log"

    # Configure root logger
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file),
        ]
    )

    return logging.getLogger("worker"), log_file

from temporal_gateway.executors import ComfyUIWorkflow, ChainExecutorWorkflow
from temporal_gateway.activities import (
    select_best_server,
    execute_and_track_workflow,
    download_and_store_artifacts,
    create_execution_log,
    get_server_output_files,
    resolve_chain_templates,
    evaluate_chain_condition,
    apply_workflow_parameters,
    transfer_outputs_to_input,
    transfer_artifacts_from_storage,
    create_chain_record,
    create_workflow_record,
    update_chain_status_activity,
    update_workflow_status_activity,
    get_workflow_artifacts,
    publish_step_completed_activity,
    create_approval_request_activity,
    upload_local_inputs,
)
from temporal_gateway.servers import ServerRegistry
from temporal_gateway.database import init_db
from temporal_gateway.config import get_servers
from temporal_gateway.services.broadcast import connect_broadcast, disconnect_broadcast


async def main():
    """Start the Temporal worker"""

    # Setup logging (writes to logs/ directory)
    log_dir = Path(__file__).parent / "logs"
    logger, log_file = setup_worker_logging(log_dir=log_dir, log_level="INFO")

    # Initialize database
    logger.info("Initializing artifact database...")
    init_db()
    logger.info("Database initialized")

    # Connect to Redis for broadcast events
    logger.info("Connecting to Redis for event broadcasting...")
    await connect_broadcast()
    logger.info("Redis broadcast connected")

    # Initialize server registry
    logger.info("Loading server registry...")
    registry = ServerRegistry.get_instance()
    logger.info(f"Registered {len(registry)} servers")
    for server in registry.get_all_servers():
        logger.info(f"  Server: {server.name} ({server.provider_type})")

    # Connect to Temporal Server
    # For local dev with CLI: localhost:7233
    # For docker-compose: temporal:7233
    client = await Client.connect("localhost:7233")

    # Create worker
    worker = Worker(
        client,
        task_queue="comfyui-gpu-farm",  # Name of our task queue
        workflows=[ComfyUIWorkflow, ChainExecutorWorkflow],  # Register workflow classes
        activities=[                     # Register activity functions
            select_best_server,
            execute_and_track_workflow,
            download_and_store_artifacts,
            create_execution_log,
            get_server_output_files,
            resolve_chain_templates,
            evaluate_chain_condition,
            apply_workflow_parameters,
            transfer_outputs_to_input,
            transfer_artifacts_from_storage,
            create_chain_record,
            create_workflow_record,
            update_chain_status_activity,
            update_workflow_status_activity,
            get_workflow_artifacts,
            publish_step_completed_activity,
            create_approval_request_activity,
            upload_local_inputs,
        ]
    )

    logger.info("=" * 60)
    logger.info("🔧 Temporal Worker Started")
    logger.info("=" * 60)
    logger.info("Connected to Temporal: localhost:7233")
    logger.info("Task Queue: comfyui-gpu-farm")
    logger.info(f"Workflows: {[ComfyUIWorkflow.__name__, ChainExecutorWorkflow.__name__]}")
    if log_file:
        logger.info(f"Log file: {log_file}")
    logger.info("=" * 60)
    logger.info("Worker is running. Press Ctrl+C to stop.")

    # Run worker (blocks until stopped)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
