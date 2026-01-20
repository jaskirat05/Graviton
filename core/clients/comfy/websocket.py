"""
ComfyUI WebSocket Client

Handles real-time updates from ComfyUI server via WebSocket.
"""

import json
import asyncio
from typing import Dict, Any, AsyncIterator, Optional, TYPE_CHECKING
import websockets

if TYPE_CHECKING:
    from core.observability.chain_logger import ChainLogger


class ComfyWebSocketClient:
    """WebSocket client for ComfyUI real-time updates"""

    def __init__(self, server_address: str, client_id: str, chain_logger: Optional['ChainLogger'] = None):
        # Convert HTTP URL to WebSocket URL
        self.ws_url = server_address.replace('http://', 'ws://').replace('https://', 'wss://')
        self.ws_url = f"{self.ws_url.rstrip('/')}/ws?clientId={client_id}"
        self.client_id = client_id
        self.chain_logger = chain_logger

    def _log(self, message: str):
        """Log to chain logger if available."""
        if self.chain_logger:
            self.chain_logger.comfy_ws.info(message)

    async def listen(self, prompt_id: Optional[str] = None) -> AsyncIterator[Dict[str, Any]]:
        """
        Listen to WebSocket messages

        Args:
            prompt_id: Optional prompt ID to filter messages

        Yields:
            Message dictionaries from WebSocket
        """
        self._log(f"Connecting to WebSocket: {self.ws_url}")

        try:
            async with websockets.connect(self.ws_url) as websocket:
                self._log("WebSocket connected")

                while True:
                    try:
                        message = await asyncio.wait_for(
                            websocket.recv(),
                            timeout=1.0  # 1 second timeout to allow cancellation
                        )

                        data = json.loads(message)
                        msg_type = data.get('type', 'unknown')

                        # If filtering by prompt_id, only yield relevant messages
                        if prompt_id:
                            msg_prompt_id = data.get('data', {}).get('prompt_id')
                            if msg_prompt_id and msg_prompt_id != prompt_id:
                                continue

                        # Log the message
                        if msg_type == 'executing':
                            node_id = data.get('data', {}).get('node')
                            self._log(f"executing node={node_id}")
                        elif msg_type == 'execution_success':
                            self._log(f"execution_success prompt_id={prompt_id}")
                        elif msg_type == 'execution_error':
                            error = data.get('data', {}).get('exception_message', 'unknown')
                            self._log(f"execution_error: {error}")
                        elif msg_type == 'progress':
                            value = data.get('data', {}).get('value', 0)
                            max_val = data.get('data', {}).get('max', 1)
                            self._log(f"progress {value}/{max_val}")
                        elif msg_type == 'status':
                            queue_remaining = data.get('data', {}).get('status', {}).get('exec_info', {}).get('queue_remaining', 0)
                            self._log(f"status queue_remaining={queue_remaining}")
                        elif msg_type == 'execution_start':
                            self._log(f"execution_start prompt_id={data.get('data', {}).get('prompt_id')}")
                        elif msg_type == 'execution_cached':
                            cached_nodes = data.get('data', {}).get('nodes', [])
                            self._log(f"execution_cached nodes={cached_nodes}")
                        elif msg_type == 'execution_interrupted':
                            self._log(f"execution_interrupted")
                        elif msg_type == 'crystools.monitor':
                            pass  # Skip verbose system monitor events
                        else:
                            # Log any unrecognized events
                            self._log(f"[other] {msg_type}: {data.get('data', {})}")

                        yield data

                    except asyncio.TimeoutError:
                        # Timeout allows cancellation, continue listening
                        continue

                    except websockets.exceptions.ConnectionClosed:
                        self._log("WebSocket connection closed")
                        break

        except Exception as e:
            self._log(f"WebSocket error: {e}")
            # Don't raise - let the tracker handle fallback to polling
