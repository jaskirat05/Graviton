"""Health evaluation for server ping events."""

from __future__ import annotations

from datetime import datetime, timezone

from .config import settings
from .projection import HealthProjection, ProjectionStore


class HealthEvaluator:
    def __init__(self, store: ProjectionStore):
        self.store = store

    async def evaluate_ping(self, server_id: str, ping: dict) -> HealthProjection:
        health = await self.store.get_or_create_health(server_id)
        health.last_seen_at = self.store.now_iso()
        health.latency_ms = ping.get("latency_ms")
        health.queue_depth = ping.get("queue_depth")
        health.gpu_utilization = ping.get("gpu_utilization")
        health.vram_free_mb = ping.get("vram_free_mb")

        ok = ping.get("ok", False)
        if ok:
            health.consecutive_failures = 0
            health.last_ok_at = health.last_seen_at
            health.health_state = "healthy"
            health.reason = "ok"

            degraded_reasons = []
            if (
                health.latency_ms is not None
                and health.latency_ms > settings.degraded_latency_ms
            ):
                degraded_reasons.append(f"latency>{settings.degraded_latency_ms}ms")
            if (
                health.queue_depth is not None
                and health.queue_depth >= settings.degraded_queue_depth
            ):
                degraded_reasons.append(f"queue>={settings.degraded_queue_depth}")
            if (
                health.vram_free_mb is not None
                and health.vram_free_mb < settings.degraded_vram_free_mb
            ):
                degraded_reasons.append(f"vram_free<{settings.degraded_vram_free_mb}mb")

            if degraded_reasons:
                health.health_state = "degraded"
                health.reason = ", ".join(degraded_reasons)
            await self.store.save_health(health)
            return health

        health.consecutive_failures += 1
        if health.consecutive_failures >= settings.unhealthy_failure_threshold:
            health.health_state = "unhealthy"
            health.reason = (
                f"consecutive_failures>={settings.unhealthy_failure_threshold}"
            )
        else:
            health.health_state = "degraded"
            health.reason = ping.get("error") or "ping failed"

        await self.store.save_health(health)
        return health

    def apply_staleness(self, health: HealthProjection) -> HealthProjection:
        if not health.last_seen_at:
            health.health_state = "stale"
            health.reason = "no pings yet"
            return health

        seen = self.store.parse_iso(health.last_seen_at)
        if not seen:
            health.health_state = "stale"
            health.reason = "invalid timestamp"
            return health

        elapsed_seconds = (datetime.now(timezone.utc) - seen).total_seconds()
        if elapsed_seconds > settings.stale_seconds:
            health.health_state = "stale"
            health.reason = f"last ping older than {settings.stale_seconds}s"
        return health
