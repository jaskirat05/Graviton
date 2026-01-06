"""
Chain System

Provides tools for defining, validating, and executing workflow chains.

Usage:
    from temporal_gateway.chains import load_chain, create_execution_graph, ChainEngine
    from temporal_gateway.workflows import ChainExecutorWorkflow
    from temporalio.client import Client

    # Load chain definition
    chain = load_chain("chains/video_pipeline.yaml")

    # Create execution graph
    graph = create_execution_graph(chain)

    # Inspect parallel groups
    groups = graph.get_level_groups()
    print(f"Parallel execution groups: {groups}")

    # Execute via Chain Engine
    temporal_client = await Client.connect("localhost:7233")
    engine = ChainEngine(temporal_client)
    workflow_id = await engine.execute_chain(graph)
    print(f"Chain started: {workflow_id}")
"""

# Import all models from models/ package
from .models import (
    ChainDefinition,
    ChainStepDefinition,
    StepResult,
    ChainExecutionResult,
    ExecutionGraph,
    StepNode,
)

from .interpreter import (
    ChainInterpreter,
    ChainValidationError,
    TemplateResolutionError
)

from .service import (
    load_chain,
    load_chain_from_dict,
    create_execution_graph,
    validate_chain,
    discover_chains,
    resolve_step_parameters,
    evaluate_step_condition
)

from .engine import ChainEngine

__all__ = [
    # Models
    "ChainDefinition",
    "ChainStepDefinition",
    "StepResult",
    "ChainExecutionResult",
    "ExecutionGraph",
    "StepNode",

    # Interpreter
    "ChainInterpreter",
    "ChainValidationError",
    "TemplateResolutionError",

    # Service functions
    "load_chain",
    "load_chain_from_dict",
    "create_execution_graph",
    "validate_chain",
    "discover_chains",
    "resolve_step_parameters",
    "evaluate_step_condition",

    # Engine
    "ChainEngine",
]
