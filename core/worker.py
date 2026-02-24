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

from core.executors import (
    ComfyUIWorkflow,
    ChainExecutorWorkflow,
    ControlPlaneFanoutWorkflow,
)
from core.activities import (
    select_best_server,
    execute_and_track_workflow,
    interrupt_comfy_prompt,
    download_and_store_artifacts,
    resolve_chain_templates,
    evaluate_chain_condition,
    apply_workflow_parameters,
    transfer_artifacts_from_storage,
    create_workflow_record,
    create_cached_workflow_record_activity,
    persist_step_output_artifact_activity,
    update_chain_status_activity,
    update_workflow_status_activity,
    get_workflow_artifacts,
    publish_step_completed_activity,
    publish_step_cached_activity,
    publish_level_wait_event,
    get_step_cache_activity,
    upsert_step_cache_activity,
    create_approval_request_activity,
    upload_local_inputs,
    save_executed_definition_activity,
)
from core.servers import ServerRegistry
from core.database import init_db
from core.config import get_servers
from core.services.broadcast import connect_broadcast, disconnect_broadcast


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
    from core.config import get_temporal_address
    temporal_address = get_temporal_address()
    logger.info(f"Connecting to Temporal at {temporal_address}...")
    client = await Client.connect(temporal_address)

    # Create worker
    worker = Worker(
        client,
        task_queue="comfyui-gpu-farm",  # Name of our task queue
        workflows=[
            ComfyUIWorkflow,
            ChainExecutorWorkflow,
            ControlPlaneFanoutWorkflow,
        ],  # Register workflow classes
        activities=[                     # Register activity functions
            select_best_server,
            execute_and_track_workflow,
            interrupt_comfy_prompt,
            download_and_store_artifacts,
            resolve_chain_templates,
            evaluate_chain_condition,
            apply_workflow_parameters,
            transfer_artifacts_from_storage,
            create_workflow_record,
            create_cached_workflow_record_activity,
            persist_step_output_artifact_activity,
            update_chain_status_activity,
            update_workflow_status_activity,
            get_workflow_artifacts,
            publish_step_completed_activity,
            publish_step_cached_activity,
            publish_level_wait_event,
            get_step_cache_activity,
            upsert_step_cache_activity,
            create_approval_request_activity,
            upload_local_inputs,
            save_executed_definition_activity,
        ]
    )

    logger.info("=" * 60)
    logger.info("🔧 Temporal Worker Started")
    logger.info("=" * 60)
    logger.info("Connected to Temporal: localhost:7233")
    logger.info("Task Queue: comfyui-gpu-farm")
    logger.info(
        "Workflows: %s",
        [
            ComfyUIWorkflow.__name__,
            ChainExecutorWorkflow.__name__,
            ControlPlaneFanoutWorkflow.__name__,
        ],
    )
    if log_file:
        logger.info(f"Log file: {log_file}")
    logger.info("=" * 60)
    logger.info("Worker is running. Press Ctrl+C to stop.")

    # Run worker (blocks until stopped)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
