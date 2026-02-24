"""Configuration helpers (env-only)."""

import os
from pathlib import Path


def get_storage_dir() -> Path:
    """Get artifacts storage directory from env."""
    storage_path = os.environ.get("ARTIFACTS_DIR", "artifacts")
    path = Path(storage_path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_redis_url() -> str:
    """Get Redis URL for pub/sub from env."""
    return os.environ.get("REDIS_URL", "redis://localhost:6379")


def get_gateway_url() -> str:
    """Get gateway URL for notifications from env."""
    return os.environ.get("GATEWAY_URL", "http://localhost:8001")


def get_temporal_address() -> str:
    """Get Temporal server address (env: TEMPORAL_ADDRESS)"""
    return os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
