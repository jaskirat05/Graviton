"""
Activity: Evaluate chain conditions
"""

from typing import Dict, Any, Optional

from temporalio import activity

from core.observability.chain_logger import ChainLogger


@activity.defn
async def evaluate_chain_condition(
    condition: str,
    step_results: Dict[str, Any],
    chain_name: Optional[str] = None,
    chain_version: int = 1,
    chain_id: Optional[str] = None,
) -> bool:
    """
    Activity: Evaluate a chain step condition

    Args:
        condition: Jinja2 condition expression
        step_results: Previous step results
        chain_name: Chain name for logging
        chain_version: Chain version for logging
        chain_id: Chain ID for logging

    Returns:
        True if condition passes, False otherwise
    """
    chain_logger = None
    if chain_id and chain_name:
        chain_logger = ChainLogger.create(chain_name, chain_version, chain_id)

    def log(msg: str, level: str = "info"):
        if chain_logger:
            getattr(chain_logger.worker, level)(msg)

    log(f"Evaluating condition: {condition}")

    try:
        from core.chains.service import build_execution_context, evaluate_condition

        context = build_execution_context(step_results)
        result = evaluate_condition(condition, context)

        log(f"Condition evaluated to: {result}")
        return result

    except Exception as e:
        log(f"Failed to evaluate condition: {e}", "error")
        raise
