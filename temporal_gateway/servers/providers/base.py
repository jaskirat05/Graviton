"""
Abstract Server Provider Base Class

All provider implementations must extend this class.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any

from ..models import ServerStatus, ServerInfo


class ServerProvider(ABC):
    """Abstract base class for GPU server providers"""

    def __init__(self, name: str, config: Dict[str, Any]):
        """
        Initialize provider with name and configuration.

        Args:
            name: Unique server name
            config: Server configuration from config.yaml
        """
        self.name = name
        self.config = config

    @property
    @abstractmethod
    def provider_type(self) -> str:
        """
        Provider type identifier.

        Returns:
            Type string (e.g., 'comfyui', 'runpod', 'vastai')
        """
        pass

    @abstractmethod
    async def health_check(self) -> ServerStatus:
        """
        Check server health and get status information.

        Returns:
            ServerStatus with health info, queue depth, GPU memory, etc.
        """
        pass

    @abstractmethod
    async def get_connection_info(self) -> ServerInfo:
        """
        Get connection details for client creation.

        Returns:
            ServerInfo with HTTP and WebSocket URLs
        """
        pass

    @abstractmethod
    async def is_available(self) -> bool:
        """
        Quick availability check (lighter than full health_check).

        Returns:
            True if server is reachable and accepting requests
        """
        pass

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r})"
