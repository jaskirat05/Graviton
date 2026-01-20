"""
Load Balancer

Selects best server based on real-time queue depth from servers.
"""

import asyncio
import logging
from typing import List, Tuple

from .models import ServerStatus, ServerInfo
from .registry import ServerRegistry
from .providers import ServerProvider

logger = logging.getLogger(__name__)


class NoServersAvailableError(Exception):
    """Raised when no healthy servers are available"""

    pass


class LoadBalancer:
    """
    Load balancer using server's real queue depth.

    Queries each server's /system_stats to get actual load,
    then selects the server with shortest queue.
    """

    def __init__(self, registry: ServerRegistry):
        self.registry = registry

    async def select_server(self) -> ServerInfo:
        """
        Select server with shortest queue.

        Returns:
            ServerInfo for the best available server

        Raises:
            NoServersAvailableError: If no healthy servers are available
        """
        servers = self.registry.get_all_servers()

        if not servers:
            raise NoServersAvailableError("No servers configured")

        # Get actual status from each server (includes queue_depth)
        statuses = await asyncio.gather(
            *[server.health_check() for server in servers],
            return_exceptions=True,
        )

        # Filter to healthy servers
        healthy: List[Tuple[ServerProvider, ServerStatus]] = []
        for server, status in zip(servers, statuses):
            if isinstance(status, Exception):
                logger.warning(f"Health check failed for {server.name}: {status}")
                continue
            if status.healthy:
                healthy.append((server, status))
            else:
                logger.debug(
                    f"Server {server.name} unhealthy: {status.error}"
                )

        if not healthy:
            raise NoServersAvailableError("No healthy servers available")

        # Select by lowest queue_depth (real server load)
        best_server, best_status = min(healthy, key=lambda x: x[1].queue_depth)

        logger.info(
            f"Selected server {best_server.name} "
            f"(queue_depth={best_status.queue_depth}, "
            f"gpu_mem={best_status.gpu_memory_percent:.1f}%)"
        )

        return await best_server.get_connection_info()

    async def get_all_statuses(self) -> List[Tuple[ServerProvider, ServerStatus]]:
        """
        Get status of all servers (for monitoring/debugging).

        Returns:
            List of (server, status) tuples
        """
        servers = self.registry.get_all_servers()
        statuses = await asyncio.gather(
            *[server.health_check() for server in servers],
            return_exceptions=True,
        )

        result = []
        for server, status in zip(servers, statuses):
            if isinstance(status, Exception):
                result.append(
                    (
                        server,
                        ServerStatus(healthy=False, error=str(status)),
                    )
                )
            else:
                result.append((server, status))

        return result
