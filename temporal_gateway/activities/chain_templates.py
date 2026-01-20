"""
Activity: Resolve chain templates
"""

from typing import Dict, Any

from temporalio import activity


@activity.defn
async def resolve_chain_templates(
    parameters: Dict[str, Any],
    step_results: Dict[str, Any],
    uploaded_inputs: Dict[str, str] = None
) -> Dict[str, Any]:
    """
    Activity: Resolve Jinja2 templates in parameters using step results and inputs

    Args:
        parameters: Parameters with templates like {{ step1.output.video }} or {{ inputs.key }}
        step_results: Previous step results for context
        uploaded_inputs: Uploaded input files mapping {key: filename_on_server}

    Returns:
        Resolved parameters
    """
    activity.logger.info(f"Resolving templates in parameters")

    try:
        from temporal_gateway.chains.service import build_execution_context, resolve_templates

        context = build_execution_context(step_results)

        # Inject uploaded inputs into context for {{ inputs.key }} templates
        if uploaded_inputs:
            context["inputs"] = uploaded_inputs
            activity.logger.info(f"Injected {len(uploaded_inputs)} input(s) into template context")

        resolved = resolve_templates(parameters, context)

        activity.logger.info(f"Templates resolved successfully")
        return resolved

    except Exception as e:
        activity.logger.error(f"Failed to resolve templates: {e}")
        raise
