"""
Chain Service Layer

Provides convenient functions for loading, validating, and working with chains.
"""

import sys
from pathlib import Path
from typing import List, Optional, Dict, Any

# Add parent to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from .interpreter import ChainInterpreter, ChainValidationError
from .models import ChainDefinition, ExecutionGraph, StepNode


# Global interpreter instance
_interpreter = ChainInterpreter()


def load_chain(yaml_path: str | Path) -> ChainDefinition:
    """
    Load a chain definition from a YAML file

    Args:
        yaml_path: Path to chain YAML file

    Returns:
        ChainDefinition object

    Raises:
        ChainValidationError: If chain file is invalid

    Example:
        chain = load_chain("chains/video_upscale_chain.yaml")
        print(f"Chain: {chain.name}")
        print(f"Steps: {len(chain.steps)}")
    """
    return _interpreter.load_from_yaml(Path(yaml_path))


def load_chain_from_dict(data: Dict[str, Any]) -> ChainDefinition:
    """
    Load a chain definition from a dictionary

    Args:
        data: Chain definition as dictionary

    Returns:
        ChainDefinition object

    Raises:
        ChainValidationError: If chain structure is invalid

    Example:
        chain_data = {
            "name": "my_chain",
            "steps": [
                {"id": "step1", "workflow": "generate_video", "parameters": {}}
            ]
        }
        chain = load_chain_from_dict(chain_data)
    """
    return _interpreter.load_from_dict(data)


def create_execution_graph(chain: ChainDefinition) -> ExecutionGraph:
    """
    Create an execution graph (NetworkX DAG) from a chain definition

    This validates the chain and builds a NetworkX-based execution graph
    for the new chain execution architecture.

    Args:
        chain: Chain definition

    Returns:
        ExecutionGraph ready for execution

    Raises:
        ChainValidationError: If chain is invalid (cycles, missing deps, etc.)

    Example:
        chain = load_chain("chains/my_chain.yaml")
        graph = create_execution_graph(chain)

        print(f"Execution levels: {graph.get_execution_levels()}")
    """
    # Validate chain
    _interpreter.validate_dependencies(chain)
    _interpreter.build_dag(chain)

    # Create execution graph
    graph = ExecutionGraph(chain_name=chain.name)

    # Add all steps as nodes
    for step in chain.steps:
        node = StepNode(
            step_id=step.id,
            workflow=step.workflow,
            parameters=step.parameters or {},
            dependencies=step.depends_on or [],
            requires_approval=step.requires_approval or False,
            approval_config=step.approval or {},  # FIX: Include approval configuration
            condition=step.condition,
            status="pending"
        )
        graph.add_node(node)

    # Validate DAG (no cycles)
    graph.validate_dag()

    return graph


def validate_chain(chain: ChainDefinition) -> Dict[str, Any]:
    """
    Validate a chain definition and return validation results

    Args:
        chain: Chain definition to validate

    Returns:
        Validation result dict with 'valid' (bool) and 'errors' (list) keys

    Example:
        chain = load_chain("chains/my_chain.yaml")
        result = validate_chain(chain)

        if result['valid']:
            print("Chain is valid!")
        else:
            print(f"Errors: {result['errors']}")
    """
    errors = []

    try:
        # Validate dependencies
        _interpreter.validate_dependencies(chain)

        # Try to build DAG (will fail if cycles exist)
        _interpreter.build_dag(chain)

        return {"valid": True, "errors": []}

    except ChainValidationError as e:
        errors.append(str(e))

    return {"valid": False, "errors": errors}


def discover_chains(directory: str | Path) -> List[Dict[str, Any]]:
    """
    Discover all chain YAML files in a directory

    Args:
        directory: Directory to search for chain files

    Returns:
        List of chain summaries with name, path, and basic info

    Example:
        chains = discover_chains("chains/")
        for chain_info in chains:
            print(f"{chain_info['name']}: {chain_info['description']}")
    """
    directory = Path(directory)

    if not directory.exists():
        return []

    chain_files = list(directory.glob("**/*.yaml")) + list(directory.glob("**/*.yml"))

    chains = []
    for yaml_file in chain_files:
        try:
            chain = load_chain(yaml_file)
            chains.append({
                "name": chain.name,
                "description": chain.description,
                "path": str(yaml_file),
                "steps": len(chain.steps),
                "metadata": chain.metadata
            })
        except Exception as e:
            # Skip invalid chain files
            continue

    return chains


def resolve_step_parameters(
    parameters: Dict[str, Any],
    step_results: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Resolve Jinja2 templates in step parameters using previous step results

    Args:
        parameters: Parameters that may contain templates
        step_results: Results from previous steps for context

    Returns:
        Resolved parameters

    Raises:
        TemplateResolutionError: If resolution fails

    Example:
        params = {"input_video": "{{ step1.output.video }}"}
        results = {"step1": {"output": {"video": "/path/out.mp4"}}}

        resolved = resolve_step_parameters(params, results)
        # {"input_video": "/path/out.mp4"}
    """
    context = _interpreter.build_execution_context(step_results)
    return _interpreter.resolve_templates(parameters, context)


def evaluate_step_condition(
    condition: str,
    step_results: Dict[str, Any]
) -> bool:
    """
    Evaluate a step condition using previous step results

    Args:
        condition: Jinja2 condition expression
        step_results: Results from previous steps

    Returns:
        True if condition passes, False otherwise

    Raises:
        TemplateResolutionError: If evaluation fails

    Example:
        condition = "{{ step1.output.score > 0.8 }}"
        results = {"step1": {"output": {"score": 0.9}}}

        should_execute = evaluate_step_condition(condition, results)
        # True
    """
    context = _interpreter.build_execution_context(step_results)
    return _interpreter.evaluate_condition(condition, context)
