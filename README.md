# ComfyAutomate

**Orchestrate multi-step ComfyUI workflows with approvals, retries, and distributed GPU load balancing.**

ComfyAutomate turns ComfyUI into a production-ready workflow engine. Chain multiple workflows together, add human approval gates, automatically retry failed steps, and distribute work across multiple GPU servers.

## Features

- **Chain Workflows** - Define multi-step pipelines in YAML with automatic dependency resolution
- **Approval Gates** - Pause execution for human review, reject and regenerate with new parameters
- **Distributed Load Balancing** - Automatically route work to the least busy GPU server
- **Durable Execution** - Workflows survive crashes and restarts (powered by Temporal)
- **Real-time Progress** - SSE events for live updates in your UI
- **CLI Tool** - Execute and monitor chains from the command line

## Quick Start

### Prerequisites

- Python 3.10+
- [Temporal](https://docs.temporal.io/cli#install) (for durable workflow execution)
- Redis (for real-time events)
- At least one ComfyUI server

### Installation

```bash
# Clone the repo
git clone https://github.com/yourusername/comfyautomate.git
cd comfyautomate

# Install dependencies
uv sync

# Copy config and edit with your servers
cp config.yaml.example config.yaml
```

### Start Services

```bash
# Terminal 1: Start Temporal server
temporal server start-dev

# Terminal 2: Start the worker
python core/worker.py

# Terminal 3: Start the gateway
python core/main.py
```

### Execute a Chain

```bash
# Using the CLI
comfy-chain execute chains/image-edit-to-video-pipeline.yaml \
  --param prompt="A dragon breathing fire"

# Or via API
curl -X POST http://localhost:8001/chains/execute \
  -H "Content-Type: application/json" \
  -d @chains/image-edit-to-video-pipeline.yaml
```

## Chain Definition

Chains are defined in YAML and support Jinja2 templating:

```yaml
name: image-to-video
description: Generate image then convert to video

steps:
  - id: generate_image
    workflow: flux_dev
    parameters:
      prompt: "{{ prompt }}"
      seed: 42

  - id: create_video
    workflow: wan_i2v
    depends_on: [generate_image]
    requires_approval: true
    parameters:
      input_image: "{{ generate_image.output.image }}"
```

### Key Features

- **Dependencies** - `depends_on` ensures steps run in order
- **Parallel Execution** - Independent steps run simultaneously
- **Approvals** - `requires_approval: true` pauses for human review
- **Template Variables** - Reference outputs from previous steps with `{{ step_id.output.* }}`
- **Conditional Steps** - Skip steps based on conditions

## Approval Flow

When a step has `requires_approval: true`:

1. Workflow pauses after the step completes
2. User reviews the output (image/video) via the approval UI
3. **Approve** - Continues to next step
4. **Reject** - Regenerates with new parameters you provide

This enables iterative refinement without restarting the entire chain.

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Gateway   │────▶│   Temporal  │────▶│   Worker    │
│  (FastAPI)  │     │   Server    │     │             │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                               │
                    ┌──────────────────────────┼──────────────────────────┐
                    ▼                          ▼                          ▼
             ┌─────────────┐           ┌─────────────┐           ┌─────────────┐
             │  ComfyUI 1  │           │  ComfyUI 2  │           │  ComfyUI N  │
             │   (GPU)     │           │   (GPU)     │           │   (GPU)     │
             └─────────────┘           └─────────────┘           └─────────────┘
```

- **Gateway** - REST API for submitting chains and querying status
- **Temporal** - Durable workflow orchestration (handles retries, state persistence)
- **Worker** - Executes workflow steps on ComfyUI servers
- **Load Balancer** - Routes to server with shortest queue

## Configuration

Edit `config.yaml` to add your ComfyUI servers:

```yaml
servers:
  - name: local
    provider: comfyui
    address: localhost
    port: 8188

  - name: remote-gpu
    provider: comfyui
    address: gpu.example.com
    port: 8188
```

## Workflow Templates

Place your ComfyUI workflow JSON files in `templates/`. The system automatically generates override files that define which parameters are exposed.

```
templates/
├── flux_dev.json              # ComfyUI workflow export
├── flux_dev_overrides.json    # Auto-generated parameter definitions
├── wan_i2v.json
└── wan_i2v_overrides.json
```

## CLI Commands

```bash
# Execute a chain
comfy-chain execute chains/my-chain.yaml --param key=value

# List available workflows
comfy-chain workflows list

# Check chain status
comfy-chain status <chain-id>
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `POST /chains/execute` | Execute a chain |
| `GET /chains/status/{id}` | Get chain status |
| `GET /chains/result/{id}` | Get chain results |
| `GET /chains/events?chain_id={id}` | SSE stream for real-time updates |
| `POST /approval/{token}/approve` | Approve a pending step |
| `POST /approval/{token}/reject` | Reject and regenerate |

## License

MIT
