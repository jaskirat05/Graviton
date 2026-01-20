# ComfyAutomate

A clean, modular system for automating ComfyUI workflows with load balancing, chain execution, and observability.

## Project Structure

```
comfyautomate/
├── temporal_gateway/      # FastAPI gateway with Temporal orchestration
│   ├── main.py           # App entry point
│   ├── worker.py         # Temporal worker
│   ├── registry.py       # Workflow template registry
│   ├── executors/        # Temporal workflow definitions
│   │   ├── comfy_executor.py    # Single workflow executor
│   │   └── chain_executor.py    # Chain orchestrator
│   ├── activities/       # Temporal activities
│   ├── chains/           # Chain system (DAG execution)
│   │   ├── models/       # Data models (ExecutionGraph, StepNode)
│   │   ├── interpreter.py # YAML parser & template resolver
│   │   ├── engine.py     # Execution interface
│   │   └── service.py    # Chain loading utilities
│   ├── clients/          # External service clients
│   │   ├── comfy/        # ComfyUI HTTP client
│   │   └── approval/     # Approval API routes
│   ├── core/             # Core business logic
│   │   ├── load_balancer.py   # Server selection
│   │   └── storage.py         # Image storage
│   ├── database/         # SQLAlchemy models
│   └── observability/    # Logging & monitoring
│
├── templates/            # ComfyUI workflow JSON templates
├── chains/              # Chain YAML definitions
├── tests/               # Test scripts
├── docs/                # Documentation
└── config.yaml          # Server configuration
```

## Quick Start

### 1. Install Dependencies

```bash
uv sync
```

### 2. Start Services

```bash
# Start Temporal server
temporal server start-dev

# Start Temporal worker
python temporal_gateway/worker.py

# Start Temporal gateway (port 8001)
python temporal_gateway/main.py
```

### 3. Execute Workflows via Chains

All workflow execution is done through chains (even single workflows are single-step chains):

```bash
# List available chains
curl http://localhost:8001/chains

# Execute a chain
curl -X POST http://localhost:8001/chains/my_chain/execute \
  -H "Content-Type: application/json" \
  -d '{"parameters": {"prompt": "A dragon flying"}}'

# Check status
curl http://localhost:8001/chains/status/{workflow_id}

# Get result
curl http://localhost:8001/chains/result/{workflow_id}
```

Temporal UI available at: `http://localhost:8233`

## Features

- **Durable Execution** - Workflows survive crashes via Temporal
- **Chain Execution** - Multi-step pipelines with DAG dependencies
- **Approval Workflows** - Human-in-the-loop with regeneration support
- **Load Balancing** - Automatically selects the best available GPU server
- **Automatic Logging** - Every execution is logged (JSONL format)

## Chain System

Chains define multi-step workflows as YAML:

```yaml
name: image-to-video
description: Generate image then convert to video
steps:
  - id: generate_image
    workflow: text_to_image
    parameters:
      prompt: "{{ prompt }}"

  - id: create_video
    workflow: image_to_video
    depends_on: [generate_image]
    parameters:
      input_image: "{{ generate_image.output.image }}"
```

Features:
- Jinja2 templates for passing outputs between steps
- Parallel execution of independent steps
- Conditional step execution
- Approval gates with regeneration

## Documentation

- [Architecture](docs/ARCHITECTURE.md) - System design and data flows
- [Logging Guide](docs/LOGGING.md) - Automatic logging explained
- [Edge Cases](temporal_gateway/chains/EDGE_CASES.md) - Chain execution edge cases

## Development

```bash
# Run tests
python test_chain_execution.py

# Check server health
curl http://localhost:8001/health

# View Temporal UI
open http://localhost:8233
```
