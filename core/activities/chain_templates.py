"""
Activity: Resolve chain templates
"""

from typing import Dict, Any, Optional

from temporalio import activity

from core.observability.chain_logger import ChainLogger


@activity.defn
async def resolve_chain_templates(
    parameters: Dict[str, Any],
    step_results: Dict[str, Any],
    uploaded_inputs: Dict[str, str] = None,
    chain_name: Optional[str] = None,
    chain_version: int = 1,
    chain_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Activity: Resolve Jinja2 templates in parameters using step results and inputs

    Args:
        parameters: Parameters with templates like {{ step1.output.video }} or {{ inputs.key }}
        step_results: Previous step results for context
        uploaded_inputs: Uploaded input files mapping {key: filename_on_server}
        chain_name: Chain name for logging
        chain_version: Chain version for logging
        chain_id: Chain ID for logging

    Returns:
        Resolved parameters
    """
    chain_logger = None
    if chain_id and chain_name:
        chain_logger = ChainLogger.create(chain_name, chain_version, chain_id)

    def log(msg: str, level: str = "info"):
        if chain_logger:
            getattr(chain_logger.worker, level)(msg)

    log(f"Resolving templates in parameters")

    try:
        from core.chains.service import build_execution_context, resolve_templates

        context = build_execution_context(step_results)

        # Inject uploaded inputs into context for {{ inputs.key }} templates
        if uploaded_inputs:
            context["inputs"] = uploaded_inputs
            log(f"Injected {len(uploaded_inputs)} input(s) into template context")

        resolved = resolve_templates(parameters, context)

        log(f"Templates resolved successfully")
        return resolved

    except Exception as e:
        log(f"Failed to resolve templates: {e}", "error")
        raise
