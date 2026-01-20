"""
Activities: Database operations for chains and workflows
"""

import sys
from pathlib import Path
from typing import Dict, Any, Optional

from temporalio import activity

# Add parent to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from temporal_gateway.database import (
    get_session,
    create_chain,
    create_workflow,
    update_chain_status,
    update_workflow_status,
    get_workflow,
)
from temporal_gateway.services.broadcast import publish_chain_event


@activity.defn
async def create_chain_record(
    chain_name: str,
    job_id: str,
    job_run_id: str,
    chain_definition: Optional[Dict[str, Any]] = None,
    description: Optional[str] = None,
) -> str:
    """
    Activity: Create chain record in database

    Args:
        chain_name: Chain name
        job_id: Job ID (Temporal workflow ID)
        job_run_id: Job run ID (Temporal run ID)
        chain_definition: Full chain definition (YAML as dict)
        description: Optional description

    Returns:
        Chain ID
    """
    activity.logger.info(f"Creating chain record: {chain_name}")

    try:
        with get_session() as session:
            chain = create_chain(
                session=session,
                name=chain_name,
                job_id=job_id,
                job_run_id=job_run_id,
                chain_definition=chain_definition,
                description=description,
                status="initializing"
            )
            activity.logger.info(f"✓ Created chain record: {chain.id}")
            return chain.id

    except Exception as e:
        activity.logger.error(f"Failed to create chain record: {e}")
        raise


@activity.defn
async def create_workflow_record(
    workflow_name: str,
    server_address: str,
    prompt_id: str,
    chain_id: Optional[str] = None,
    step_id: Optional[str] = None,
    job_id: Optional[str] = None,
    job_run_id: Optional[str] = None,
    workflow_definition: Optional[Dict[str, Any]] = None,
    parameters: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Activity: Create workflow record in database

    Args:
        workflow_name: Workflow name
        server_address: ComfyUI server address
        prompt_id: ComfyUI prompt ID
        chain_id: Optional chain ID
        step_id: Optional step ID (for chain workflows)
        job_id: Job ID (Temporal workflow ID)
        job_run_id: Job run ID (Temporal run ID)
        workflow_definition: Workflow JSON
        parameters: Resolved parameters

    Returns:
        Workflow ID
    """
    activity.logger.info(f"Creating workflow record: {workflow_name} (prompt: {prompt_id})")

    try:
        with get_session() as session:
            workflow_record = create_workflow(
                session=session,
                workflow_name=workflow_name,
                server_address=server_address,
                prompt_id=prompt_id,
                chain_id=chain_id,
                step_id=step_id,
                job_id=job_id,
                job_run_id=job_run_id,
                workflow_definition=workflow_definition,
                parameters=parameters,
                status="queued"
            )
            activity.logger.info(f"✓ Created workflow record: {workflow_record.id}")
            return workflow_record.id

    except Exception as e:
        activity.logger.error(f"Failed to create workflow record: {e}")
        raise


@activity.defn
async def update_chain_status_activity(
    chain_id: str,
    status: str,
    current_level: Optional[int] = None,
    error_message: Optional[str] = None,
) -> None:
    """
    Activity: Update chain status in database

    Args:
        chain_id: Chain ID
        status: New status
        current_level: Optional current level
        error_message: Optional error message
    """
    activity.logger.info(f"Updating chain {chain_id} status to: {status}")

    try:
        with get_session() as session:
            update_chain_status(
                session=session,
                chain_id=chain_id,
                status=status,
                current_level=current_level,
                error_message=error_message
            )
            activity.logger.info(f"✓ Updated chain status")

        # Publish completion/failure events to Redis for SSE subscribers
        if status == "completed":
            await publish_chain_event(
                chain_id=chain_id,
                event={
                    "type": "chain_completed",
                    "chain_id": chain_id,
                }
            )
            activity.logger.info(f"Published chain_completed event for chain {chain_id}")
        elif status == "failed":
            await publish_chain_event(
                chain_id=chain_id,
                event={
                    "type": "chain_failed",
                    "chain_id": chain_id,
                    "error": error_message,
                }
            )
            activity.logger.info(f"Published chain_failed event for chain {chain_id}")

    except Exception as e:
        activity.logger.error(f"Failed to update chain status: {e}")
        # Don't fail workflow for status update failures


@activity.defn
async def update_workflow_status_activity(
    workflow_id: str,
    status: str,
    error_message: Optional[str] = None,
) -> None:
    """
    Activity: Update workflow status in database

    Args:
        workflow_id: Workflow ID
        status: New status
        error_message: Optional error message
    """
    activity.logger.info(f"Updating workflow {workflow_id} status to: {status}")

    try:
        with get_session() as session:
            update_workflow_status(
                session=session,
                workflow_id=workflow_id,
                status=status,
                error_message=error_message
            )
            activity.logger.info(f"✓ Updated workflow status")

    except Exception as e:
        activity.logger.error(f"Failed to update workflow status: {e}")
        # Don't fail workflow for status update failures


@activity.defn
async def publish_step_completed_activity(
    chain_id: str,
    step_id: str,
) -> None:
    """
    Activity: Publish step_completed event to Redis

    Args:
        chain_id: Chain ID
        step_id: Step ID that completed
    """
    try:
        await publish_chain_event(
            chain_id=chain_id,
            event={
                "type": "step_completed",
                "chain_id": chain_id,
                "step_id": step_id,
            }
        )
        activity.logger.info(f"Published step_completed event for {step_id} in chain {chain_id}")
    except Exception as e:
        activity.logger.error(f"Failed to publish step_completed event: {e}")
        # Don't fail workflow for event publish failures


@activity.defn
async def get_workflow_artifacts(
    workflow_id: str,
) -> list[str]:
    """
    Activity: Get artifact IDs for a workflow

    Args:
        workflow_id: Workflow ID

    Returns:
        List of artifact IDs (returns ["latest"] if only latest needed)
    """
    activity.logger.info(f"Getting artifacts for workflow: {workflow_id}")

    try:
        with get_session() as session:
            workflow_record = get_workflow(session, workflow_id)
            if not workflow_record or not workflow_record.latest_artifact_id:
                activity.logger.warning(f"No artifacts found for workflow {workflow_id}")
                return []

            # Return the latest artifact ID
            return [workflow_record.latest_artifact_id]

    except Exception as e:
        activity.logger.error(f"Failed to get workflow artifacts: {e}")
        return []
