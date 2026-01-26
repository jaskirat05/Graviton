"""
Configuration management - reads from config.yaml with env var overrides
"""

import os
import yaml
from pathlib import Path
from functools import lru_cache
from typing import List, Dict, Any


# Config file path (env: CONFIG_PATH, default: config.yaml in cwd)
CONFIG_PATH = Path(os.environ.get("CONFIG_PATH", "config.yaml"))


@lru_cache
def load_config() -> Dict[str, Any]:
    """Load configuration from config.yaml"""
    if not CONFIG_PATH.exists():
        return {}
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f) or {}


def get_storage_dir() -> Path:
    """Get the artifacts storage directory from config"""
    config = load_config()
    storage_path = config.get("storage", {}).get("artifacts_dir", "artifacts")
    path = Path(storage_path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_servers() -> List[Dict[str, Any]]:
    """Get configured ComfyUI servers from config.yaml"""
    return load_config().get("servers", [])


def get_server(name: str) -> Dict[str, Any]:
    """Get server config by name"""
    for server in get_servers():
        if server.get("name") == name:
            return server
    return {}


def get_default_server() -> Dict[str, Any]:
    """Get the first configured server"""
    servers = get_servers()
    if not servers:
        raise ValueError("No servers configured in config.yaml")
    return servers[0]


def get_redis_url() -> str:
    """Get Redis URL for pub/sub (env: REDIS_URL)"""
    if os.environ.get("REDIS_URL"):
        return os.environ["REDIS_URL"]
    return load_config().get("redis", {}).get("url", "redis://localhost:6379")


def get_gateway_url() -> str:
    """Get gateway URL for building notification URLs (env: GATEWAY_URL)"""
    if os.environ.get("GATEWAY_URL"):
        return os.environ["GATEWAY_URL"]
    return load_config().get("gateway", {}).get("url", "http://localhost:8001")


def get_temporal_address() -> str:
    """Get Temporal server address (env: TEMPORAL_ADDRESS)"""
    return os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
