"""
Activity: Execute workflow with hybrid tracking
"""

import asyncio
from typing import Dict, Any, Optional

import httpx
from temporalio import activity

from core.clients.comfy import ComfyUIClient
from core.clients.comfy.http import ComfyHTTPClient
from core.services.broadcast import publish_chain_event
from core.observability.chain_logger import ChainLogger


@activity.defn
async def interrupt_comfy_prompt(server_address: str) -> bool:
    """
    Activity: Interrupt the currently running prompt on a ComfyUI server.

    Args:
        server_address: ComfyUI server address

    Returns:
        True if interrupt was successful
    """
    client = ComfyHTTPClient(server_address)
    try:
        return await client.interrupt()
    finally:
        await client.close()


@activity.defn
async def execute_and_track_workflow(
    server_address: str,
    workflow_json: Dict[str, Any],
    workflow_name: Optional[str] = None,
    timeout: float = 1800.0,
    chain_id: Optional[str] = None,
    step_id: Optional[str] = None,
    chain_name: Optional[str] = None,
    chain_version: int = 1,
) -> Dict[str, Any]:
    """
    Activity: Execute workflow using new ComfyUI client with hybrid tracking

    Args:
        server_address: ComfyUI server address
        workflow_json: Workflow definition JSON
        workflow_name: Optional workflow name for logging
        timeout: Execution timeout in seconds
        chain_id: Chain ID for event publishing and logging
        step_id: Step ID for event publishing
        chain_name: Chain name for logging folder
        chain_version: Chain version for logging folder

    Returns:
        Dict with execution result
    """
    # Create chain logger if we have chain info
    chain_logger = None
    if chain_id and chain_name:
        chain_logger = ChainLogger.create(chain_name, chain_version, chain_id)

    def log(msg: str, level: str = "info"):
        """Log to chain logger's worker.log"""
        if chain_logger:
            getattr(chain_logger.worker, level)(msg)

    log(f"Step {step_id}: Executing {workflow_name} on {server_address}")

    # Publish step started event
    if chain_id and step_id:
        await publish_chain_event(chain_id, {
            "type": "step_executing",
            "step_id": step_id,
            "workflow": workflow_name,
            "server": server_address,
        })

    # Create client with chain logger for HTTP/WS logging
    client = ComfyUIClient(server_address, chain_logger=chain_logger)

    try:
        # Track last known node for progress-only updates
        last_node_id = [None]  # Use list to allow mutation in closure

        # Progress callback to send heartbeats and publish events
        async def on_progress_async(update):
            try:
                activity.heartbeat({
                    "current_node": update.current_node,
                    "progress": update.progress
                })
            except Exception:
                pass

            # Track current node for progress-only updates
            if update.current_node:
                last_node_id[0] = update.current_node

            # Publish node execution event (for new node or progress update)
            if chain_id and step_id:
                node_id = update.current_node or last_node_id[0]
                if node_id or update.progress > 0:
                    # Look up node name from workflow JSON
                    node_name = None
                    if node_id and node_id in workflow_json:
                        node_meta = workflow_json[node_id].get("_meta", {})
                        node_name = node_meta.get("title")

                    await publish_chain_event(chain_id, {
                        "type": "step_node",
                        "step_id": step_id,
                        "node_id": node_id,
                        "node_name": node_name,
                        "progress": update.progress,
                    })

        # Sync wrapper for callback
        import asyncio
        def on_progress(update):
            try:
                asyncio.get_event_loop().create_task(on_progress_async(update))
            except Exception:
                pass

        # Execute workflow with tracking
        result = await client.execute_workflow(
            workflow=workflow_json,
            progress_callback=on_progress,
            timeout=timeout
        )

        log(f"Step {step_id}: Result status={result.status}, is_success={result.is_success}")

        if result.is_success:
            log(f"Step {step_id}: Workflow completed successfully")

            # Publish completion event
            if chain_id and step_id:
                try:
                    await publish_chain_event(chain_id, {
                        "type": "step_workflow_complete",
                        "step_id": step_id,
                        "workflow": workflow_name,
                        "output_count": len(result.outputs) if result.outputs else 0,
                    })
                except Exception as e:
                    log(f"Step {step_id}: Failed to publish completion event: {e}", "warning")

            return {
                "status": "completed",
                "prompt_id": result.prompt_id,
                "server_address": server_address,
                "outputs": result.outputs
            }
        else:
            error_msg = result.error or "Unknown error"
            log(f"Step {step_id}: Workflow failed: {error_msg}", "error")

            # Publish failure event
            if chain_id and step_id:
                try:
                    await publish_chain_event(chain_id, {
                        "type": "step_workflow_failed",
                        "step_id": step_id,
                        "workflow": workflow_name,
                        "error": error_msg,
                    })
                except Exception as e:
                    log(f"Step {step_id}: Failed to publish failure event: {e}", "warning")

            return {
                "status": "failed",
                "prompt_id": result.prompt_id,
                "server_address": server_address,
                "error": error_msg
            }

    except httpx.HTTPStatusError as e:
        # ComfyUI rejected the request (400, 500, etc.) - prompt validation failed
        import json

        # Parse ComfyUI error response
        error_data = {}
        try:
            error_data = e.response.json()
        except Exception:
            error_data = {"error": {"message": e.response.text[:500]}}

        # Extract structured error info
        error_info = error_data.get("error", {})
        error_type = error_info.get("type", "unknown_error") if isinstance(error_info, dict) else "unknown_error"
        error_message = error_info.get("message", str(error_info)) if isinstance(error_info, dict) else str(error_info)
        node_errors = error_data.get("node_errors", {})

        log(f"Step {step_id}: ComfyUI validation failed: {error_type} - {error_message}", "error")
        if node_errors:
            log(f"Step {step_id}: Node errors: {json.dumps(node_errors, indent=2)}", "error")

        # Publish structured validation failure event
        if chain_id and step_id:
            try:
                await publish_chain_event(chain_id, {
                    "type": "step_validation_failed",
                    "step_id": step_id,
                    "workflow": workflow_name,
                    "error_type": error_type,
                    "error_message": error_message,
                    "node_errors": node_errors,
                })
            except Exception as pub_err:
                log(f"Step {step_id}: Failed to publish failure event: {pub_err}", "warning")

        # Build structured error message for database storage
        # Format: JSON with error_type, message, and node_errors for frontend parsing
        structured_error = {
            "type": "validation_error",
            "error_type": error_type,
            "message": error_message,
            "node_errors": node_errors,
        }
        raise Exception(json.dumps(structured_error))

    except asyncio.CancelledError:
        # Activity was cancelled - interrupt the ComfyUI prompt
        log(f"Step {step_id}: Activity cancelled, interrupting ComfyUI prompt", "warning")
        try:
            interrupt_client = ComfyHTTPClient(server_address, chain_logger=chain_logger)
            await interrupt_client.interrupt()
            await interrupt_client.close()
        except Exception as interrupt_err:
            log(f"Step {step_id}: Failed to interrupt ComfyUI: {interrupt_err}", "warning")
        raise  # Re-raise to properly cancel

    except Exception as e:
        # Any other unexpected error
        error_msg = f"{type(e).__name__}: {str(e)}"
        log(f"Step {step_id}: Unexpected error: {error_msg}", "error")

        # Publish failure event before re-raising
        if chain_id and step_id:
            try:
                await publish_chain_event(chain_id, {
                    "type": "step_workflow_failed",
                    "step_id": step_id,
                    "workflow": workflow_name,
                    "error": error_msg,
                })
            except Exception as pub_err:
                log(f"Step {step_id}: Failed to publish failure event: {pub_err}", "warning")

        raise  # Re-raise to fail the activity

    finally:
        await client.close()
