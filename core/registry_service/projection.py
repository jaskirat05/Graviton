"""Redis-backed projection store for registry service."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from redis.asyncio import Redis


@dataclass
class ServerProjection:
    id: str
    name: str
    provider: str
    address: str
    port: Optional[int]
    ssl: bool
    status: str = "registered"
    tags: Dict[str, Any] = field(default_factory=dict)
    weight: int = 1


@dataclass
class HealthProjection:
    server_id: str
    health_state: str = "stale"
    reason: str = "no pings yet"
    last_seen_at: Optional[str] = None
    last_ok_at: Optional[str] = None
    consecutive_failures: int = 0
    latency_ms: Optional[float] = None
    queue_depth: Optional[int] = None
    gpu_utilization: Optional[float] = None
    vram_free_mb: Optional[float] = None


@dataclass
class ServerObjectInfoProjection:
    server_id: str
    server_name: str
    updated_at: str
    node_count: int
    node_classes: List[str] = field(default_factory=list)
    object_info: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkerControlSecretProjection:
    server_id: str
    server_name: str
    worker_id: str
    shared_secret: str
    secret_version: int
    created_at: str
    rotated_at: Optional[str] = None


@dataclass
class ControlPlaneStateProjection:
    settings_hash: str
    settings: Dict[str, Any] = field(default_factory=dict)
    config_version: Optional[str] = None
    updated_at: str = ""
    last_applied_at: Optional[str] = None


@dataclass
class WorkerConfigPushJobProjection:
    id: str
    server_id: str
    server_name: str
    target_hash: str
    status: str
    attempts: int
    last_error: Optional[str]
    next_retry_at: Optional[str]
    updated_at: str
    created_at: str


class ProjectionStore:
    def __init__(self):
        self.redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        self._redis: Optional[Redis] = None

    async def connect(self) -> None:
        self._redis = Redis.from_url(self.redis_url, decode_responses=True)
        await self._redis.ping()

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.close()

    def _require_redis(self) -> Redis:
        if self._redis is None:
            raise RuntimeError("ProjectionStore is not connected")
        return self._redis

    @staticmethod
    def _server_key(server_id: str) -> str:
        return f"registry:server:{server_id}"

    @staticmethod
    def _server_name_key(server_name: str) -> str:
        return f"registry:server_name:{server_name}"

    @staticmethod
    def _health_key(server_id: str) -> str:
        return f"registry:health:{server_id}"

    @staticmethod
    def _template_hash_key(content_hash: str) -> str:
        return f"registry:template_hash:{content_hash}"

    @staticmethod
    def _template_hashes_key(template_name: str) -> str:
        return f"registry:template_hashes:{template_name}"

    @staticmethod
    def _server_object_info_key(server_id: str) -> str:
        return f"registry:server_object_info:{server_id}"

    @staticmethod
    def _dataplane_mode_key() -> str:
        return "registry:dataplane_mode"

    @staticmethod
    def _worker_control_secret_key(server_id: str) -> str:
        return f"registry:worker_control_secret:{server_id}"

    @staticmethod
    def _control_plane_state_key() -> str:
        return "registry:control_plane_state"

    @staticmethod
    def _worker_config_push_job_key(job_id: str) -> str:
        return f"registry:worker_config_push_job:{job_id}"

    @staticmethod
    def _worker_config_push_jobs_index_key() -> str:
        return "registry:worker_config_push_jobs:index"

    @staticmethod
    def _worker_config_push_jobs_server_index_key(server_id: str) -> str:
        return f"registry:worker_config_push_jobs:server:{server_id}"

    @staticmethod
    def _to_server_projection(raw: Dict[str, Any]) -> ServerProjection:
        port_val = raw.get("port")
        return ServerProjection(
            id=raw["id"],
            name=raw["name"],
            provider=raw.get("provider", "comfyui"),
            address=raw.get("address", ""),
            port=int(port_val) if port_val not in (None, "", "None") else None,
            ssl=str(raw.get("ssl", "False")).lower() == "true",
            status=raw.get("status", "registered"),
            tags=json.loads(raw.get("tags", "{}")),
            weight=int(raw.get("weight", 1)),
        )

    @staticmethod
    def _to_health_projection(server_id: str, raw: Dict[str, Any]) -> HealthProjection:
        def _to_int(v):
            return None if v in (None, "", "None") else int(v)

        def _to_float(v):
            return None if v in (None, "", "None") else float(v)

        return HealthProjection(
            server_id=server_id,
            health_state=raw.get("health_state", "stale"),
            reason=raw.get("reason", "no pings yet"),
            last_seen_at=raw.get("last_seen_at") or None,
            last_ok_at=raw.get("last_ok_at") or None,
            consecutive_failures=int(raw.get("consecutive_failures", 0)),
            latency_ms=_to_float(raw.get("latency_ms")),
            queue_depth=_to_int(raw.get("queue_depth")),
            gpu_utilization=_to_float(raw.get("gpu_utilization")),
            vram_free_mb=_to_float(raw.get("vram_free_mb")),
        )

    @staticmethod
    def _to_object_info_projection(
        server_id: str, raw: Dict[str, Any]
    ) -> ServerObjectInfoProjection:
        node_classes = json.loads(raw.get("node_classes", "[]"))
        object_info = json.loads(raw.get("object_info", "{}"))
        return ServerObjectInfoProjection(
            server_id=server_id,
            server_name=raw.get("server_name", ""),
            updated_at=raw.get("updated_at", ""),
            node_count=int(raw.get("node_count", 0)),
            node_classes=node_classes if isinstance(node_classes, list) else [],
            object_info=object_info if isinstance(object_info, dict) else {},
        )

    @staticmethod
    def _to_worker_control_secret_projection(
        server_id: str, raw: Dict[str, Any]
    ) -> WorkerControlSecretProjection:
        return WorkerControlSecretProjection(
            server_id=server_id,
            server_name=raw.get("server_name", ""),
            worker_id=raw.get("worker_id", ""),
            shared_secret=raw.get("shared_secret", ""),
            secret_version=int(raw.get("secret_version", 1)),
            created_at=raw.get("created_at", ""),
            rotated_at=raw.get("rotated_at") or None,
        )

    @staticmethod
    def _to_control_plane_state_projection(raw: Dict[str, Any]) -> ControlPlaneStateProjection:
        settings = json.loads(raw.get("settings", "{}"))
        if not isinstance(settings, dict):
            settings = {}
        return ControlPlaneStateProjection(
            settings_hash=raw.get("settings_hash", ""),
            settings=settings,
            config_version=raw.get("config_version") or None,
            updated_at=raw.get("updated_at", ""),
            last_applied_at=raw.get("last_applied_at") or None,
        )

    @staticmethod
    def _to_worker_config_push_job_projection(
        job_id: str, raw: Dict[str, Any]
    ) -> WorkerConfigPushJobProjection:
        return WorkerConfigPushJobProjection(
            id=job_id,
            server_id=raw.get("server_id", ""),
            server_name=raw.get("server_name", ""),
            target_hash=raw.get("target_hash", ""),
            status=raw.get("status", "pending"),
            attempts=int(raw.get("attempts", 0)),
            last_error=raw.get("last_error") or None,
            next_retry_at=raw.get("next_retry_at") or None,
            updated_at=raw.get("updated_at", ""),
            created_at=raw.get("created_at", ""),
        )

    async def upsert_server(self, data: Dict[str, Any]) -> ServerProjection:
        redis = self._require_redis()
        existing_id = await redis.get(self._server_name_key(data["name"]))

        if existing_id:
            server_id = existing_id
        else:
            server_id = str(uuid4())

        tags_json = json.dumps(data.get("tags", {}), ensure_ascii=False)
        mapping = {
            "id": server_id,
            "name": data["name"],
            "provider": data.get("provider", "comfyui"),
            "address": data.get("address", ""),
            "port": "" if data.get("port") is None else str(data.get("port")),
            "ssl": str(bool(data.get("ssl", False))),
            "status": data.get("status", "registered"),
            "tags": tags_json,
            "weight": str(int(data.get("weight", 1))),
        }
        await redis.hset(self._server_key(server_id), mapping=mapping)
        await redis.set(self._server_name_key(data["name"]), server_id)
        await redis.sadd("registry:servers", server_id)

        existing_health = await redis.hgetall(self._health_key(server_id))
        if not existing_health:
            await self.save_health(HealthProjection(server_id=server_id))

        raw = await redis.hgetall(self._server_key(server_id))
        return self._to_server_projection(raw)

    async def get_server(self, server_id: str) -> Optional[ServerProjection]:
        redis = self._require_redis()
        raw = await redis.hgetall(self._server_key(server_id))
        if not raw:
            return None
        return self._to_server_projection(raw)

    async def get_server_by_name(self, server_name: str) -> Optional[ServerProjection]:
        redis = self._require_redis()
        server_id = await redis.get(self._server_name_key(server_name))
        if not server_id:
            return None
        return await self.get_server(server_id)

    async def list_servers(self) -> List[ServerProjection]:
        redis = self._require_redis()
        server_ids = await redis.smembers("registry:servers")
        servers: List[ServerProjection] = []
        for sid in server_ids:
            srv = await self.get_server(sid)
            if srv:
                servers.append(srv)
        servers.sort(key=lambda s: s.name)
        return servers

    async def delete_server(self, server_id: str) -> bool:
        redis = self._require_redis()
        server = await self.get_server(server_id)
        if server is None:
            return False

        await self.delete_worker_control_secret(server_id)
        await self.delete_worker_config_push_jobs_for_server(server_id)
        await redis.delete(self._server_key(server_id))
        await redis.delete(self._server_name_key(server.name))
        await redis.delete(self._health_key(server_id))
        await redis.delete(self._server_object_info_key(server_id))
        await redis.srem("registry:servers", server_id)
        return True

    async def get_or_create_health(self, server_id: str) -> HealthProjection:
        health = await self.get_health(server_id)
        if health:
            return health
        health = HealthProjection(server_id=server_id)
        await self.save_health(health)
        return health

    async def get_health(self, server_id: str) -> Optional[HealthProjection]:
        redis = self._require_redis()
        raw = await redis.hgetall(self._health_key(server_id))
        if not raw:
            return None
        return self._to_health_projection(server_id, raw)

    async def save_health(self, health: HealthProjection) -> None:
        redis = self._require_redis()
        mapping = {
            "health_state": health.health_state,
            "reason": health.reason,
            "last_seen_at": health.last_seen_at or "",
            "last_ok_at": health.last_ok_at or "",
            "consecutive_failures": str(int(health.consecutive_failures)),
            "latency_ms": "" if health.latency_ms is None else str(float(health.latency_ms)),
            "queue_depth": "" if health.queue_depth is None else str(int(health.queue_depth)),
            "gpu_utilization": "" if health.gpu_utilization is None else str(float(health.gpu_utilization)),
            "vram_free_mb": "" if health.vram_free_mb is None else str(float(health.vram_free_mb)),
        }
        await redis.hset(self._health_key(health.server_id), mapping=mapping)

    async def get_template_by_hash(self, content_hash: str) -> Optional[str]:
        redis = self._require_redis()
        template_name = await redis.get(self._template_hash_key(content_hash))
        return template_name

    async def save_template_hash(self, content_hash: str, template_name: str) -> None:
        redis = self._require_redis()
        previous_template = await redis.get(self._template_hash_key(content_hash))
        if previous_template and previous_template != template_name:
            await redis.srem(self._template_hashes_key(previous_template), content_hash)
        await redis.set(self._template_hash_key(content_hash), template_name)
        await redis.sadd(self._template_hashes_key(template_name), content_hash)

    async def delete_template_hashes(self, template_name: str) -> int:
        redis = self._require_redis()
        hashes_key = self._template_hashes_key(template_name)
        hashes = await redis.smembers(hashes_key)
        removed = 0
        for content_hash in hashes:
            hash_key = self._template_hash_key(content_hash)
            mapped_template = await redis.get(hash_key)
            if mapped_template == template_name:
                await redis.delete(hash_key)
                removed += 1
        await redis.delete(hashes_key)
        return removed

    async def get_data_plane_mode(self) -> Optional[str]:
        redis = self._require_redis()
        value = await redis.get(self._dataplane_mode_key())
        if not value:
            return None
        mode = str(value).strip().lower()
        return mode or None

    async def set_data_plane_mode(self, mode: str) -> str:
        redis = self._require_redis()
        normalized = str(mode).strip().lower()
        await redis.set(self._dataplane_mode_key(), normalized)
        return normalized

    async def save_server_object_info(
        self,
        server_id: str,
        server_name: str,
        object_info: Dict[str, Any],
    ) -> ServerObjectInfoProjection:
        redis = self._require_redis()
        node_classes = sorted(object_info.keys()) if isinstance(object_info, dict) else []
        projection = ServerObjectInfoProjection(
            server_id=server_id,
            server_name=server_name,
            updated_at=self.now_iso(),
            node_count=len(node_classes),
            node_classes=node_classes,
            object_info=object_info if isinstance(object_info, dict) else {},
        )
        await redis.hset(
            self._server_object_info_key(server_id),
            mapping={
                "server_name": projection.server_name,
                "updated_at": projection.updated_at,
                "node_count": str(projection.node_count),
                "node_classes": json.dumps(projection.node_classes, ensure_ascii=False),
                "object_info": json.dumps(projection.object_info, ensure_ascii=False),
            },
        )
        return projection

    async def get_server_object_info(
        self, server_id: str
    ) -> Optional[ServerObjectInfoProjection]:
        redis = self._require_redis()
        raw = await redis.hgetall(self._server_object_info_key(server_id))
        if not raw:
            return None
        return self._to_object_info_projection(server_id, raw)

    async def get_worker_control_secret(
        self, server_id: str
    ) -> Optional[WorkerControlSecretProjection]:
        redis = self._require_redis()
        raw = await redis.hgetall(self._worker_control_secret_key(server_id))
        if not raw:
            return None
        return self._to_worker_control_secret_projection(server_id, raw)

    async def save_worker_control_secret(
        self,
        *,
        server_id: str,
        server_name: str,
        worker_id: str,
        shared_secret: str,
        secret_version: int,
        created_at: str,
        rotated_at: Optional[str] = None,
    ) -> WorkerControlSecretProjection:
        redis = self._require_redis()
        await redis.hset(
            self._worker_control_secret_key(server_id),
            mapping={
                "server_name": server_name,
                "worker_id": worker_id,
                "shared_secret": shared_secret,
                "secret_version": str(secret_version),
                "created_at": created_at,
                "rotated_at": rotated_at or "",
            },
        )
        return WorkerControlSecretProjection(
            server_id=server_id,
            server_name=server_name,
            worker_id=worker_id,
            shared_secret=shared_secret,
            secret_version=secret_version,
            created_at=created_at,
            rotated_at=rotated_at,
        )

    async def delete_worker_control_secret(self, server_id: str) -> int:
        redis = self._require_redis()
        return int(await redis.delete(self._worker_control_secret_key(server_id)))

    async def get_control_plane_state(self) -> Optional[ControlPlaneStateProjection]:
        redis = self._require_redis()
        raw = await redis.hgetall(self._control_plane_state_key())
        if not raw:
            return None
        return self._to_control_plane_state_projection(raw)

    async def save_control_plane_state(
        self,
        *,
        settings_hash: str,
        settings: Dict[str, Any],
        config_version: Optional[str] = None,
        updated_at: Optional[str] = None,
        last_applied_at: Optional[str] = None,
    ) -> ControlPlaneStateProjection:
        redis = self._require_redis()
        now = updated_at or self.now_iso()
        await redis.hset(
            self._control_plane_state_key(),
            mapping={
                "settings_hash": settings_hash,
                "settings": json.dumps(settings, ensure_ascii=False),
                "config_version": config_version or "",
                "updated_at": now,
                "last_applied_at": last_applied_at or "",
            },
        )
        return ControlPlaneStateProjection(
            settings_hash=settings_hash,
            settings=settings,
            config_version=config_version,
            updated_at=now,
            last_applied_at=last_applied_at,
        )

    async def set_control_plane_last_applied(
        self,
        *,
        at: Optional[str] = None,
    ) -> Optional[ControlPlaneStateProjection]:
        redis = self._require_redis()
        raw = await redis.hgetall(self._control_plane_state_key())
        if not raw:
            return None
        last_applied = at or self.now_iso()
        raw["last_applied_at"] = last_applied
        await redis.hset(
            self._control_plane_state_key(),
            mapping={"last_applied_at": last_applied},
        )
        return self._to_control_plane_state_projection(raw)

    async def create_worker_config_push_job(
        self,
        *,
        server_id: str,
        server_name: str,
        target_hash: str,
    ) -> WorkerConfigPushJobProjection:
        redis = self._require_redis()
        now = self.now_iso()
        score = datetime.fromisoformat(now).timestamp()
        job_id = str(uuid4())
        mapping = {
            "server_id": server_id,
            "server_name": server_name,
            "target_hash": target_hash,
            "status": "pending",
            "attempts": "0",
            "last_error": "",
            "next_retry_at": "",
            "updated_at": now,
            "created_at": now,
        }
        await redis.hset(self._worker_config_push_job_key(job_id), mapping=mapping)
        await redis.zadd(self._worker_config_push_jobs_index_key(), {job_id: score})
        await redis.zadd(self._worker_config_push_jobs_server_index_key(server_id), {job_id: score})
        return self._to_worker_config_push_job_projection(job_id, mapping)

    async def update_worker_config_push_job(
        self,
        job_id: str,
        *,
        status: Optional[str] = None,
        attempts: Optional[int] = None,
        last_error: Optional[str] = None,
        next_retry_at: Optional[str] = None,
    ) -> Optional[WorkerConfigPushJobProjection]:
        redis = self._require_redis()
        key = self._worker_config_push_job_key(job_id)
        raw = await redis.hgetall(key)
        if not raw:
            return None

        mapping: Dict[str, str] = {"updated_at": self.now_iso()}
        if status is not None:
            mapping["status"] = status
        if attempts is not None:
            mapping["attempts"] = str(int(attempts))
        if last_error is not None:
            mapping["last_error"] = last_error
        if next_retry_at is not None:
            mapping["next_retry_at"] = next_retry_at
        await redis.hset(key, mapping=mapping)

        refreshed = await redis.hgetall(key)
        return self._to_worker_config_push_job_projection(job_id, refreshed)

    async def list_worker_config_push_jobs(
        self,
        *,
        limit: int = 100,
        server_id: Optional[str] = None,
    ) -> List[WorkerConfigPushJobProjection]:
        redis = self._require_redis()
        index_key = (
            self._worker_config_push_jobs_server_index_key(server_id)
            if server_id
            else self._worker_config_push_jobs_index_key()
        )
        job_ids = await redis.zrevrange(index_key, 0, max(0, int(limit) - 1))
        jobs: List[WorkerConfigPushJobProjection] = []
        for job_id in job_ids:
            raw = await redis.hgetall(self._worker_config_push_job_key(job_id))
            if raw:
                jobs.append(self._to_worker_config_push_job_projection(job_id, raw))
        return jobs

    async def delete_worker_config_push_jobs_for_server(self, server_id: str) -> int:
        redis = self._require_redis()
        server_index_key = self._worker_config_push_jobs_server_index_key(server_id)
        job_ids = await redis.zrange(server_index_key, 0, -1)
        removed = 0
        for job_id in job_ids:
            await redis.delete(self._worker_config_push_job_key(job_id))
            await redis.zrem(self._worker_config_push_jobs_index_key(), job_id)
            removed += 1
        await redis.delete(server_index_key)
        return removed

    @staticmethod
    def now_iso() -> str:
        return datetime.now().astimezone().isoformat()

    @staticmethod
    def parse_iso(ts: Optional[str]) -> Optional[datetime]:
        if not ts:
            return None
        try:
            return datetime.fromisoformat(ts)
        except ValueError:
            return None
