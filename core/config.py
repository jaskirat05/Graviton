"""Configuration helpers (env-only)."""

import os
from pathlib import Path
from typing import List, Dict, Any


def load_config() -> Dict[str, Any]:
    """Legacy shim retained for compatibility; env-only config returns empty dict."""
    return {}


def get_storage_dir() -> Path:
    """Get artifacts storage directory from env."""
    storage_path = os.environ.get("ARTIFACTS_DIR", "artifacts")
    path = Path(storage_path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_servers() -> List[Dict[str, Any]]:
    """Legacy shim; server registration now goes through registry service APIs."""
    return []


def get_server(name: str) -> Dict[str, Any]:
    """Get server config by name"""
    for server in get_servers():
        if server.get("name") == name:
            return server
    return {}


def get_default_server() -> Dict[str, Any]:
    """Legacy shim for backward compatibility."""
    servers = get_servers()
    if not servers:
        raise ValueError("No servers configured. Use registry service APIs.")
    return servers[0]


def get_redis_url() -> str:
    """Get Redis URL for pub/sub from env."""
    return os.environ.get("REDIS_URL", "redis://localhost:6379")


def get_gateway_url() -> str:
    """Get gateway URL for notifications from env."""
    return os.environ.get("GATEWAY_URL", "http://localhost:8001")


def get_temporal_address() -> str:
    """Get Temporal server address (env: TEMPORAL_ADDRESS)"""
    return os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
