"""
Activities: Database operations for chains and workflows
"""

import sys
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

from temporalio import activity

# Add parent to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from core.database import (
    get_session,
    create_workflow,
    create_artifact,
    update_chain_status,
    update_workflow_status,
    get_workflow,
    save_executed_definition,
)
from core.database.models import StepCache
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
async def create_cached_workflow_record_activity(
    workflow_name: str,
    chain_id: str,
    step_id: str,
    cache_key: str,
    artifact_id: Optional[str] = None,
    parameters: Optional[Dict[str, Any]] = None,
    chain_name: Optional[str] = None,
    chain_version: int = 1,
) -> str:
    """
    Activity: Create a workflow row for a cache-hit step so history panels can display it.

    Returns:
        Workflow ID
    """
    log = _get_log_func(chain_name, chain_version, chain_id)
    prompt_id = f"cache:{cache_key[:16]}"
    try:
        with get_session() as session:
            workflow_record = create_workflow(
                session=session,
                workflow_name=workflow_name,
                server_address="cache",
                prompt_id=prompt_id,
                chain_id=chain_id,
                step_id=step_id,
                workflow_definition=None,
                parameters=parameters,
                status="cached",
            )
            workflow_record.started_at = datetime.utcnow()
            workflow_record.completed_at = datetime.utcnow()
            if artifact_id:
                workflow_record.latest_artifact_id = artifact_id
            session.add(workflow_record)
            log(
                f"✓ Created cached workflow record: {workflow_record.id} "
                f"(step={step_id}, artifact={artifact_id})"
            )
            return workflow_record.id
    except Exception as e:
        log(f"Failed to create cached workflow record: {e}", "error")
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


def _detect_file_type_and_ext(filename: str, content_type: Optional[str]) -> tuple[str, Optional[str]]:
    ext = Path(filename).suffix.lower().lstrip(".") or None

    if content_type:
        lowered = content_type.lower()
        if lowered.startswith("image/"):
            return "image", (ext or lowered.split("/", 1)[1].split(";", 1)[0])
        if lowered.startswith("video/"):
            return "video", (ext or lowered.split("/", 1)[1].split(";", 1)[0])
        if lowered.startswith("audio/"):
            return "audio", (ext or lowered.split("/", 1)[1].split(";", 1)[0])

    if ext in {"png", "jpg", "jpeg", "gif", "webp", "bmp"}:
        return "image", ext
    if ext in {"mp4", "avi", "mov", "webm", "mkv"}:
        return "video", ext
    if ext in {"mp3", "wav", "ogg", "flac"}:
        return "audio", ext
    return "unknown", ext


@activity.defn
async def persist_step_output_artifact_activity(
    workflow_id: str,
    step_output: Optional[Dict[str, Any]] = None,
    chain_name: Optional[str] = None,
    chain_version: int = 1,
    chain_id: Optional[str] = None,
) -> Dict[str, Optional[str]]:
    """
    Persist step output artifact metadata (asset_id + asset_ref) in artifacts table.

    Returns:
        {"artifact_id": "<db artifact id>|None", "artifact_url": None}
    """
    log = _get_log_func(chain_name, chain_version, chain_id)
    asset_ref = step_output.get("asset_ref") if isinstance(step_output, dict) else None
    if not isinstance(asset_ref, dict):
        log(f"No asset_ref found for workflow {workflow_id}", "warning")
        return {"artifact_id": None, "artifact_url": None}

    asset_id = asset_ref.get("asset_id")
    if not isinstance(asset_id, str) or not asset_id.strip():
        log(f"asset_ref missing asset_id for workflow {workflow_id}", "warning")
        return {"artifact_id": None, "artifact_url": None}

    guessed_name = f"{asset_id.strip()}.bin"
    if isinstance(asset_ref.get("filename"), str) and asset_ref["filename"].strip():
        guessed_name = asset_ref["filename"]
    mime_type = asset_ref.get("mime_type")
    kind = asset_ref.get("kind")
    file_type, file_format = _detect_file_type_and_ext(
        guessed_name,
        mime_type if isinstance(mime_type, str) else None,
    )
    if file_type == "unknown" and isinstance(kind, str) and kind in {"image", "video", "audio"}:
        file_type = kind

    with get_session() as session:
        artifact = create_artifact(
            session=session,
            workflow_id=workflow_id,
            filename=guessed_name,
            file_type=file_type,
            local_filename=None,
            local_path=None,
            file_format=file_format,
            file_size=int(asset_ref.get("size_bytes") or 0),
            approval_status="auto_approved",
            extra_metadata={
                "asset_id": asset_id.strip(),
                "asset_ref": asset_ref,
            },
        )
        artifact_id = artifact.id

    log(f"Persisted artifact {artifact_id} for workflow {workflow_id} from asset_id {asset_id.strip()}")
    return {"artifact_id": artifact_id, "artifact_url": None}


@activity.defn
async def publish_step_completed_activity(
    chain_id: str,
    step_id: str,
    chain_name: Optional[str] = None,
    chain_version: int = 1,
    artifact_id: Optional[str] = None,
    artifact_url: Optional[str] = None,
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
        resolved_artifact_url = artifact_url
        if not resolved_artifact_url and artifact_id:
            with get_session() as session:
                from core.database.crud.artifact import get_artifact

                artifact = get_artifact(session, artifact_id)
                if artifact and isinstance(artifact.extra_metadata, dict):
                    source_url = artifact.extra_metadata.get("source_url")
                    if isinstance(source_url, str) and source_url.strip():
                        resolved_artifact_url = source_url.strip()

        event = {
            "type": "step_completed",
            "chain_id": chain_id,
            "step_id": step_id,
        }
        if artifact_id:
            event["artifact_id"] = artifact_id
        if resolved_artifact_url:
            event["artifact_url"] = resolved_artifact_url

        await publish_chain_event(chain_id=chain_id, event=event)
        log(
            f"Published step_completed event for {step_id} in chain {chain_id} "
            f"(artifact: {artifact_id}, url: {resolved_artifact_url})"
        )
    except Exception as e:
        log(f"Failed to publish step_completed event: {e}", "error")
        # Don't fail workflow for event publish failures


@activity.defn
async def publish_step_cached_activity(
    chain_id: str,
    step_id: str,
    chain_name: Optional[str] = None,
    chain_version: int = 1,
    artifact_id: Optional[str] = None,
    artifact_url: Optional[str] = None,
    cache_key: Optional[str] = None,
) -> None:
    """Publish step_cached event to Redis for frontend step-level cache visibility."""
    log = _get_log_func(chain_name, chain_version, chain_id)
    try:
        event: Dict[str, Any] = {
            "type": "step_cached",
            "chain_id": chain_id,
            "step_id": step_id,
        }
        if artifact_id:
            event["artifact_id"] = artifact_id
        if artifact_url:
            event["artifact_url"] = artifact_url
        if cache_key:
            event["cache_key"] = cache_key
        await publish_chain_event(chain_id=chain_id, event=event)
        log(f"Published step_cached event for {step_id} (artifact: {artifact_id})")
    except Exception as e:
        log(f"Failed to publish step_cached event: {e}", "error")


@activity.defn
async def get_step_cache_activity(
    execution_hash: str,
    chain_name: Optional[str] = None,
    chain_version: int = 1,
    chain_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Get cached step result by execution hash.

    Returns:
        Dict with cached data or None if missing.
    """
    log = _get_log_func(chain_name, chain_version, chain_id)
    try:
        with get_session() as session:
            row = session.get(StepCache, execution_hash)
            if not row:
                return None

            row.last_hit_at = datetime.utcnow()
            row.hit_count = (row.hit_count or 0) + 1
            session.add(row)

            artifact_url = None
            if row.artifact_id:
                artifact_url = f"/artifact-service/artifacts/{row.artifact_id}/download"

            log(
                f"Step cache hit for hash {execution_hash[:12]}... "
                f"(workflow={row.workflow_name}, artifact={row.artifact_id})"
            )
            return {
                "execution_hash": row.execution_hash,
                "structure_hash": row.structure_hash,
                "workflow_name": row.workflow_name,
                "runtime_fingerprint": row.runtime_fingerprint,
                "artifact_id": row.artifact_id,
                "artifact_url": artifact_url,
                "output_json": row.output_json,
                "step_parameters": row.step_parameters,
                "source_step_id": row.source_step_id,
                "source_chain_id": row.source_chain_id,
            }
    except Exception as e:
        log(f"Failed to read step cache: {e}", "error")
        return None


@activity.defn
async def upsert_step_cache_activity(
    execution_hash: str,
    structure_hash: str,
    workflow_name: str,
    runtime_fingerprint: str,
    output_json: Optional[Dict[str, Any]],
    artifact_id: Optional[str],
    step_parameters: Optional[Dict[str, Any]],
    source_step_id: Optional[str],
    source_chain_id: Optional[str],
    chain_name: Optional[str] = None,
    chain_version: int = 1,
    chain_id: Optional[str] = None,
) -> None:
    """Insert or update step cache entry."""
    log = _get_log_func(chain_name, chain_version, chain_id)
    try:
        with get_session() as session:
            row = session.get(StepCache, execution_hash)
            now = datetime.utcnow()
            if row is None:
                row = StepCache(
                    execution_hash=execution_hash,
                    structure_hash=structure_hash,
                    workflow_name=workflow_name,
                    runtime_fingerprint=runtime_fingerprint,
                    output_json=output_json,
                    artifact_id=artifact_id,
                    step_parameters=step_parameters,
                    source_step_id=source_step_id,
                    source_chain_id=source_chain_id,
                    created_at=now,
                    last_hit_at=now,
                    hit_count=0,
                )
            else:
                row.structure_hash = structure_hash
                row.workflow_name = workflow_name
                row.runtime_fingerprint = runtime_fingerprint
                row.output_json = output_json
                row.artifact_id = artifact_id
                row.step_parameters = step_parameters
                row.source_step_id = source_step_id
                row.source_chain_id = source_chain_id

            session.add(row)
            log(
                f"Upserted step cache {execution_hash[:12]}... "
                f"(workflow={workflow_name}, artifact={artifact_id})"
            )
    except Exception as e:
        log(f"Failed to upsert step cache: {e}", "error")


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
