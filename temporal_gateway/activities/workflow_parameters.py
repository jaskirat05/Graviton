"""
Activity: Apply workflow parameters
"""

import sys
from pathlib import Path
from typing import Dict, Any

from temporalio import activity

# Add parent to path
sys.path.append(str(Path(__file__).parent.parent.parent))


@activity.defn
async def apply_workflow_parameters(
    workflow_name: str,
    parameters: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Activity: Apply parameters to workflow and return workflow JSON

    Args:
        workflow_name: Name of the workflow
        parameters: Parameters to apply

    Returns:
        Workflow JSON with parameters applied
    """
    # Lazy import to avoid circular dependency
    from temporal_gateway.registry import get_registry

    activity.logger.info(f"Applying parameters to workflow: {workflow_name}")

    try:
        registry = get_registry()
        workflow_json = registry.apply_overrides(workflow_name, parameters)

        activity.logger.info(f"Parameters applied successfully")
        return workflow_json

    except Exception as e:
        activity.logger.error(f"Failed to apply parameters: {e}")
        raise
