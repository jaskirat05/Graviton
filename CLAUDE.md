# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ComfyAutomate is a distributed GPU farm orchestration system for ComfyUI workflows. It provides two gateways:

1. **Original Gateway** (`gateway/`) - Simple FastAPI-based workflow execution with load balancing
2. **Temporal Gateway** (`temporal_gateway/`) - Durable workflow orchestration using Temporal.io with chain execution and approval workflows

## Common Commands

### Environment Setup

```bash
# Install dependencies
uv sync

# Activate virtual environment
source .venv/bin/activate
```

### Running Services

```bash
# Start original gateway (port 8000)
uv run run_gateway.py

# Start Temporal server (development mode)
temporal server start-dev
# UI available at http://localhost:8233

# Start Temporal worker
python temporal_gateway/worker.py

# Start Temporal gateway (port 8001)
python temporal_gateway/main.py
```

### Testing

```bash
# Test chain execution with approval flow
python test_chain_execution.py

# Test database operations
python test_database.py

# Test ComfyUI client
python test_comfy_client.py

# Test upload/download
python test_upload_download.py
```

## Architecture Overview

### Temporal Gateway Chain System

The chain execution system uses a DAG (Directed Acyclic Graph) architecture with NetworkX for managing complex workflow dependencies, approvals, and regenerations.

#### Key Components

**Chain Models** (`temporal_gateway/chains/models/`):
- `ExecutionGraph`: NetworkX-based DAG for managing step dependencies and subgraph operations
- `StepNode`: Individual execution unit with runtime state tracking
- `ChainDefinition`: YAML-based chain configuration
- `StepResult` / `ChainExecutionResult`: Execution outcomes

**Chain Interpreter** (`temporal_gateway/chains/interpreter.py`):
- Parses YAML chain definitions
- Validates dependencies and detects cycles
- Resolves Jinja2 templates in parameters (e.g., `{{ step1.output.video }}`)
- Evaluates conditional expressions
- Builds ExecutionGraph from ChainDefinition

**Chain Engine** (`temporal_gateway/chains/engine.py`):
- Executes chains via Temporal workflows
- Provides status queries and result retrieval
- Handles chain cancellation

**Workflow Layer** (`temporal_gateway/workflows/`):
- `ChainExecutorWorkflow`: Main workflow for chain execution
- Orchestrates step execution across parallel levels
- Manages approval flows and regenerations
- Creates child chains for subgraph regeneration

#### Chain Execution Flow

1. Load YAML chain definition → `ChainDefinition`
2. Interpreter validates and creates → `ExecutionGraph` (NetworkX DAG)
3. Graph analyzed for parallel execution levels using `nx.topological_generations()`
4. Engine submits to Temporal → `ChainExecutorWorkflow`
5. Workflow executes steps level-by-level
6. For approval steps: pause, wait for approval, handle rejection
7. On rejection: create subgraph from rejected step, spawn child chain
8. Child chain inherits context from parent

#### Subgraph Regeneration

When a step is rejected during approval:
1. `ExecutionGraph.create_subgraph(step_id)` creates new graph with:
   - The rejected step (with new parameters)
   - All descendants (steps that depend on it)
2. Subgraph becomes a child chain with fresh execution state
3. Parent chain waits for child chain completion
4. Child chain results merged back into parent context

### Database Schema

**Artifacts Table** (`temporal_gateway/database/artifacts.py`):
- Tracks all generated files (images, videos)
- Links artifacts to workflows and chains
- Supports approval workflows and artifact lifecycle

**Workflows Table**:
- Stores workflow execution metadata
- Links to artifacts and chains

**Chains Table**:
- Parent-child chain relationships
- Chain execution history
- Regeneration tracking

### Approval System

**Approval Flow** (`temporal_gateway/clients/approval/`):
- Steps marked with `requires_approval: true` pause execution
- Approval request stored in database with unique token
- User can approve or reject with new parameters
- Rejection triggers subgraph regeneration
- Max retries configurable per step

## Critical Implementation Details

### DAG and NetworkX Usage

The system uses NetworkX extensively for graph operations:

```python
# Get all descendants for regeneration
descendants = graph.get_descendants(step_id)  # Uses nx.descendants()

# Get ancestors for validation
ancestors = graph.get_ancestors(step_id)  # Uses nx.ancestors()

# Create subgraph for regeneration
subgraph = graph.create_subgraph(step_id)  # Uses graph.subgraph()

# Get parallel execution levels
levels = graph.get_execution_levels()  # Uses nx.topological_generations()

# Validate no cycles
graph.validate_dag()  # Uses nx.is_directed_acyclic_graph()
```

### Template Resolution

Parameters support Jinja2 templates that reference previous step outputs:

```yaml
steps:
  - id: generate_image
    workflow: text_to_image
    parameters:
      prompt: "A beautiful landscape"

  - id: create_video
    workflow: image_to_video
    depends_on: [generate_image]
    parameters:
      input_image: "{{ generate_image.output.image }}"
      duration: "{{ generate_image.parameters.duration * 2 }}"
```

Templates are resolved at runtime using `ChainInterpreter.resolve_templates()`.

### Edge Cases (Critical Reading)

See `temporal_gateway/chains/EDGE_CASES.md` for comprehensive documentation on:
- Diamond dependencies (shared descendants)
- Cross-branch dependencies
- Partial subgraph overlap
- Approval chain reactions
- Multiple artifacts per step
- Conditional step handling
- Concurrent regenerations
- Version tracking
- Cache invalidation

These edge cases drive the design of the ExecutionGraph and regeneration system.

### Temporal Workflow Patterns

**Activities** (`temporal_gateway/activities/`):
- `execute_comfy_workflow`: Execute workflow on ComfyUI server
- `request_approval`: Create approval request and wait
- `store_artifact`: Save files to database
- `transfer_artifact`: Move files between servers

**Workflows use**:
- Queries for status: `@workflow.query` decorators
- Signals for control: `@workflow.signal` decorators (approval decisions)
- Child workflows for regeneration: `workflow.execute_child_workflow()`
- Activity retries with exponential backoff

### File Organization

```
temporal_gateway/
├── chains/                 # Chain execution system
│   ├── models/            # Data models
│   │   ├── execution_graph.py    # NetworkX DAG
│   │   ├── chain_definition.py   # YAML models
│   │   ├── execution_result.py   # Results
│   │   └── child_chain.py        # Child chain metadata (to implement)
│   ├── interpreter.py     # YAML parser, template resolver
│   ├── engine.py          # Execution interface
│   └── EDGE_CASES.md      # Critical edge case documentation
├── workflows/             # Temporal workflows
│   └── chain/
│       └── workflow.py    # ChainExecutorWorkflow
├── activities/            # Temporal activities
│   ├── comfyui/          # ComfyUI execution
│   └── approval/         # Approval activities
├── clients/               # External service clients
│   ├── comfyui/          # ComfyUI API client
│   └── approval/         # Approval API routes
├── database/              # SQLAlchemy models
│   ├── artifacts.py      # Artifact storage
│   └── workflows.py      # Workflow tracking
├── main.py               # FastAPI gateway
└── worker.py             # Temporal worker
```

## Development Guidelines

### Working with Chains

When modifying chain execution logic:
1. Changes to graph operations go in `ExecutionGraph` class
2. Template resolution logic in `ChainInterpreter`
3. Execution orchestration in `ChainExecutorWorkflow`
4. Never modify running workflow code (Temporal versioning required)

### Adding New Step Types

1. Add workflow definition in ComfyUI
2. Define in YAML chain with proper dependencies
3. Ensure output structure matches expected template variables
4. Test template resolution with sample data

### Database Migrations

When modifying database models:
```bash
# Generate migration
alembic revision --autogenerate -m "Description"

# Apply migration
alembic upgrade head

# Rollback
alembic downgrade -1
```

### Debugging Chains

1. Check Temporal UI at http://localhost:8233 for workflow history
2. Query workflow status: `GET /chains/status/{workflow_id}`
3. Check artifact database: `temporal_gateway/data/artifacts.db`
4. View approval requests: `GET /approval/pending`
5. Examine step-by-step results in execution graph

## Important Patterns

### Temporal Workflow Determinism

Workflows must be deterministic - avoid:
- Random number generation
- Current time (use `workflow.now()` instead)
- Non-deterministic iterations
- External API calls (use activities instead)

### Artifact Transfer

Files generated on ComfyUI servers must be:
1. Stored in artifact database with metadata
2. Linked to source workflow and chain
3. Referenced by artifact_id (not file path) in downstream steps
4. Transferred between servers if needed using transfer activities

### Chain Context Building

The execution context for template resolution is built from step results:
```python
context = {
    "step_id": {
        "output": {...},      # Step outputs
        "parameters": {...},  # Resolved parameters
        "status": "completed"
    }
}
```

This context is passed to Jinja2 for template resolution.

## Known Limitations

- In-memory job tracking in original gateway (not persisted)
- Approval system assumes single approver (no multi-party approval)
- Artifact storage is local filesystem (not distributed)
- No automatic server discovery (manual registration required)
- Child chain depth not limited (potential infinite recursion if misconfigured)
