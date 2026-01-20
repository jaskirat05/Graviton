"""
ComfyUI Server Provider

Direct connection to ComfyUI servers via HTTP/WebSocket.
"""

import httpx
import logging
from datetime import datetime
from typing import Dict, Any

from .base import ServerProvider
from ..models import ServerStatus, ServerInfo

logger = logging.getLogger(__name__)


class ComfyUIProvider(ServerProvider):
    """Direct ComfyUI server provider"""

    DEFAULT_PORT = 8188

    @property
    def provider_type(self) -> str:
        return "comfyui"

    @property
    def http_url(self) -> str:
        """Build HTTP URL from config"""
        address = self.config.get("address", "localhost")
        port = self.config.get("port")  # None if not specified

        # Add http:// prefix if not present
        if not address.startswith(("http://", "https://")):
            address = f"http://{address}"

        # Only add port if explicitly provided and not already in address
        if port and ":" not in address.split("//")[1]:
            address = f"{address}:{port}"

        return address

    @property
    def ws_url(self) -> str:
        """Build WebSocket URL from HTTP URL"""
        url = self.http_url
        if url.startswith("https://"):
            return url.replace("https://", "wss://") + "/ws"
        return url.replace("http://", "ws://") + "/ws"

    async def health_check(self) -> ServerStatus:
        """
        Check server health via /system_stats and /queue endpoints.

        Returns:
            ServerStatus with health info, queue depth, GPU memory
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Get system stats for GPU info
                stats_response = await client.get(f"{self.http_url}/system_stats")
                stats_response.raise_for_status()
                stats = stats_response.json()

                # Get queue for queue depth
                queue_response = await client.get(f"{self.http_url}/queue")
                queue_response.raise_for_status()
                queue = queue_response.json()

            # Parse GPU memory from system stats
            gpu_memory_used = 0.0
            gpu_memory_total = 0.0

            devices = stats.get("devices", [])
            if devices:
                # Sum up all GPU memory (in case of multi-GPU)
                for device in devices:
                    gpu_memory_used += device.get("vram_used", 0) or 0
                    gpu_memory_total += device.get("vram_total", 0) or 0

            # Calculate queue depth (running + pending)
            queue_running = queue.get("queue_running", [])
            queue_pending = queue.get("queue_pending", [])
            queue_depth = len(queue_running) + len(queue_pending)

            return ServerStatus(
                healthy=True,
                queue_depth=queue_depth,
                gpu_memory_used=gpu_memory_used,
                gpu_memory_total=gpu_memory_total,
                last_check=datetime.now(),
            )

        except httpx.TimeoutException:
            logger.warning(f"Health check timeout for {self.name} at {self.http_url}")
            return ServerStatus(
                healthy=False,
                last_check=datetime.now(),
                error="Connection timeout",
            )
        except httpx.HTTPStatusError as e:
            logger.warning(f"Health check HTTP error for {self.name}: {e}")
            return ServerStatus(
                healthy=False,
                last_check=datetime.now(),
                error=f"HTTP {e.response.status_code}",
            )
        except Exception as e:
            logger.warning(f"Health check failed for {self.name}: {e}")
            return ServerStatus(
                healthy=False,
                last_check=datetime.now(),
                error=str(e),
            )

    async def get_connection_info(self) -> ServerInfo:
        """Get connection details for client creation"""
        return ServerInfo(
            name=self.name,
            provider_type=self.provider_type,
            http_url=self.http_url,
            ws_url=self.ws_url,
        )

    async def is_available(self) -> bool:
        """Quick availability check - just ping the server"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.http_url}/system_stats")
                return response.status_code == 200
        except Exception:
            return False
