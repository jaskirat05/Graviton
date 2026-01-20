# Temporal Gateway for ComfyAutomate

GPU farm orchestration using Temporal for durable workflow execution.

## Quick Start

### 1. Start Temporal Server (Dev Mode)

```bash
temporal server start-dev
```

This starts:
- Temporal Server on `localhost:7233`
- Temporal UI on `http://localhost:8233`

### 2. Start Temporal Worker

```bash
python temporal_gateway/worker.py
```

The worker executes workflows and activities.

### 3. Start Temporal Gateway

```bash
python temporal_gateway/main.py
```

Gateway API runs on `http://localhost:8001`

### 4. Execute via Chains API

All workflow execution is done through chains (even single workflows are single-step chains):

```bash
# List available chains
curl http://localhost:8001/chains

# Execute a chain
curl -X POST http://localhost:8001/chains/my_chain/execute \
  -H "Content-Type: application/json" \
  -d '{"initial_parameters": {"prompt": "A dragon flying"}}'

# Check status
curl http://localhost:8001/chains/status/{workflow_id}

# Get result
curl http://localhost:8001/chains/result/{workflow_id}
```

Temporal UI available at: `http://localhost:8233`

## Architecture

```
Chains API → FastAPI Gateway (8001) → Temporal Server (7233) → Worker → ComfyUI
                                              ↓
                                        SQLite/PostgreSQL
```

## Key Features

### Durable Execution
- Workflows survive gateway crashes
- State persisted to database
- Resume exactly where left off

### Automatic Retries
- Activity failures auto-retry
- Configurable retry policies
- Exponential backoff

### Real-time Monitoring
- Temporal UI: `http://localhost:8233`
- See all workflows
- Click into any workflow for full history
- Query running workflows

### AI Agent Integration
```python
from temporalio.client import Client

# AI agent debugging
client = await Client.connect("localhost:7233")
handle = client.get_workflow_handle(workflow_id)

# Get current state
state = await handle.query("get_status")
print(f"Current node: {state['current_node']}")
print(f"Progress: {state['progress']}")

# Get all events
events = await handle.query("get_events")

# Cancel if needed
await handle.signal("cancel")
```

## Files

```
temporal_gateway/
├── workflows.py     # Workflow definitions (orchestration logic)
├── activities.py    # Activities (actual work)
├── worker.py        # Worker process
├── main.py          # FastAPI gateway
└── README.md        # This file

temporal_sdk/
└── client.py        # SDK for users
```

## Comparison with Original Gateway

| Feature | Original Gateway | Temporal Gateway |
|---------|-----------------|------------------|
| State persistence | In-memory (RAM) | Database (durable) |
| Survives crashes | ❌ No | ✅ Yes |
| Automatic retries | Manual | ✅ Automatic |
| Monitoring UI | None | ✅ Temporal UI |
| Progress tracking | WebSocket | ✅ Queries + Heartbeats |
| Audit trail | Log files only | ✅ Complete event history |
| Setup complexity | Simple | Moderate |

## Production Deployment

For production, replace `temporal server start-dev` with:

```yaml
# docker-compose.yml
services:
  postgresql:
    image: postgres:13
    environment:
      POSTGRES_PASSWORD: temporal
      POSTGRES_USER: temporal

  temporal:
    image: temporalio/auto-setup:1.22.4
    depends_on:
      - postgresql
    environment:
      - DB=postgresql
      - POSTGRES_SEEDS=postgresql
    ports:
      - 7233:7233

  temporal-ui:
    image: temporalio/ui:2.21.3
    depends_on:
      - temporal
    ports:
      - 8233:8080
```

Then run:
```bash
docker-compose up -d
```

## Testing

Run comparison test:
```bash
python tests/test_temporal_comparison.py
```

This compares both gateways side by side.

## Troubleshooting

### Worker can't connect to Temporal
- Make sure `temporal server start-dev` is running
- Check `localhost:7233` is accessible

### Gateway can't start workflows
- Make sure worker is running
- Check worker is connected to same Temporal Server

### No progress updates
- Activities send heartbeats - check activity logs
- Query workflow: `http://localhost:8001/workflow/status/{workflow_id}`

## Next Steps

1. View workflow in UI: `http://localhost:8233`
2. Click on a workflow to see full execution history
3. Try canceling a workflow via SDK
4. Crash the worker mid-execution and watch it resume!
