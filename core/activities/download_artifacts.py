"""
Activity: Download artifacts from ComfyUI and persist to database
"""

import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

from temporalio import activity

from core.config import get_storage_dir
from core.clients.comfy import ComfyUIClient
from core.database import get_session, create_artifact
from core.observability.chain_logger import ChainLogger


def _extract_output_files(history_data: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Extract output file info from ComfyUI history data.

    Args:
        history_data: ComfyUI history data with 'outputs' key

    Returns:
        List of output file info dicts
    """
    output_files = []
    outputs = history_data.get('outputs', {})

    for node_id, node_output in outputs.items():
        if 'images' in node_output:
            for img_info in node_output['images']:
                output_files.append({
                    "filename": img_info['filename'],
                    "subfolder": img_info.get('subfolder', ''),
                    "type": img_info.get('type', 'output'),
                    "node_id": node_id
                })

    return output_files


@activity.defn
async def download_and_store_artifacts(
    workflow_id: str,
    server_address: str,
    history_data: Dict[str, Any],
    chain_name: Optional[str] = None,
    chain_version: int = 1,
    chain_id: Optional[str] = None,
) -> list[Dict[str, Any]]:
    """
    Activity: Extract outputs from history, download from ComfyUI, and store to database.

    Args:
        workflow_id: Workflow ID to link artifacts to (REQUIRED)
        server_address: Server address
        history_data: ComfyUI history data with 'outputs' key
        chain_name: Chain name for logging
        chain_version: Chain version for logging
        chain_id: Chain ID for logging

    Returns:
        List of stored artifact info with artifact IDs
    """
    # Create chain logger if we have chain info
    chain_logger = None
    if chain_id and chain_name:
        chain_logger = ChainLogger.create(chain_name, chain_version, chain_id)

    def log(msg: str, level: str = "info"):
        if chain_logger:
            getattr(chain_logger.worker, level)(msg)

    # Extract output files from history
    output_files = _extract_output_files(history_data)
    log(f"Downloading {len(output_files)} artifact(s) for workflow {workflow_id}")

    if not output_files:
        log("No output files to download")
        return []

    try:
        client = ComfyUIClient(server_address, chain_logger=chain_logger)
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

                log(f"✓ Saved artifact to DB: {artifact.id} ({filename})")

        await client.close()
        log(f"Downloaded and persisted {len(stored_artifacts)} artifact(s)")
        return stored_artifacts

    except Exception as e:
        log(f"Failed to download and persist artifacts: {e}", "error")
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
