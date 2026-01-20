"""
History-based Logger

Creates JSONL logs from ComfyUI history data after execution completes.
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime


def create_log_from_history(
    prompt_id: str,
    server_address: str,
    workflow: Dict[str, Any],
    history_data: Dict[str, Any]
) -> Path:
    """
    Create a JSONL log file from ComfyUI history data

    Args:
        prompt_id: The prompt ID
        server_address: ComfyUI server address
        workflow: The workflow definition that was executed
        history_data: History data from ComfyUI's /history/{prompt_id}

    Returns:
        Path to the created log file
    """
    # Create log directory
    log_dir = Path(__file__).parent.parent / "core" / "logs" / "prompts"
    log_dir.mkdir(parents=True, exist_ok=True)

    # Create log file
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"{timestamp}_{prompt_id}.jsonl"

    # Helper to write log entry
    def write_entry(entry: Dict[str, Any]):
        with open(log_file, 'a') as f:
            json.dump(entry, f, default=str)
            f.write('\n')

    # 1. Log workflow submission
    write_entry({
        "timestamp": datetime.utcnow().isoformat(),
        "event": "workflow.submitted",
        "prompt_id": prompt_id,
        "server": server_address,
        "workflow": workflow,
        "workflow_node_count": len(workflow),
        "workflow_nodes": list(workflow.keys())
    })

    # 2. Determine execution status
    status = history_data.get("status", {})
    outputs = history_data.get("outputs", {})

    # Check if execution completed
    completed = status.get("completed", True)  # Default to True if not specified
    status_str = status.get("status_str", "")
    messages = status.get("messages", [])

    # 3. Log execution result
    if not completed or status_str == "error":
        # Execution failed
        write_entry({
            "timestamp": datetime.utcnow().isoformat(),
            "event": "execution.error",
            "prompt_id": prompt_id,
            "server": server_address,
            "error": {
                "status": status_str,
                "messages": messages,
                "completed": completed
            }
        })

        write_entry({
            "timestamp": datetime.utcnow().isoformat(),
            "event": "workflow.failed",
            "prompt_id": prompt_id,
            "server": server_address,
            "reason": "Execution error",
            "error": {
                "status": status_str,
                "messages": messages
            }
        })

    elif outputs:
        # Execution completed successfully

        # Log outputs for each node
        for node_id, node_output in outputs.items():
            write_entry({
                "timestamp": datetime.utcnow().isoformat(),
                "event": "node.executed",
                "prompt_id": prompt_id,
                "server": server_address,
                "node_id": node_id,
                "output": node_output
            })

        # Log execution complete
        write_entry({
            "timestamp": datetime.utcnow().isoformat(),
            "event": "execution.complete",
            "prompt_id": prompt_id,
            "server": server_address,
            "nodes_executed": len(outputs)
        })

        # Log workflow success
        image_count = sum(
            len(node_output.get("images", []))
            for node_output in outputs.values()
        )

        write_entry({
            "timestamp": datetime.utcnow().isoformat(),
            "event": "workflow.success",
            "prompt_id": prompt_id,
            "server": server_address,
            "image_count": image_count
        })

    # 4. Log complete history data for reference
    write_entry({
        "timestamp": datetime.utcnow().isoformat(),
        "event": "history.complete",
        "prompt_id": prompt_id,
        "server": server_address,
        "history_data": history_data
    })

    return log_file
