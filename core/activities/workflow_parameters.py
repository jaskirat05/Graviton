"""
Activity: Apply workflow parameters
"""

import sys
from pathlib import Path
from typing import Dict, Any, Optional

from temporalio import activity

# Add parent to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from core.observability.chain_logger import ChainLogger


@activity.defn
async def apply_workflow_parameters(
    workflow_name: str,
    parameters: Dict[str, Any],
    chain_name: Optional[str] = None,
    chain_version: int = 1,
    chain_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Activity: Apply parameters to workflow and return workflow JSON

    Args:
        workflow_name: Name of the workflow
        parameters: Parameters to apply
        chain_name: Chain name for logging
        chain_version: Chain version for logging
        chain_id: Chain ID for logging

    Returns:
        Workflow JSON with parameters applied
    """
    chain_logger = None
    if chain_id and chain_name:
        chain_logger = ChainLogger.create(chain_name, chain_version, chain_id)

    def log(msg: str, level: str = "info"):
        if chain_logger:
            getattr(chain_logger.worker, level)(msg)

    # Lazy import to avoid circular dependency
    from core.workflow_registry import get_registry

    log(f"Applying parameters to workflow: {workflow_name}")

    try:
        registry = get_registry()
        workflow_json = registry.apply_overrides(workflow_name, parameters)

        log(f"Parameters applied successfully")
        return workflow_json

    except Exception as e:
        log(f"Failed to apply parameters: {e}", "error")
        raise
