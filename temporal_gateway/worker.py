"""
Temporal Worker for ComfyUI Workflows

This worker connects to Temporal Server and executes workflows and activities.
Run this alongside the FastAPI gateway.
"""

import asyncio
import sys
import yaml
from pathlib import Path

# Add parent to path
sys.path.append(str(Path(__file__).parent.parent))

from temporalio.client import Client
from temporalio.worker import Worker

from temporal_gateway.workflows import ComfyUIWorkflow, ChainExecutorWorkflow
from temporal_gateway.activities import (
    select_best_server,
    execute_and_track_workflow,
    download_and_store_images,
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
    create_approval_request_activity,
)
from gateway.core import load_balancer
from temporal_gateway.database import init_db


async def main():
    """Start the Temporal worker"""

    # Initialize database
    print("Initializing artifact database...")
    init_db()
    print("✓ Database initialized\n")

    # Load server configuration
    config_path = Path(__file__).parent.parent / "config.yaml"
    print(f"Loading server configuration from: {config_path}")

    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)

        # Register all servers from config
        servers = config.get('servers', [])
        print(f"Found {len(servers)} server(s) in config")

        for server in servers:
            load_balancer.register_server(server['address'])
            print(f"  ✓ Registered: {server['name']} ({server['address']})")

        print()
    except FileNotFoundError:
        print(f"⚠ Config file not found: {config_path}")
        print("  Create config.yaml with server definitions")
        print()
    except Exception as e:
        print(f"⚠ Error loading config: {e}")
        print()

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
            download_and_store_images,
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
            create_approval_request_activity,
        ]
    )

    print("=" * 60)
    print("Temporal Worker Started")
    print("=" * 60)
    print(f"Connected to: localhost:7233")
    print(f"Task Queue: comfyui-gpu-farm")
    print(f"Workflows: {[ComfyUIWorkflow.__name__, ChainExecutorWorkflow.__name__]}")
    print(f"Activities: 9 registered")
    print("=" * 60)
    print("\nWorker is running. Press Ctrl+C to stop.")
    print("Waiting for workflows to execute...\n")

    # Run worker (blocks until stopped)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
