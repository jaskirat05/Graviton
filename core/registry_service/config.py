"""Configuration for the registry service."""

from __future__ import annotations

import os
from pathlib import Path

from .env import load_root_env

load_root_env()


class Settings:
    service_name: str = os.getenv("REGISTRY_SERVICE_NAME", "registry-service")
    service_version: str = os.getenv("REGISTRY_SERVICE_VERSION", "0.1.0")

    # NATS / JetStream
    nats_url: str = os.getenv("REGISTRY_NATS_URL", "nats://localhost:4222")
    nats_stream: str = os.getenv("REGISTRY_NATS_STREAM", "REGISTRY")
    nats_subject_prefix: str = os.getenv("REGISTRY_NATS_SUBJECT_PREFIX", "registry")

    # Storage (projection db can be split later; sqlite default for local dev)
    database_url: str = os.getenv("REGISTRY_DATABASE_URL", "sqlite:///data/registry_service.db")

    # Health policy
    stale_seconds: int = int(os.getenv("REGISTRY_HEALTH_STALE_SECONDS", "30"))
    unhealthy_failure_threshold: int = int(
        os.getenv("REGISTRY_HEALTH_UNHEALTHY_FAILURE_THRESHOLD", "3")
    )
    degraded_latency_ms: float = float(os.getenv("REGISTRY_HEALTH_DEGRADED_LATENCY_MS", "1500"))
    degraded_queue_depth: int = int(os.getenv("REGISTRY_HEALTH_DEGRADED_QUEUE_DEPTH", "5"))
    degraded_vram_free_mb: float = float(
        os.getenv("REGISTRY_HEALTH_DEGRADED_VRAM_FREE_MB", "1024")
    )
    health_ping_interval_seconds: float = float(
        os.getenv("REGISTRY_HEALTH_PING_INTERVAL_SECONDS", "10")
    )

    # Dedicated template storage (separate from existing legacy templates dir)
    template_root_dir: str = os.getenv("REGISTRY_TEMPLATE_ROOT_DIR", "registry_templates")

    @property
    def template_workflows_dir(self) -> Path:
        return Path(self.template_root_dir) / "workflows"

    @property
    def template_overrides_dir(self) -> Path:
        return Path(self.template_root_dir) / "overrides"


settings = Settings()
