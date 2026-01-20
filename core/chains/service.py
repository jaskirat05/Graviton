"""
Chain Service

Functions for loading, validating, and working with chain definitions.
"""

import yaml
from pathlib import Path
from typing import List, Dict, Any

from jinja2 import Environment, TemplateSyntaxError, UndefinedError
from simpleeval import simple_eval, NameNotDefined

from .models import ChainDefinition, ExecutionGraph, StepNode, StepResult


# Exceptions
class ChainValidationError(Exception):
    """Raised when chain definition is invalid"""
    pass


class TemplateResolutionError(Exception):
    """Raised when template resolution fails"""
    pass


# Module-level Jinja environment
_jinja_env = Environment(
    variable_start_string='{{',
    variable_end_string='}}',
    autoescape=False
)


# =============================================================================
# Chain Loading
# =============================================================================

def load_chain(yaml_path: str | Path) -> ChainDefinition:
    """Load chain definition from YAML file"""
    try:
        with open(yaml_path, 'r') as f:
            data = yaml.safe_load(f)
        return ChainDefinition(**data)
    except yaml.YAMLError as e:
        raise ChainValidationError(f"Invalid YAML: {e}")
    except FileNotFoundError:
        raise ChainValidationError(f"Chain file not found: {yaml_path}")
    except Exception as e:
        raise ChainValidationError(f"Invalid chain definition: {e}")


def load_chain_from_dict(data: Dict[str, Any]) -> ChainDefinition:
    """Load chain definition from dictionary"""
    try:
        return ChainDefinition(**data)
    except Exception as e:
        raise ChainValidationError(f"Invalid chain definition: {e}")


# =============================================================================
# Execution Graph
# =============================================================================

def create_execution_graph(chain: ChainDefinition) -> ExecutionGraph:
    """
    Create an execution graph (NetworkX DAG) from a chain definition.

    Validates dependencies and builds graph for execution.
    """
    # Validate dependencies exist
    step_ids = {step.id for step in chain.steps}
    for step in chain.steps:
        for dep in step.depends_on:
            if dep not in step_ids:
                raise ChainValidationError(
                    f"Step '{step.id}' depends on unknown step '{dep}'"
                )

    # Convert inputs using Pydantic's model_dump
    inputs_dict = {key: inp.model_dump() for key, inp in chain.inputs.items()}

    # Create graph
    graph = ExecutionGraph(chain_name=chain.name, inputs=inputs_dict)

    # Add nodes
    for step in chain.steps:
        node = StepNode(
            step_id=step.id,
            workflow=step.workflow,
            parameters=step.parameters or {},
            dependencies=step.depends_on or [],
            requires_approval=step.requires_approval or False,
            approval_config=step.approval or {},
            condition=step.condition,
            status="pending"
        )
        graph.add_node(node)

    # Validate no cycles
    graph.validate_dag()

    return graph


def validate_chain(chain: ChainDefinition) -> Dict[str, Any]:
    """Validate a chain definition, return {'valid': bool, 'errors': list}"""
    try:
        create_execution_graph(chain)
        return {"valid": True, "errors": []}
    except (ChainValidationError, ValueError) as e:
        return {"valid": False, "errors": [str(e)]}


def discover_chains(directory: str | Path) -> List[Dict[str, Any]]:
    """Discover all chain YAML files in a directory"""
    directory = Path(directory)
    if not directory.exists():
        return []

    chains = []
    for yaml_file in list(directory.glob("**/*.yaml")) + list(directory.glob("**/*.yml")):
        try:
            chain = load_chain(yaml_file)
            chains.append({
                "name": chain.name,
                "description": chain.description,
                "path": str(yaml_file),
                "steps": len(chain.steps),
                "metadata": chain.metadata
            })
        except Exception:
            continue

    return chains


# =============================================================================
# Template Resolution
# =============================================================================

def resolve_templates(parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Resolve Jinja2 templates in parameters.

    Example:
        params = {"input": "{{ step1.output.video }}"}
        context = {"step1": {"output": {"video": "out.mp4"}}}
        resolve_templates(params, context)  # {"input": "out.mp4"}
    """
    resolved = {}
    for key, value in parameters.items():
        try:
            resolved[key] = _resolve_value(value, context)
        except (TemplateSyntaxError, UndefinedError) as e:
            raise TemplateResolutionError(f"Failed to resolve '{key}': {e}")
    return resolved


def _resolve_value(value: Any, context: Dict[str, Any]) -> Any:
    """Recursively resolve templates in a value"""
    if isinstance(value, str):
        if '{{' in value and '}}' in value:
            template = _jinja_env.from_string(value)
            result = template.render(**context)

            # Convert to number if possible
            if result.isdigit():
                return int(result)
            try:
                return float(result)
            except ValueError:
                return result
        return value

    elif isinstance(value, dict):
        return {k: _resolve_value(v, context) for k, v in value.items()}

    elif isinstance(value, list):
        return [_resolve_value(item, context) for item in value]

    return value


def resolve_step_parameters(
    parameters: Dict[str, Any],
    step_results: Dict[str, Any]
) -> Dict[str, Any]:
    """Resolve templates using previous step results"""
    context = build_execution_context(step_results)
    return resolve_templates(parameters, context)


# =============================================================================
# Condition Evaluation
# =============================================================================

def evaluate_condition(condition: str, context: Dict[str, Any]) -> bool:
    """
    Evaluate a condition expression.

    Example:
        evaluate_condition("{{ step1.score > 0.8 }}", {"step1": {"score": 0.9}})
        # True
    """
    try:
        template = _jinja_env.from_string(condition)
        expression = template.render(**context)
        result = simple_eval(expression, names=context)

        if not isinstance(result, bool):
            raise TemplateResolutionError(
                f"Condition must be boolean, got {type(result)}: {result}"
            )
        return result

    except (TemplateSyntaxError, UndefinedError, NameNotDefined) as e:
        raise TemplateResolutionError(f"Failed to evaluate '{condition}': {e}")


def evaluate_step_condition(condition: str, step_results: Dict[str, Any]) -> bool:
    """Evaluate a step condition using previous step results"""
    context = build_execution_context(step_results)
    return evaluate_condition(condition, context)


# =============================================================================
# Context Building
# =============================================================================

def build_execution_context(step_results: Dict[str, StepResult]) -> Dict[str, Any]:
    """
    Build context dict for template resolution from step results.

    Handles both StepResult objects and dicts (Temporal serializes to dicts).
    """
    context = {}
    for step_id, result in step_results.items():
        if isinstance(result, dict):
            context[step_id] = {
                "output": result.get("output") or {},
                "parameters": result.get("parameters") or {},
                "status": result.get("status"),
            }
        else:
            context[step_id] = {
                "output": result.output or {},
                "parameters": result.parameters or {},
                "status": result.status,
            }
    return context
