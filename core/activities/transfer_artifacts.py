"""
Activity: Transfer artifacts from local storage to target server
"""

import sys
from pathlib import Path
from typing import List, Optional

from temporalio import activity

# Add parent to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from core.clients.comfy import ComfyUIClient
from core.database import (
    get_session,
    get_latest_artifact,
    create_transfer,
    update_transfer_status,
)
from core.database.crud.artifact import get_artifact
from core.observability.chain_logger import ChainLogger


@activity.defn
async def transfer_artifacts_from_storage(
    source_workflow_id: str,
    target_server: str,
    artifact_ids: List[str],
    target_workflow_id: str = None,
    chain_name: Optional[str] = None,
    chain_version: int = 1,
    chain_id: Optional[str] = None,
) -> list[str]:
    """
    Activity: Transfer artifacts from local storage to target server's input directory

    NEW BEHAVIOR: Instead of server-to-server transfer, we:
    1. Read artifacts from local database
    2. Load files from local storage
    3. Upload to target server

    This enables:
    - Human-in-the-loop workflows (edit artifacts before upload)
    - Single source of truth (local storage)
    - Resilience to server restarts

    Args:
        source_workflow_id: Source workflow ID (to fetch artifacts from DB)
        target_server: Target ComfyUI server address
        artifact_ids: List of artifact IDs to transfer (or ["latest"])
        target_workflow_id: Optional target workflow ID for linking transfer
        chain_name: Chain name for logging
        chain_version: Chain version for logging
        chain_id: Chain ID for logging

    Returns:
        List of filenames now available in target server's input/ directory
    """
    # Create chain logger if we have chain info
    chain_logger = None
    if chain_id and chain_name:
        chain_logger = ChainLogger.create(chain_name, chain_version, chain_id)

    def log(msg: str, level: str = "info"):
        if chain_logger:
            getattr(chain_logger.worker, level)(msg)

    log(f"Transferring {len(artifact_ids)} artifact(s) from workflow {source_workflow_id} to {target_server}")

    try:
        target_client = ComfyUIClient(target_server, chain_logger=chain_logger)
        transferred_filenames = []

        with get_session() as session:
            for artifact_id in artifact_ids:
                # Handle special "latest" keyword
                if artifact_id == "latest":
                    artifact = get_latest_artifact(session, source_workflow_id)
                else:
                    artifact = get_artifact(session, artifact_id)

                if not artifact:
                    log(f"Artifact {artifact_id} not found, skipping")
                    continue

                # Create transfer record
                transfer = create_transfer(
                    session=session,
                    artifact_id=artifact.id,
                    source_workflow_id=source_workflow_id,
                    target_server=target_server,
                    target_workflow_id=target_workflow_id,
                    target_subfolder=artifact.subfolder,
                    status="uploading"
                )

                try:
                    # Read file from local storage
                    local_path = Path(artifact.local_path)
                    if not local_path.exists():
                        raise FileNotFoundError(f"Local file not found: {local_path}")

                    file_data = local_path.read_bytes()
                    log(f"Uploading: {artifact.filename} from local storage to {target_server}/input/")

                    # Upload to target server's input directory
                    upload_result = await target_client.upload_file(
                        file_data=file_data,
                        filename=artifact.filename,  # Use original filename
                        subfolder=artifact.subfolder,
                        overwrite=True
                    )

                    transferred_filenames.append(artifact.filename)
                    log(f"✓ Uploaded: {artifact.filename} ({len(file_data)} bytes)")

                    # Update transfer status
                    update_transfer_status(session, transfer.id, "completed")

                except Exception as upload_error:
                    log(f"Failed to upload artifact {artifact.id}: {upload_error}", "error")
                    update_transfer_status(session, transfer.id, "failed", str(upload_error))
                    raise

        await target_client.close()

        log(f"Successfully transferred {len(transferred_filenames)} file(s)")
        return transferred_filenames

    except Exception as e:
        log(f"Failed to transfer files: {e}", "error")
        raise


