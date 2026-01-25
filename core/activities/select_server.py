"""
Activity: Select best available server

Uses the server registry and load balancer to select
the best available ComfyUI server based on queue depth.
"""

from typing import Optional
from temporalio import activity

from ..servers import ServerRegistry, LoadBalancer
from ..servers.load_balancer import NoServersAvailableError
from ..observability.chain_logger import ChainLogger


@activity.defn
async def select_best_server(
    strategy: str = "least_queue",
    chain_name: Optional[str] = None,
    chain_version: int = 1,
    chain_id: Optional[str] = None,
    server_name: Optional[str] = None,
) -> str:
    """
    Activity: Select the best available server.

    Uses real-time queue depth from servers to select the one
    with the shortest queue, or selects a specific server by name.

    Args:
        strategy: Selection strategy ('least_queue', 'least_loaded', or 'specific')
        chain_name: Chain name for logging
        chain_version: Chain version for logging
        chain_id: Chain ID for logging
        server_name: Server name (required when strategy is 'specific')

    Returns:
        Server HTTP URL (e.g., "http://localhost:8188")

    Raises:
        Exception: If no servers are available or specified server not found
    """
    chain_logger = None
    if chain_id and chain_name:
        chain_logger = ChainLogger.create(chain_name, chain_version, chain_id)

    def log(msg: str, level: str = "info"):
        if chain_logger:
            getattr(chain_logger.worker, level)(msg)

    log(f"Selecting server with strategy: {strategy}")

    registry = ServerRegistry.get_instance()

    # Handle specific server selection
    if strategy == "specific" and server_name:
        server_info = registry.get_server_by_name(server_name)
        if not server_info:
            log(f"Server '{server_name}' not found", "error")
            raise Exception(f"Server '{server_name}' not found in registry")

        log(f"Selected specific server: {server_info.name} ({server_info.http_url})")
        return server_info.http_url

    # Fall back to load balancing
    load_balancer = LoadBalancer(registry)

    try:
        server_info = await load_balancer.select_server()

        log(f"Selected server: {server_info.name} ({server_info.http_url})")

        return server_info.http_url

    except NoServersAvailableError as e:
        log(f"No servers available: {e}", "error")
        raise Exception(f"No servers available: {e}")
