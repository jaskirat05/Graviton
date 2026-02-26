# Graviton

**Orchestrate multi-step ComfyUI workflows with approvals, retries, and distributed GPU load balancing.**

Graviton turns ComfyUI into a production-ready workflow engine. Chain multiple workflows together, add human approval gates, automatically retry failed steps, and distribute work across multiple GPU servers.


https://github.com/user-attachments/assets/75bcb96e-44cb-43cd-8827-afa0c662dcea


## Features

- **Workflow Chaining** - Build multi-step pipelines with dependencies
- **Visual Editor** - Drag-and-drop canvas for composing chains
- **Approval Gates** - Pause after a step, approve/reject, and continue
- **Server Registry** - Register worker machines from the frontend
- **Bridge-Based Execution** - Connect ComfyUI workers through Graviton Bridge
- **Durable Runs** - Temporal-backed orchestration survives restarts
- **Live Progress** - Real-time execution updates in the UI

## Quick Start

### Prerequisites

- Docker & Docker Compose
- At least one machine running ComfyUI

### Step 1: Install and run Graviton

```bash
git clone https://github.com/jaskirat05/graviton.git
cd graviton
cp .env.example .env
docker compose --profile infra --profile app up -d --build
```

Open http://localhost:3000 after startup.

### Step 2: Install bridge custom node on each ComfyUI machine

Install and follow setup from:

- https://github.com/jaskirat05/graviton-bridge

This installs the Graviton Bridge custom node in that ComfyUI instance.

### Step 3: Register the machine in Graviton UI

From the Graviton frontend, register your server in Server Settings.

On successful registration, Graviton provides a worker control secret key.

### Step 4: Set the secret key on the bridge machine

On that ComfyUI/Bridge machine, put the key in the bridge `.env`:

```env
GRAVITON_BRIDGE_CONTROL_HMAC_SECRET=<secret-from-graviton-ui>
```

### Development mode (bind mounts, no rebuild for code edits)

Use the dev override to mount source code into containers:

```bash
make dev
# or without make:
docker compose --profile infra --profile app -f docker-compose.yml -f docker-compose.dev.yml up
```

This runs the frontend in `next dev` mode and bind-mounts backend code so edits are reflected without rebuilding images.

### Packaging and release

Build local images:

```bash
make build
# or without make:
BACKEND_IMAGE=graviton-backend:dev FRONTEND_IMAGE=graviton-frontend:dev docker compose build graviton-worker graviton-frontend
```

Build and push versioned images:

```bash
make release VERSION=v0.1.0 REGISTRY=ghcr.io/<org>
# or without make:
BACKEND_IMAGE=ghcr.io/<org>/graviton-backend:v0.1.0 FRONTEND_IMAGE=ghcr.io/<org>/graviton-frontend:v0.1.0 docker compose build graviton-worker graviton-frontend
docker push ghcr.io/<org>/graviton-backend:v0.1.0
docker push ghcr.io/<org>/graviton-frontend:v0.1.0
```

## Workflow Requirements

All workflows must follow these rules:

### Outputs
- **Use Graviton save nodes only** - Do not use default ComfyUI save nodes
- **Exactly one save node per workflow** - Each workflow must end with a single Graviton save node

### Inputs
- **Use Graviton load nodes** - Inputs must be provided through Graviton load nodes
- **Multiple load nodes are supported** - You can use multiple Graviton load nodes in the same workflow

## Customizing Editable Parameters

When Graviton syncs a workflow, it stores workflow and override files under `registry_templates/`:

```
registry_templates/
├── workflows/
│   └── my_workflow.json
└── overrides/
    └── my_workflow.json    # Auto-generated overrides
```

To customize which parameters are editable in the UI:

1. Open `registry_templates/overrides/my_workflow.json`
2. Delete any parameters you don't want to be editable
3. The remaining parameters will appear in the visual editor

## Validating Workflows

To check if a workflow will work on a specific ComfyUI server:

1. Open the visual editor
2. Add your workflow node
3. Select a server from the dropdown
4. Click **Validate**

This checks if the server has all required custom nodes installed.

## Server Registration

Register worker machines directly from the frontend.
After registration, copy the issued secret key to that machine's Graviton Bridge `.env`.

## Approval Flow

When a step has approval enabled:

1. Workflow pauses after the step completes
2. User reviews the output (image/video) in the UI
3. **Approve** - Continues to next step
4. **Reject** - Regenerates with new parameters

This enables iterative refinement without restarting the entire chain.

## License

Free for non-commercial/public use under the license in [LICENSE](LICENSE).

Commercial use requires a separate license. See [COMMERCIAL_LICENSE.md](COMMERCIAL_LICENSE.md).
