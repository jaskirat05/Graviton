"""
Activities: Database operations for chains and workflows
"""

import sys
from pathlib import Path
from typing import Dict, Any, Optional

from temporalio import activity

# Add parent to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from core.database import (
    get_session,
    create_workflow,
    update_chain_status,
    update_workflow_status,
    get_workflow,
    save_executed_definition,
)
from core.services.broadcast import publish_chain_event
from core.observability.chain_logger import ChainLogger


def _get_log_func(chain_name: Optional[str], chain_version: int, chain_id: Optional[str]):
    """Helper to get a logging function for chain activities."""
    chain_logger = None
    if chain_id and chain_name:
        chain_logger = ChainLogger.create(chain_name, chain_version, chain_id)

    def log(msg: str, level: str = "info"):
        if chain_logger:
            getattr(chain_logger.worker, level)(msg)

    return log


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
    chain_name: Optional[str] = None,
    chain_version: int = 1,
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
        chain_name: Chain name for logging
        chain_version: Chain version for logging

    Returns:
        Workflow ID
    """
    log = _get_log_func(chain_name, chain_version, chain_id)
    log(f"Creating workflow record: {workflow_name} (prompt: {prompt_id})")

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
            log(f"✓ Created workflow record: {workflow_record.id}")
            return workflow_record.id

    except Exception as e:
        log(f"Failed to create workflow record: {e}", "error")
        raise


@activity.defn
async def update_chain_status_activity(
    chain_id: str,
    status: str,
    current_level: Optional[int] = None,
    error_message: Optional[str] = None,
    chain_name: Optional[str] = None,
    chain_version: int = 1,
) -> None:
    """
    Activity: Update chain status in database

    Args:
        chain_id: Chain ID
        status: New status
        current_level: Optional current level
        error_message: Optional error message
        chain_name: Chain name for logging
        chain_version: Chain version for logging
    """
    log = _get_log_func(chain_name, chain_version, chain_id)
    log(f"Updating chain {chain_id} status to: {status}")

    try:
        with get_session() as session:
            update_chain_status(
                session=session,
                chain_id=chain_id,
                status=status,
                current_level=current_level,
                error_message=error_message
            )
            log(f"✓ Updated chain status")

        # Publish completion/failure events to Redis for SSE subscribers
        if status == "completed":
            await publish_chain_event(
                chain_id=chain_id,
                event={
                    "type": "chain_completed",
                    "chain_id": chain_id,
                }
            )
            log(f"Published chain_completed event for chain {chain_id}")
        elif status == "failed":
            await publish_chain_event(
                chain_id=chain_id,
                event={
                    "type": "chain_failed",
                    "chain_id": chain_id,
                    "error": error_message,
                }
            )
            log(f"Published chain_failed event for chain {chain_id}")

    except Exception as e:
        log(f"Failed to update chain status: {e}", "error")
        # Don't fail workflow for status update failures


@activity.defn
async def publish_level_wait_event(
    chain_id: str,
    level_num: int,
    event_type: str,  # "started" or "ended"
    wait_seconds: int = 0,
    skipped: bool = False,
) -> None:
    """Publish level wait SSE events."""
    try:
        if event_type == "started":
            await publish_chain_event(chain_id, {
                "type": "level_wait_started",
                "level_num": level_num,
                "wait_seconds": wait_seconds,
            })
        else:
            await publish_chain_event(chain_id, {
                "type": "level_wait_ended",
                "level_num": level_num,
                "skipped": skipped,
            })
    except Exception:
        pass  # Fire and forget


@activity.defn
async def update_workflow_status_activity(
    workflow_id: str,
    status: str,
    error_message: Optional[str] = None,
    chain_name: Optional[str] = None,
    chain_version: int = 1,
    chain_id: Optional[str] = None,
) -> None:
    """
    Activity: Update workflow status in database

    Args:
        workflow_id: Workflow ID
        status: New status
        error_message: Optional error message
        chain_name: Chain name for logging
        chain_version: Chain version for logging
        chain_id: Chain ID for logging
    """
    log = _get_log_func(chain_name, chain_version, chain_id)
    log(f"Updating workflow {workflow_id} status to: {status} (error: {error_message[:200] if error_message else None})")

    try:
        with get_session() as session:
            update_workflow_status(
                session=session,
                workflow_id=workflow_id,
                status=status,
                error_message=error_message
            )
            log(f"✓ Updated workflow status")

    except Exception as e:
        log(f"Failed to update workflow status: {e}", "error")
        # Don't fail workflow for status update failures


@activity.defn
async def publish_step_completed_activity(
    chain_id: str,
    step_id: str,
    chain_name: Optional[str] = None,
    chain_version: int = 1,
    artifact_id: Optional[str] = None,
) -> None:
    """
    Activity: Publish step_completed event to Redis

    Args:
        chain_id: Chain ID
        step_id: Step ID that completed
        chain_name: Chain name for logging
        chain_version: Chain version for logging
        artifact_id: Optional artifact ID for the step output
    """
    log = _get_log_func(chain_name, chain_version, chain_id)
    try:
        event = {
            "type": "step_completed",
            "chain_id": chain_id,
            "step_id": step_id,
        }
        if artifact_id:
            event["artifact_id"] = artifact_id

        await publish_chain_event(chain_id=chain_id, event=event)
        log(f"Published step_completed event for {step_id} in chain {chain_id} (artifact: {artifact_id})")
    except Exception as e:
        log(f"Failed to publish step_completed event: {e}", "error")
        # Don't fail workflow for event publish failures


@activity.defn
async def get_workflow_artifacts(
    workflow_id: str,
    chain_name: Optional[str] = None,
    chain_version: int = 1,
    chain_id: Optional[str] = None,
) -> list[str]:
    """
    Activity: Get artifact IDs for a workflow

    Args:
        workflow_id: Workflow ID
        chain_name: Chain name for logging
        chain_version: Chain version for logging
        chain_id: Chain ID for logging

    Returns:
        List of artifact IDs (returns ["latest"] if only latest needed)
    """
    log = _get_log_func(chain_name, chain_version, chain_id)
    log(f"Getting artifacts for workflow: {workflow_id}")

    try:
        with get_session() as session:
            workflow_record = get_workflow(session, workflow_id)
            if not workflow_record or not workflow_record.latest_artifact_id:
                log(f"No artifacts found for workflow {workflow_id}", "warning")
                return []

            # Return the latest artifact ID
            return [workflow_record.latest_artifact_id]

    except Exception as e:
        log(f"Failed to get workflow artifacts: {e}", "error")
        return []


@activity.defn
async def save_executed_definition_activity(
    chain_id: str,
    executed_definition: Dict[str, Any],
    chain_name: Optional[str] = None,
    chain_version: int = 1,
) -> None:
    """
    Activity: Save the executed definition (with actual parameters) to the chain.

    Called after chain completion to persist the final state including
    any parameter updates that were made during execution via signals.

    Args:
        chain_id: Chain ID
        executed_definition: Final chain definition with actual executed parameters
        chain_name: Chain name for logging
        chain_version: Chain version for logging
    """
    log = _get_log_func(chain_name, chain_version, chain_id)
    log(f"Saving executed definition for chain {chain_id}")

    try:
        with get_session() as session:
            result = save_executed_definition(
                session=session,
                chain_id=chain_id,
                executed_definition=executed_definition,
            )
            if result:
                log(f"✓ Saved executed definition for chain {chain_id}")
            else:
                log(f"Chain {chain_id} not found when saving executed definition", "warning")

    except Exception as e:
        log(f"Failed to save executed definition: {e}", "error")
        # Don't fail the workflow for this - it's a nice-to-have
