"""
ComfyUI Workflow Execution Tracker

Handles tracking workflow execution through WebSocket + HTTP polling fallback.
Solves race conditions where workflows complete before WebSocket connects.
"""

import asyncio
import time
from typing import Optional, Callable, Dict, Any, TYPE_CHECKING
from dataclasses import dataclass

from core.clients.comfy.models import ExecutionStatus, WorkflowResult, ProgressUpdate

if TYPE_CHECKING:
    from core.observability.chain_logger import ChainLogger


@dataclass
class TrackingResult:
    """Result from tracking a workflow execution"""
    status: ExecutionStatus
    history_data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class ExecutionTracker:
    """
    Tracks workflow execution using hybrid WebSocket + Polling approach

    Strategy:
    1. Immediately check history (workflow might already be done)
    2. If not done, connect WebSocket for real-time updates
    3. Poll history periodically as backup (handles WS failures and race conditions)
    4. Return as soon as we have a definitive result
    """

    def __init__(
        self,
        http_client,  # HTTP client for polling
        ws_client,    # WebSocket client for real-time updates
        prompt_id: str,
        server_address: str,
        poll_interval: float = 1.0,
        timeout: float = 600.0,
        progress_callback: Optional[Callable[[ProgressUpdate], None]] = None,
        chain_logger: Optional['ChainLogger'] = None
    ):
        self.http_client = http_client
        self.ws_client = ws_client
        self.prompt_id = prompt_id
        self.server_address = server_address
        self.poll_interval = poll_interval
        self.timeout = timeout
        self.progress_callback = progress_callback
        self.chain_logger = chain_logger

        self._result: Optional[TrackingResult] = None
        self._completed = asyncio.Event()
        self._start_time = time.time()

    def _log_http(self, message: str, level: str = "info"):
        """Log HTTP-related messages to comfy_http.log"""
        if self.chain_logger:
            getattr(self.chain_logger.comfy_http, level)(message)

    def _log_ws(self, message: str, level: str = "info"):
        """Log WebSocket-related messages to comfy_ws.log"""
        if self.chain_logger:
            getattr(self.chain_logger.comfy_ws, level)(message)

    async def track(self) -> TrackingResult:
        """
        Track workflow execution until completion

        Returns:
            TrackingResult with final status and history data
        """
        self._log_ws(f"Starting execution tracking for prompt {self.prompt_id}")

        # Strategy: Run WebSocket listener and HTTP poller concurrently
        # Whichever gets the result first wins
        # Start tasks
        poll_task = asyncio.create_task(self._poll_history())
        ws_task = asyncio.create_task(self._listen_websocket())

        try:
            # Wait for completion event (set by either task when result found)
            await asyncio.wait_for(
                self._completed.wait(),
                timeout=self.timeout
            )

        except asyncio.TimeoutError:
            self._log_ws(f"Tracking timed out after {self.timeout}s", "error")
            self._result = TrackingResult(
                status=ExecutionStatus.ERROR,
                error=f"Tracking timed out after {self.timeout} seconds"
            )

        finally:
            # Cancel tasks once we have result or timeout
            poll_task.cancel()
            ws_task.cancel()
            # Don't wait for them - just let them cancel in background

        return self._result or TrackingResult(
            status=ExecutionStatus.UNKNOWN,
            error="No result received"
        )

    async def _poll_history(self):
        """Poll history API for completion"""
        self._log_http("Starting history polling")

        while not self._completed.is_set():
            try:
                # Check if workflow is in history
                history = await self.http_client.get_history(self.prompt_id)

                if self.prompt_id in history:
                    history_data = history[self.prompt_id]
                    status_str = history_data.get('status', {}).get('status_str', '')

                    self._log_http(f"[POLL] Found in history: {status_str}")

                    # Map status
                    if status_str == 'success':
                        self._set_result(TrackingResult(
                            status=ExecutionStatus.SUCCESS,
                            history_data=history_data
                        ))
                        return

                    elif status_str == 'error':
                        error_msg = history_data.get('status', {}).get('messages', [[None, 'Unknown error']])[0][1]
                        self._set_result(TrackingResult(
                            status=ExecutionStatus.ERROR,
                            history_data=history_data,
                            error=error_msg
                        ))
                        return

            except Exception as e:
                self._log_http(f"Polling error: {e}", "warning")

            # Wait before next poll
            await asyncio.sleep(self.poll_interval)

    async def _listen_websocket(self):
        """Listen to WebSocket for real-time updates"""
        self._log_ws("Starting WebSocket listener")

        try:
            async for message in self.ws_client.listen(self.prompt_id):
                msg_type = message.get('type')
                data = message.get('data', {})

                self._log_ws(f"[WS] Message: {msg_type}", "debug")

                if msg_type == 'executing':
                    node_id = data.get('node')
                    if node_id and self.progress_callback:
                        self.progress_callback(ProgressUpdate(
                            prompt_id=self.prompt_id,
                            current_node=node_id
                        ))

                elif msg_type == 'execution_success':
                    self._log_ws("[WS] Execution completed successfully")
                    # Fetch final history data
                    try:
                        history = await self.http_client.get_history(self.prompt_id)
                        if self.prompt_id in history:
                            history_data = history[self.prompt_id]
                            self._set_result(TrackingResult(
                                status=ExecutionStatus.SUCCESS,
                                history_data=history_data
                            ))
                            return
                    except Exception as e:
                        self._log_http(f"Failed to fetch history after WS success: {e}", "warning")
                        # Polling will handle it

                elif msg_type == 'execution_error':
                    error_msg = data.get('exception_message', 'Unknown error')
                    self._log_ws(f"[WS] Execution error: {error_msg}", "error")
                    self._set_result(TrackingResult(
                        status=ExecutionStatus.ERROR,
                        error=error_msg
                    ))
                    return

                elif msg_type == 'execution_interrupted':
                    self._log_ws("[WS] Execution interrupted", "warning")
                    self._set_result(TrackingResult(
                        status=ExecutionStatus.INTERRUPTED,
                        error="Execution was interrupted"
                    ))
                    return

        except Exception as e:
            self._log_ws(f"WebSocket listener error: {e}", "warning")
            # Don't fail - polling will handle it

    def _set_result(self, result: TrackingResult):
        """Set the final result and mark as completed"""
        if not self._completed.is_set():
            elapsed = time.time() - self._start_time
            self._log_ws(f"Tracking completed: {result.status} (took {elapsed:.2f}s)")
            self._result = result
            self._completed.set()
