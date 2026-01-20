"""
Server Registry

Singleton registry that manages all configured servers.
"""

import logging
from typing import Dict, List, Optional

from ..config import get_servers
from .models import ServerInfo
from .providers import ServerProvider, get_provider_class

logger = logging.getLogger(__name__)


class ServerRegistry:
    """
    Singleton registry for all configured servers.

    Loads servers from config.yaml and creates appropriate provider instances.
    """

    _instance: Optional["ServerRegistry"] = None

    def __init__(self):
        self._servers: Dict[str, ServerProvider] = {}
        self._load_from_config()

    @classmethod
    def get_instance(cls) -> "ServerRegistry":
        """Get singleton instance"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls):
        """Reset singleton (for testing)"""
        cls._instance = None

    def _load_from_config(self):
        """Load servers from config.yaml and create provider instances"""
        servers_config = get_servers()

        for server_config in servers_config:
            name = server_config.get("name")
            if not name:
                logger.warning("Skipping server with no name")
                continue

            # Get provider type, default to 'comfyui' for backwards compatibility
            provider_type = server_config.get("provider", "comfyui")

            try:
                provider_class = get_provider_class(provider_type)
                provider = provider_class(name=name, config=server_config)
                self._servers[name] = provider
                logger.info(f"Registered server: {name} ({provider_type})")
            except ValueError as e:
                logger.error(f"Failed to register server {name}: {e}")
            except Exception as e:
                logger.error(f"Error creating provider for {name}: {e}")

        logger.info(f"Loaded {len(self._servers)} servers from config")

    def get_all_servers(self) -> List[ServerProvider]:
        """Get all registered servers"""
        return list(self._servers.values())

    def get_server_by_name(self, name: str) -> Optional[ServerProvider]:
        """Get server by name"""
        return self._servers.get(name)

    def get_servers_by_type(self, provider_type: str) -> List[ServerProvider]:
        """Get all servers of a specific provider type"""
        return [
            server
            for server in self._servers.values()
            if server.provider_type == provider_type
        ]

    def __len__(self) -> int:
        return len(self._servers)

    def __repr__(self) -> str:
        return f"ServerRegistry({len(self._servers)} servers)"
