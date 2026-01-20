"""
Server Providers

Pluggable provider implementations for different GPU server types.
"""

from .base import ServerProvider
from .comfyui import ComfyUIProvider

# Provider registry - maps provider type to class
PROVIDER_REGISTRY = {
    "comfyui": ComfyUIProvider,
}


def get_provider_class(provider_type: str) -> type:
    """Get provider class by type name"""
    if provider_type not in PROVIDER_REGISTRY:
        raise ValueError(f"Unknown provider type: {provider_type}")
    return PROVIDER_REGISTRY[provider_type]


__all__ = [
    "ServerProvider",
    "ComfyUIProvider",
    "PROVIDER_REGISTRY",
    "get_provider_class",
]
