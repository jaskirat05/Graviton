"""
Temporal Workflow Definitions for ComfyUI Execution

A Workflow orchestrates the execution flow and maintains durable state.
"""

from datetime import timedelta
from typing import Dict, Any, Optional
from dataclasses import dataclass

from temporalio import workflow
from temporalio.common import RetryPolicy

# Import activities (will be defined in activities.py)
with workflow.unsafe.imports_passed_through():
    from ..activities import (
        select_best_server,
        download_and_store_artifacts,
    )


@dataclass
class WorkflowExecutionRequest:
    """Input for workflow execution"""
    workflow_definition: Dict[str, Any]
    workflow_db_id: str  # Database workflow ID (required for artifact tracking)
    strategy: str = "least_loaded"
    workflow_name: Optional[str] = None  # For chain execution
    server_address: Optional[str] = None  # Pre-selected server (for chain steps)
    chain_id: Optional[str] = None  # Chain ID for event publishing
    step_id: Optional[str] = None  # Step ID for event publishing
    chain_name: Optional[str] = None  # Chain name for logging
    chain_version: int = 1  # Chain version for logging


@dataclass
class WorkflowExecutionResult:
    """Result of workflow execution"""
    status: str
    prompt_id: str
    server_address: str
    output: Optional[Dict[str, Any]] = None  # Standardized output: {"video": "/path/to/file.mp4", "type": "video", ...}
    local_preview: Optional[list[Dict[str, Any]]] = None  # Local downloaded files for preview/viewing
    parameters: Optional[Dict[str, Any]] = None  # Parameters used for execution
    log_file_path: Optional[str] = None
    error: Optional[str] = None


@workflow.defn
class ComfyUIWorkflow:
    """
    Durable workflow for executing ComfyUI workflows on GPU farm

    This workflow:
    1. Selects best available GPU server
    2. Queues workflow on ComfyUI
    3. Tracks execution via WebSocket
    4. Downloads generated images
    5. Creates execution log

    All state is persisted - survives crashes and restarts.
    """

    def __init__(self):
        # Workflow state - all persisted automatically by Temporal
        self._status = "initializing"
        self._server_address: Optional[str] = None
        self._prompt_id: Optional[str] = None
        self._current_node: Optional[str] = None
        self._progress = 0.0
        self._events: list[Dict] = []
        self._error: Optional[Dict] = None
        self._cancelled = False
        self._client_id: Optional[str] = None  # ComfyUI client_id for WebSocket tracking

    @workflow.run
    async def run(self, request: WorkflowExecutionRequest) -> WorkflowExecutionResult:
        """
        Main workflow execution logic

        This entire function is durable - if the worker crashes,
        Temporal will resume from the last completed step.
        """
        workflow.logger.info(f"Starting ComfyUI workflow execution")

        try:
            # Generate unique client_id for this workflow execution
            # Use Temporal's deterministic UUID generator
            self._client_id = str(workflow.uuid4())
            workflow.logger.info(f"Generated client_id: {self._client_id}")

            # Step 1: Select best GPU server (or use pre-selected)
            self._status = "selecting_server"
            if request.server_address:
                # Use pre-selected server (from chain orchestration)
                self._server_address = request.server_address
                workflow.logger.info(f"Using pre-selected server: {self._server_address}")
            else:
                # Dynamically select server
                self._server_address = await workflow.execute_activity(
                    select_best_server,
                    args=[
                        request.strategy,
                        request.chain_name,
                        request.chain_version,
                        request.chain_id,
                    ],
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(
                        maximum_attempts=3,
                        initial_interval=timedelta(seconds=1),
                        maximum_interval=timedelta(seconds=10),
                        backoff_coefficient=2.0
                    )
                )
                workflow.logger.info(f"Selected server: {self._server_address}")

            # Step 2: Execute workflow with new V3 client (handles queue + tracking)
            self._status = "executing"
            from ..activities import execute_and_track_workflow

            execution_result = await workflow.execute_activity(
                execute_and_track_workflow,
                args=[
                    self._server_address,
                    request.workflow_definition,
                    request.workflow_name,
                    1800.0,  # timeout
                    request.chain_id,
                    request.step_id,
                    request.chain_name,
                    request.chain_version,
                ],
                start_to_close_timeout=timedelta(minutes=30),
                heartbeat_timeout=timedelta(minutes=10),
                retry_policy=RetryPolicy(
                    maximum_attempts=2,
                    initial_interval=timedelta(seconds=5),
                    maximum_interval=timedelta(seconds=30),
                    backoff_coefficient=2.0
                )
            )

            self._prompt_id = execution_result.get("prompt_id")

            # Check if execution failed
            if execution_result.get("status") == "failed":
                self._status = "failed"
                self._error = execution_result.get("error")
                workflow.logger.error(f"Execution failed: {self._error}")

                return WorkflowExecutionResult(
                    status="failed",
                    prompt_id=self._prompt_id,
                    server_address=self._server_address,
                    local_preview=[],
                    error=str(self._error)
                )

            workflow.logger.info(f"Execution completed successfully")

            # Step 3: Download files and persist to database
            self._status = "downloading_files"
            downloaded_files = await workflow.execute_activity(
                download_and_store_artifacts,
                args=[
                    request.workflow_db_id,
                    self._server_address,
                    {"outputs": execution_result["outputs"]},
                    request.chain_name,
                    request.chain_version,
                    request.chain_id,
                ],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    maximum_attempts=3,
                    initial_interval=timedelta(seconds=2),
                    maximum_interval=timedelta(seconds=10),
                    backoff_coefficient=2.0
                )
            )

            workflow.logger.info(f"Downloaded {len(downloaded_files)} file(s) locally")

            # Step 4: Build standardized output for chains
            output_data = None
            if downloaded_files:
                primary_file = downloaded_files[0]["original_filename"]

                # Detect type from file extension
                ext = primary_file.rsplit(".", 1)[-1].lower() if "." in primary_file else ""

                # Determine output type based on extension
                if ext in ("mp4", "webm", "mov", "avi", "mkv"):
                    output_type = "video"
                elif ext in ("mp3", "wav", "flac", "ogg", "aac", "m4a"):
                    output_type = "audio"
                elif ext in ("obj", "fbx", "gltf", "glb", "stl", "ply", "usdz"):
                    output_type = "3d"
                else:
                    output_type = "image"

                output_data = {
                    "output": primary_file,  # Generic key for chain templates: {{ step.output.output }}
                    output_type: primary_file,  # Type-specific key: "video", "audio", "3d", or "image"
                    "type": output_type,
                    "files": [f["original_filename"] for f in downloaded_files],
                    "count": len(downloaded_files)
                }

            # Step 5: Complete
            self._status = "completed"

            return WorkflowExecutionResult(
                status="completed",
                prompt_id=self._prompt_id,
                server_address=self._server_address,
                output=output_data,
                local_preview=downloaded_files
            )

        except Exception as e:
            self._status = "failed"

            # Extract the original error message from Temporal's wrapped exceptions
            # Chain: ActivityError -> ApplicationError (contains original message)
            # We need to traverse to the innermost cause to get the real error
            error_message = str(e)

            # First, traverse to the innermost exception in the cause chain
            innermost = e
            while True:
                next_cause = getattr(innermost, 'cause', None) or getattr(innermost, '__cause__', None)
                if next_cause is None:
                    break
                innermost = next_cause

            # Get message from the innermost exception (ApplicationError.message)
            if hasattr(innermost, 'message') and innermost.message:
                error_message = innermost.message
            elif hasattr(innermost, 'args') and innermost.args:
                error_message = str(innermost.args[0])

            self._error = {"message": error_message, "type": type(e).__name__}
            workflow.logger.error(f"Workflow failed with error: {error_message}")

            return WorkflowExecutionResult(
                status="failed",
                prompt_id=self._prompt_id or "",
                server_address=self._server_address or "",
                local_preview=[],
                error=error_message
            )

    @workflow.query
    def get_status(self) -> Dict[str, Any]:
        """
        Query to get current workflow status

        AI agents or SDK can call this anytime to get real-time state
        """
        return {
            "status": self._status,
            "server_address": self._server_address,
            "prompt_id": self._prompt_id,
            "current_node": self._current_node,
            "progress": self._progress,
            "error": self._error
        }

    @workflow.query
    def get_events(self) -> list[Dict]:
        """Get all ComfyUI WebSocket events collected so far"""
        return self._events

    @workflow.signal
    async def cancel(self):
        """
        Signal to cancel the workflow

        User or AI agent can send this to cancel execution
        """
        workflow.logger.info("Cancel signal received")
        self._cancelled = True
        self._status = "cancelled"
