# Graviton

**Orchestrate multi-step ComfyUI workflows with approvals, retries, and distributed GPU load balancing.**

Graviton turns ComfyUI into a production-ready workflow engine. Chain multiple workflows together, add human approval gates, automatically retry failed steps, and distribute work across multiple GPU servers.


https://github.com/user-attachments/assets/75bcb96e-44cb-43cd-8827-afa0c662dcea


## Features

- **Chain Workflows** - Define multi-step pipelines with automatic dependency resolution
- **Visual Editor** - Drag-and-drop workflow builder with real-time progress
- **Approval Gates** - Pause execution for human review, reject and regenerate with new parameters
- **Distributed Load Balancing** - Automatically route work to the least busy GPU server
- **Durable Execution** - Workflows survive crashes and restarts
- **Real-time Progress** - Live updates showing current node execution

## Quick Start

### Prerequisites

- Docker & Docker Compose
- At least one ComfyUI server running

### Step 1: Clone & Setup

```bash
git clone https://github.com/jaskirat05/graviton.git
cd graviton
cp .env.example .env
cp config.yaml.example config.yaml
```

### Step 2: Setup ComfyUI

Copy `graviton/folder_paths.py` to your ComfyUI installation directory:

```bash
cd graviton
cp folder_paths.py /path/to/ComfyUI/
```

This enables Graviton to sync workflows from your ComfyUI server.

### Step 3: Add Your Workflows

Export your ComfyUI workflows (API format) and place them in your **ComfyUI server's** `models/templates/` directory:

```
/path/to/ComfyUI/models/templates/
├── my_workflow.json
├── another_workflow.json
└── ...
```

Graviton will automatically sync these workflows from your ComfyUI server.

### Step 4: Configure

Edit `config.yaml` with your ComfyUI server address (see config file for examples).

### Step 5: Start

```bash
docker compose up
```

That's it! Open http://localhost:3000 to access the visual editor.

### Development mode (bind mounts, no rebuild for code edits)

Use the dev override to mount source code into containers:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

This runs the frontend in `next dev` mode and bind-mounts backend code so edits are reflected without rebuilding images.

## Workflow Requirements

For best compatibility, your ComfyUI workflows should follow these guidelines:

### Outputs
- **Single output per workflow** - Each workflow should have one primary output
- **Use default save nodes** - Use ComfyUI's built-in `SaveImage` or `SaveVideo` nodes

### Inputs
- **Recommended** - Use ComfyUI's default `LoadImage` and `LoadVideo` nodes
- **Supported** - Custom nodes for image/video input work but are not recommended

## Customizing Editable Parameters

When Graviton syncs a workflow, it auto-generates an `_overrides.json` file in the `templates/` directory:

```
graviton/templates/
├── my_workflow.json
├── my_workflow_overrides.json    # Auto-generated
```

To customize which parameters are editable in the UI:

1. Open `my_workflow_overrides.json`
2. Delete any parameters you don't want to be editable
3. The remaining parameters will appear in the visual editor

## Validating Workflows

To check if a workflow will work on a specific ComfyUI server:

1. Open the visual editor
2. Add your workflow node
3. Select a server from the dropdown
4. Click **Validate**

This checks if the server has all required custom nodes installed.

## Configuration

### Local ComfyUI (same machine)

```yaml
servers:
  - name: local
    provider: comfyui
    address: host.docker.internal  # Works on Windows/Mac/Linux
    port: 8188
```

### Remote ComfyUI

Use Cloudflare Tunnel or ngrok to expose your remote ComfyUI:

```bash
# On remote machine
cloudflared tunnel --url http://localhost:8188
```

```yaml
servers:
  - name: cloud-gpu
    provider: comfyui
    address: random-name.trycloudflare.com
    port: 443
    ssl: true
```

See `config.yaml.example` for more options.

## Approval Flow

When a step has approval enabled:

1. Workflow pauses after the step completes
2. User reviews the output (image/video) in the UI
3. **Approve** - Continues to next step
4. **Reject** - Regenerates with new parameters

This enables iterative refinement without restarting the entire chain.

## License

MIT
