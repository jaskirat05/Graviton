"""
Activity: Upload local input files to ComfyUI server

Uploads files from the gateway server's local filesystem to ComfyUI's input directory.
Filenames are prefixed with chain_id to avoid conflicts.
"""

import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Dict, Any, Optional

from temporalio import activity

# Add parent to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from core.clients.comfy import ComfyUIClient
from core.observability.chain_logger import ChainLogger


def extract_basename(filename: str) -> str:
    """
    Extract just the filename from any path, handling both Unix and Windows paths.

    Args:
        filename: A filename that might contain path components

    Returns:
        Just the basename with no path components
    """
    # Try both path styles to handle any input
    posix_name = PurePosixPath(filename).name
    windows_name = PureWindowsPath(filename).name

    # Use the shorter one (the one that actually parsed the path)
    return posix_name if len(posix_name) <= len(windows_name) else windows_name


@activity.defn
async def upload_local_inputs(
    inputs: Dict[str, Dict[str, Any]],
    target_server: str,
    chain_id: str,
    chain_name: Optional[str] = None,
    chain_version: int = 1,
) -> Dict[str, str]:
    """
    Activity: Upload local files to ComfyUI server's input directory

    Filenames are prefixed with chain_id to avoid conflicts between chains.
    Any path components in filenames are stripped for cross-platform safety.

    Args:
        inputs: Dict of input definitions {key: {"source": path, "target": optional_filename}}
        target_server: Target ComfyUI server address
        chain_id: Chain ID used as filename prefix
        chain_name: Chain name for logging
        chain_version: Chain version for logging

    Returns:
        Dict mapping input key to the uploaded filename for use in workflow parameters
    """
    # Create chain logger if we have chain info
    chain_logger = None
    if chain_id and chain_name:
        chain_logger = ChainLogger.create(chain_name, chain_version, chain_id)

    def log(msg: str, level: str = "info"):
        if chain_logger:
            getattr(chain_logger.worker, level)(msg)

    log(f"Uploading {len(inputs)} local input(s) to {target_server}")

    uploaded_files = {}
    client = ComfyUIClient(target_server, chain_logger=chain_logger)

    try:
        for input_key, input_def in inputs.items():
            source_path = Path(input_def["source"])

            # Get target filename, strip any path components for safety
            raw_target = input_def.get("target") or source_path.name
            base_filename = extract_basename(raw_target)

            # Prefix with chain_id to avoid conflicts
            target_filename = f"{chain_id}_{base_filename}"

            # Resolve relative paths from project root
            if not source_path.is_absolute():
                project_root = Path(__file__).parent.parent.parent
                source_path = project_root / source_path

            if not source_path.exists():
                raise FileNotFoundError(f"Local input file not found: {source_path}")

            # Read file content
            file_data = source_path.read_bytes()
            log(f"Uploading '{input_key}': {source_path} -> {target_filename} ({len(file_data)} bytes)")

            # Upload to ComfyUI input/ directory (no subfolder)
            await client.upload_file(
                file_data=file_data,
                filename=target_filename,
                subfolder="",
                overwrite=True
            )

            uploaded_files[input_key] = target_filename
            log(f"Uploaded '{input_key}' as {target_filename}")

    finally:
        await client.close()

    log(f"Successfully uploaded {len(uploaded_files)} file(s)")
    return uploaded_files
