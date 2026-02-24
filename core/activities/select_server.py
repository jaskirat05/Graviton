"""Activity: Select best available server from registry-service projection."""

from typing import Optional
from temporalio import activity

from core.registry_service.projection import ProjectionStore
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

    store = ProjectionStore()
    await store.connect()
    try:
        def _to_url(address: str, port: Optional[int], ssl: bool) -> str:
            if address.startswith(("http://", "https://")):
                base = address.rstrip("/")
            else:
                scheme = "https" if ssl else "http"
                base = f"{scheme}://{address}"
            host_part = base.split("//", 1)[1]
            if port and ":" not in host_part:
                base = f"{base}:{port}"
            return base

        if strategy == "specific" and server_name:
            server = await store.get_server_by_name(server_name)
            if not server:
                log(f"Server '{server_name}' not found", "error")
                raise Exception(f"Server '{server_name}' not found in registry")
            url = _to_url(server.address, server.port, server.ssl)
            log(f"Selected specific server: {server.name} ({url})")
            return url

        candidates = []
        for server in await store.list_servers():
            if server.status != "registered":
                continue
            health = await store.get_health(server.id)
            if not health or health.health_state not in {"healthy", "degraded"}:
                continue
            queue_depth = health.queue_depth if health.queue_depth is not None else 10**9
            candidates.append((queue_depth, server))

        if not candidates:
            raise Exception("No healthy/degraded registered servers available")

        candidates.sort(key=lambda item: item[0])
        selected = candidates[0][1]
        url = _to_url(selected.address, selected.port, selected.ssl)
        log(f"Selected server: {selected.name} ({url})")
        return url
    finally:
        await store.close()
