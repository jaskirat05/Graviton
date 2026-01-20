"""
Activity: Select best available server

Uses the server registry and load balancer to select
the best available ComfyUI server based on queue depth.
"""

from temporalio import activity

from ..servers import ServerRegistry, LoadBalancer
from ..servers.load_balancer import NoServersAvailableError


@activity.defn
async def select_best_server(strategy: str = "least_queue") -> str:
    """
    Activity: Select the best available server.

    Uses real-time queue depth from servers to select the one
    with the shortest queue.

    Args:
        strategy: Selection strategy (currently only 'least_queue' supported)

    Returns:
        Server HTTP URL (e.g., "http://localhost:8188")

    Raises:
        Exception: If no servers are available
    """
    activity.logger.info(f"Selecting server with strategy: {strategy}")

    registry = ServerRegistry.get_instance()
    load_balancer = LoadBalancer(registry)

    try:
        server_info = await load_balancer.select_server()

        activity.logger.info(
            f"Selected server: {server_info.name} ({server_info.http_url})"
        )

        return server_info.http_url

    except NoServersAvailableError as e:
        activity.logger.error(f"No servers available: {e}")
        raise Exception(f"No servers available: {e}")
