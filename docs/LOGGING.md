# Logging Guide

ComfyAutomate automatically logs every workflow execution without any manual setup. This guide explains how the logging system works and how to use it.

## Overview

**Automatic Logging** - No configuration required. Every call to `sdk.execute_workflow()` creates a detailed log file automatically.

**JSONL Format** - Logs are stored as JSON Lines (one JSON object per line) for easy parsing and analysis.

**History-Based** - Logs are created from ComfyUI's execution history after completion, ensuring complete and accurate data.

## How It Works

### Execution Flow

```
1. User calls sdk.execute_workflow(workflow)
   ↓
2. Gateway queues workflow on ComfyUI server
   ↓
3. Execution completes (or fails)
   ↓
4. Gateway fetches history from ComfyUI /history/{prompt_id}
   ↓
5. Gateway creates log file from history data
   ↓
6. Response includes log_file_path
```

### For Both Sync and Async Modes

**Sync Mode (wait=True):**
- Blocks until execution completes
- Log created before response returned
- Response includes `log_file_path`

**Async Mode (wait=False):**
- Returns immediately with job_id
- When you poll `/workflow/status/{job_id}` and execution is complete
- Log is created automatically
- Status response includes `log_file_path`

## Log File Format

### File Location

```
gateway/core/logs/prompts/{timestamp}_{prompt_id}.jsonl
```

Example: `20250124_143022_abc123def456.jsonl`

### Log Entries

Each line in the log file is a JSON object with these fields:

```json
{
  "timestamp": "2025-01-24T14:30:22.123456",
  "event": "workflow.submitted",
  "prompt_id": "abc123def456",
  "server": "127.0.0.1:8188",
  ...additional fields based on event type...
}
```

### Event Types

| Event | Description | Contains |
|-------|-------------|----------|
| `workflow.submitted` | Workflow queued | `workflow`, `workflow_node_count`, `workflow_nodes` |
| `node.executed` | Node completed | `node_id`, `output` |
| `execution.complete` | All nodes finished | `nodes_executed` |
| `execution.error` | Execution failed | `error` details |
| `workflow.success` | Successful completion | `image_count` |
| `workflow.failed` | Failed execution | `reason`, `error` |
| `history.complete` | Full history data | `history_data` |

## Usage Examples

### Basic Usage

```bash
# Execute a chain - logging happens automatically
curl -X POST http://localhost:8001/chains/my_chain/execute \
  -H "Content-Type: application/json" \
  -d '{"initial_parameters": {}}'

# Get result with log path
curl http://localhost:8001/chains/result/{workflow_id}
```

### Retrieve Logs via API

```python
import requests

# Get log contents
response = requests.get(f"http://localhost:8000/workflow/logs/{job_id}")
log_data = response.json()

print(f"Total events: {log_data['entry_count']}")
print(f"Log file: {log_data['log_file_path']}")

# Iterate through log entries
for entry in log_data['log_entries']:
    print(f"{entry['timestamp']} - {entry['event']}")
```

### Analyze Logs with PromptLogReader

```python
from temporal_gateway.observability import PromptLogReader
from pathlib import Path

# Read log file
log_file = Path(result['log_file_path'])
reader = PromptLogReader(log_file)

# Get summary
summary = reader.get_summary()
print(f"Status: {summary['status']}")
print(f"Nodes executed: {summary['nodes_executed']}")

# Check for errors
if summary['error']:
    print(f"Failed node: {summary['error']['node_id']}")
    print(f"Error: {summary['error']['error_message']}")

# Get execution timeline
for event in reader.get_execution_timeline():
    print(f"{event['timestamp']} - {event['event']}")
```

### Find Failed Workflows

```python
from temporal_gateway.observability import find_failed_prompts

# Find all failed executions
failed = find_failed_prompts()

for failure in failed:
    summary = failure['summary']
    print(f"Prompt: {summary['prompt_id']}")
    print(f"Error: {summary['error']['error_message']}")
    print(f"Log: {failure['log_file']}")
```

## Log Contents Detail

### Workflow Submission

```json
{
  "timestamp": "2025-01-24T14:30:22.123456",
  "event": "workflow.submitted",
  "prompt_id": "abc123",
  "server": "127.0.0.1:8188",
  "workflow": {
    "1": {"class_type": "LoadImage", "inputs": {...}},
    "2": {"class_type": "KSampler", "inputs": {...}}
  },
  "workflow_node_count": 5,
  "workflow_nodes": ["1", "2", "3", "4", "5"]
}
```

### Node Execution

```json
{
  "timestamp": "2025-01-24T14:30:25.789012",
  "event": "node.executed",
  "prompt_id": "abc123",
  "server": "127.0.0.1:8188",
  "node_id": "3",
  "output": {
    "images": [
      {"filename": "output_00001.png", "subfolder": "", "type": "output"}
    ]
  }
}
```

### Execution Error

```json
{
  "timestamp": "2025-01-24T14:30:30.456789",
  "event": "execution.error",
  "prompt_id": "abc123",
  "server": "127.0.0.1:8188",
  "error": {
    "status": "error",
    "messages": [
      ["Error executing node 3", {"exception_message": "...", "traceback": [...]}]
    ],
    "completed": false
  }
}
```

### Complete History Data

```json
{
  "timestamp": "2025-01-24T14:30:31.123456",
  "event": "history.complete",
  "prompt_id": "abc123",
  "server": "127.0.0.1:8188",
  "history_data": {
    "prompt": {...},
    "outputs": {...},
    "status": {...}
  }
}
```

## Integration with Debug Agent

The logging system is designed for automated debugging:

1. **Workflow fails** → Log automatically created
2. **Debug agent reads log** using `PromptLogReader`
3. **Agent analyzes**:
   - Which node failed
   - Error type and message
   - Node inputs that caused the failure
   - Full workflow context
4. **Agent fixes workflow** and retries

Example debug agent workflow:

```python
from temporal_gateway.observability import PromptLogReader, find_failed_prompts

# Find recent failures
failed = find_failed_prompts()

for failure in failed[:5]:  # Last 5 failures
    reader = failure['reader']

    # Get error details
    failed_node = reader.get_failed_node()

    print(f"Failed Node: {failed_node['node_id']}")
    print(f"Node Type: {failed_node['node_type']}")
    print(f"Error: {failed_node['error']}")
    print(f"Inputs: {failed_node['node_context']['inputs']}")

    # Agent can now:
    # 1. Analyze why this node failed
    # 2. Fix the workflow
    # 3. Retry execution
```

## API Endpoints

### Get Log Contents

```http
GET /workflow/logs/{job_id}
```

Response:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "log_file_path": "/path/to/20250124_143022_abc123.jsonl",
  "log_entries": [...],
  "entry_count": 12
}
```

### Get Job Status (includes log path when complete)

```http
GET /workflow/status/{job_id}
```

Response:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "log_file_path": "/path/to/20250124_143022_abc123.jsonl",
  "images": [...],
  ...
}
```

## Benefits

✅ **Zero Configuration** - Works automatically, no setup needed
✅ **Complete Data** - All execution details captured
✅ **Structured Format** - JSONL for easy parsing
✅ **Debug-Friendly** - Designed for automated analysis
✅ **Persistent** - Logs stored on disk for later analysis
✅ **Works Both Modes** - Sync and async both get full logging

## Technical Details

### Implementation

Logs are created by `create_log_from_history()` in `gateway/observability/history_logger.py`:

1. Fetches execution history from ComfyUI
2. Parses outputs, errors, and status
3. Creates structured JSONL entries
4. Writes to timestamped file

### Why History-Based?

ComfyUI maintains complete execution state in `/history/{prompt_id}`. By using this:
- ✅ No need for real-time WebSocket tracking
- ✅ Guaranteed complete and accurate data
- ✅ Simpler implementation
- ✅ Works reliably for both sync/async

### What's Not Logged

Since logs are created from history (not real-time WebSocket):
- ❌ Real-time progress percentages
- ❌ Intermediate node states during execution
- ❌ Raw WebSocket event stream

But you **do** get:
- ✅ Final node outputs
- ✅ Complete error information
- ✅ Execution success/failure status
- ✅ Full workflow definition
- ✅ Complete ComfyUI history data

This is sufficient for debugging and automated analysis.
