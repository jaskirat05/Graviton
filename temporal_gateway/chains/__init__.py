"""
Chain System

Provides tools for defining, validating, and executing workflow chains.

Usage:
    from temporal_gateway.chains import load_chain_from_dict, create_execution_graph, ChainEngine
    from temporalio.client import Client

    # Define chain at runtime
    chain_def = {
        "name": "my_chain",
        "steps": [
            {"id": "step1", "workflow": "generate_image", "parameters": {...}}
        ]
    }

    # Load and create execution graph
    chain = load_chain_from_dict(chain_def)
    graph = create_execution_graph(chain)

    # Execute via Chain Engine
    temporal_client = await Client.connect("localhost:7233")
    engine = ChainEngine(temporal_client)
    chain_id = await engine.execute_chain(graph)
    print(f"Chain started: {chain_id}")
"""

# Models
from .models import (
    ChainDefinition,
    ChainStepDefinition,
    StepResult,
    ChainExecutionResult,
    ExecutionGraph,
    StepNode,
)

# Service functions (includes exceptions)
from .service import (
    load_chain,
    load_chain_from_dict,
    create_execution_graph,
    validate_chain,
    discover_chains,
    resolve_templates,
    resolve_step_parameters,
    evaluate_condition,
    evaluate_step_condition,
    build_execution_context,
    ChainValidationError,
    TemplateResolutionError,
)

# Engine
from .engine import ChainEngine

__all__ = [
    # Models
    "ChainDefinition",
    "ChainStepDefinition",
    "StepResult",
    "ChainExecutionResult",
    "ExecutionGraph",
    "StepNode",

    # Service functions
    "load_chain",
    "load_chain_from_dict",
    "create_execution_graph",
    "validate_chain",
    "discover_chains",
    "resolve_templates",
    "resolve_step_parameters",
    "evaluate_condition",
    "evaluate_step_condition",
    "build_execution_context",

    # Exceptions
    "ChainValidationError",
    "TemplateResolutionError",

    # Engine
    "ChainEngine",
]
