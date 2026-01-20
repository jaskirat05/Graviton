"""
Activity: Create execution log file
"""

import sys
from pathlib import Path
from typing import Dict, Any

from temporalio import activity

# Add parent to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from temporal_gateway.observability import create_log_from_history


@activity.defn
async def create_execution_log(
    prompt_id: str,
    server_address: str,
    workflow_def: Dict[str, Any],
    history_data: Dict[str, Any]
) -> str:
    """
    Activity: Create execution log file from history

    Args:
        prompt_id: ComfyUI prompt ID
        server_address: Server address
        workflow_def: Original workflow definition
        history_data: ComfyUI history data

    Returns:
        Path to log file
    """
    activity.logger.info(f"Creating log for prompt_id: {prompt_id}")

    try:
        # Use existing log creation
        log_path = create_log_from_history(
            prompt_id=prompt_id,
            server_address=server_address,
            workflow=workflow_def,
            history_data=history_data
        )

        activity.logger.info(f"Log created: {log_path}")
        return str(log_path)

    except Exception as e:
        activity.logger.error(f"Failed to create log: {e}")
        return ""
