"""
Activity: Download artifacts from ComfyUI and persist to database
"""

import sys
import uuid
from pathlib import Path
from typing import Dict, Any
from datetime import datetime

from temporalio import activity

# Add parent to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from temporal_gateway.config import get_storage_dir
from temporal_gateway.clients.comfy import ComfyUIClient
from temporal_gateway.database import get_session, create_artifact


@activity.defn
async def download_and_store_artifacts(
    workflow_id: str,
    server_address: str,
    output_files: list[Dict[str, Any]]
) -> list[Dict[str, Any]]:
    """
    Activity: Download artifacts from ComfyUI and ALWAYS store to database

    This activity is for workflows where artifact tracking is required.
    Use download_and_store_images() for ephemeral downloads without DB.

    Args:
        workflow_id: Workflow ID to link artifacts to (REQUIRED)
        server_address: Server address
        output_files: List of output file info from get_server_output_files

    Returns:
        List of stored artifact info with artifact IDs
    """
    activity.logger.info(f"Downloading and persisting {len(output_files)} artifact(s) for workflow {workflow_id}")

    try:
        client = ComfyUIClient(server_address)
        stored_artifacts = []

        with get_session() as session:
            for file_info in output_files:
                filename = file_info['filename']
                subfolder = file_info.get('subfolder', '')
                file_type = file_info.get('type', 'output')

                # Download file
                file_data = await client.download_file(
                    filename=filename,
                    subfolder=subfolder,
                    folder_type=file_type
                )

                # Store locally
                file_ext = Path(filename).suffix
                unique_filename = f"{uuid.uuid4().hex[:8]}{file_ext}"
                storage_dir = get_storage_dir()
                local_path = storage_dir / unique_filename

                local_path.write_bytes(file_data)

                # Detect file type
                detected_type = _detect_file_type(file_ext)
                file_format = file_ext.lstrip('.')

                # Save to database
                artifact = create_artifact(
                    session=session,
                    workflow_id=workflow_id,
                    filename=filename,
                    local_filename=unique_filename,
                    local_path=str(local_path),
                    file_type=detected_type,
                    file_format=file_format,
                    file_size=len(file_data),
                    node_id=file_info.get('node_id'),
                    subfolder=subfolder,
                    comfy_folder_type=file_type,
                    approval_status="auto_approved",
                )

                stored_artifacts.append({
                    "artifact_id": artifact.id,
                    "filename": unique_filename,
                    "original_filename": filename,
                    "local_path": str(local_path),
                    "node_id": file_info.get('node_id'),
                    "server_address": server_address,
                    "file_size": len(file_data),
                    "file_type": detected_type,
                    "file_format": file_format,
                    "downloaded_at": datetime.utcnow().isoformat(),
                })

                activity.logger.info(f"✓ Saved artifact to DB: {artifact.id} ({filename})")

        await client.close()
        activity.logger.info(f"Downloaded and persisted {len(stored_artifacts)} artifact(s)")
        return stored_artifacts

    except Exception as e:
        activity.logger.error(f"Failed to download and persist artifacts: {e}")
        raise  # Fail workflow if DB persistence fails


def _detect_file_type(file_ext: str) -> str:
    """Detect file type from extension"""
    ext = file_ext.lower().lstrip('.')
    if ext in ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp']:
        return 'image'
    elif ext in ['mp4', 'avi', 'mov', 'webm', 'mkv']:
        return 'video'
    elif ext in ['mp3', 'wav', 'ogg', 'flac']:
        return 'audio'
    else:
        return 'unknown'
