"""Command handlers for registry service."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from core.clients.comfy.http import ComfyHTTPClient
from core.logging_config import get_logger

from .bus import EventBus
from .comfy_checks import build_server_url, run_basic_server_checks
from .control_plane import (
    build_control_plane_config_from_env,
    compute_settings_hash,
    generate_config_version,
    generate_shared_secret,
    redact_control_plane_config,
)
from .events import EventEnvelope, EventTypes
from .health import HealthEvaluator
from .policy import check_template_policy
from .projection import ProjectionStore
from .template_manager import TemplateManager
from .template_store import TemplateStore

logger = get_logger("registry_service.service")


class RegistryService:
    def __init__(
        self,
        bus: EventBus,
        store: ProjectionStore,
        health_evaluator: HealthEvaluator,
        template_store: TemplateStore,
        template_manager: TemplateManager,
    ):
        self.bus = bus
        self.store = store
        self.health_evaluator = health_evaluator
        self.template_store = template_store
        self.template_manager = template_manager

    def _upsert_template_status(
        self,
        template_name: str,
        status: str,
        policy_errors: list[str] | None = None,
    ) -> None:
        self.template_store.upsert_status(
            template_name,
            {
                "template_name": template_name,
                "status": status,
                "policy_errors": policy_errors or [],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    @staticmethod
    def _get_combo_options_from_object_info(
        object_info: dict, class_type: str, input_name: str
    ) -> list | None:
        node_info = object_info.get(class_type)
        if not node_info:
            return None
        input_types = node_info.get("input", {})
        for category in ["required", "optional"]:
            inputs = input_types.get(category, {})
            if input_name in inputs:
                input_def = inputs[input_name]
                if isinstance(input_def, list) and len(input_def) > 0:
                    options = input_def[0]
                    if isinstance(options, list):
                        return options
        return None

    async def upsert_server(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("server_upsert_requested", server=payload.get("name"))
        checks = await run_basic_server_checks(payload)
        if not checks.get("ok"):
            error = checks.get("error", "Server preflight checks failed")
            logger.warning(
                "server_upsert_preflight_failed",
                server=payload.get("name"),
                error=error,
            )
            raise ValueError(f"Server preflight checks failed: {error}")

        server = await self.store.upsert_server(payload)

        envelope = EventEnvelope(
            event_type=EventTypes.SERVER_REGISTERED,
            aggregate_type="server",
            aggregate_id=server.id,
            payload={
                "id": server.id,
                "name": server.name,
                "provider": server.provider,
                "address": server.address,
                "port": server.port,
                "ssl": server.ssl,
                "tags": server.tags,
                "weight": server.weight,
                "preflight": {
                    "server_url": checks.get("server_url"),
                    "gpu_count": checks.get("gpu_count"),
                    "node_count": checks.get("node_count"),
                },
            },
        )
        await self.bus.publish(envelope)
        logger.info("server_registered_event_published", server=server.name, server_id=server.id)

        return {
            "id": server.id,
            "name": server.name,
            "provider": server.provider,
            "address": server.address,
            "port": server.port,
            "ssl": server.ssl,
            "status": server.status,
            "tags": server.tags,
            "weight": server.weight,
        }

    async def ingest_ping(self, server_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        ping_event = EventEnvelope(
            event_type=EventTypes.SERVER_PING_RECEIVED,
            aggregate_type="server",
            aggregate_id=server_id,
            payload={
                "server_id": server_id,
                **payload,
            },
        )
        await self.bus.publish(ping_event)

        health = await self.health_evaluator.evaluate_ping(server_id, payload)

        health_event = EventEnvelope(
            event_type=EventTypes.SERVER_HEALTH_EVALUATED,
            aggregate_type="server",
            aggregate_id=server_id,
            payload={
                "server_id": health.server_id,
                "health_state": health.health_state,
                "reason": health.reason,
                "last_seen_at": health.last_seen_at,
                "last_ok_at": health.last_ok_at,
                "consecutive_failures": health.consecutive_failures,
            },
        )
        await self.bus.publish(health_event)
        logger.info(
            "server_health_evaluated",
            server_id=server_id,
            health_state=health.health_state,
        )

        return {
            "server_id": health.server_id,
            "health_state": health.health_state,
            "reason": health.reason,
            "last_seen_at": health.last_seen_at,
        }

    async def get_server_health(self, server_id: str) -> Dict[str, Any]:
        health = await self.store.get_health(server_id)
        if not health:
            raise ValueError(f"Server health not found: {server_id}")
        health = self.health_evaluator.apply_staleness(health)
        return {
            "server_id": health.server_id,
            "health_state": health.health_state,
            "reason": health.reason,
            "last_seen_at": health.last_seen_at,
        }

    async def get_eligible_servers(self) -> Dict[str, Any]:
        servers = []
        for server in await self.store.list_servers():
            health = await self.store.get_health(server.id)
            if not health:
                continue
            health = self.health_evaluator.apply_staleness(health)
            if health.health_state not in {"healthy", "degraded"}:
                continue
            if server.status not in {"registered"}:
                continue
            servers.append(
                {
                    "id": server.id,
                    "name": server.name,
                    "provider": server.provider,
                    "address": server.address,
                    "port": server.port,
                    "ssl": server.ssl,
                    "status": server.status,
                    "weight": server.weight,
                    "health_state": health.health_state,
                    "health_reason": health.reason,
                    "queue_depth": health.queue_depth,
                }
            )
        return {"servers": servers, "count": len(servers)}

    async def list_servers(self) -> Dict[str, Any]:
        servers = []
        for server in await self.store.list_servers():
            servers.append(
                {
                    "id": server.id,
                    "name": server.name,
                    "provider": server.provider,
                    "address": server.address,
                    "port": server.port,
                    "ssl": server.ssl,
                    "status": server.status,
                    "tags": server.tags,
                    "weight": server.weight,
                }
            )
        return {"servers": servers, "count": len(servers)}

    async def get_server_by_name(self, server_name: str) -> Dict[str, Any]:
        server = await self.store.get_server_by_name(server_name)
        if not server:
            raise ValueError(f"Server not found: {server_name}")
        return {
            "id": server.id,
            "name": server.name,
            "provider": server.provider,
            "address": server.address,
            "port": server.port,
            "ssl": server.ssl,
            "status": server.status,
            "tags": server.tags,
            "weight": server.weight,
        }

    async def sync_server_templates(self, server_id: str, force: bool = False) -> Dict[str, Any]:
        server = await self.store.get_server(server_id)
        if not server:
            raise ValueError(f"Server not found: {server_id}")

        await self.bus.publish(
            EventEnvelope(
                event_type=EventTypes.SERVER_REGISTERED,
                aggregate_type="server",
                aggregate_id=server.id,
                payload={
                    "id": server.id,
                    "name": server.name,
                    "provider": server.provider,
                    "address": server.address,
                    "port": server.port,
                    "ssl": server.ssl,
                    "tags": server.tags,
                    "weight": server.weight,
                    "force": force,
                },
            )
        )
        logger.info(
            "server_template_sync_requested",
            server_id=server.id,
            server_name=server.name,
            force=force,
        )
        return {"server_id": server.id, "server_name": server.name, "sync_requested": True, "force": force}

    async def update_data_plane_mode(self, mode: str) -> Dict[str, Any]:
        normalized = str(mode).strip().lower()
        if normalized not in {"local", "orchestrator", "s3", "cloudinary"}:
            raise ValueError("mode must be one of: local, orchestrator, s3, cloudinary")
        await self.store.set_data_plane_mode(normalized)

        await self.bus.publish(
            EventEnvelope(
                event_type=EventTypes.DATA_PLANE_MODE_UPDATED,
                aggregate_type="server",
                aggregate_id="dataplane",
                payload={"mode": normalized},
            )
        )
        logger.info("data_plane_mode_update_event_published", mode=normalized)
        return {"mode": normalized, "event_published": True}

    async def get_data_plane_mode(self) -> str:
        mode = await self.store.get_data_plane_mode()
        return mode or "local"

    async def register_worker_control_secret(
        self,
        server_id: str,
        rotate: bool = False,
    ) -> Dict[str, Any]:
        server = await self.store.get_server(server_id)
        if not server:
            raise ValueError(f"Server not found: {server_id}")

        server_url = build_server_url(
            {"address": server.address, "port": server.port, "ssl": server.ssl}
        )
        client = ComfyHTTPClient(server_url)
        try:
            status = await client.get_bridge_control_status()
        finally:
            await client.close()

        worker_id = str(
            status.get("worker_id")
            or status.get("workerId")
            or status.get("id")
            or server.name
        )
        existing = await self.store.get_worker_control_secret(server.id)
        if existing and not rotate:
            raise ValueError(
                "Worker control secret already exists. Use rotate=true to rotate and reveal a new secret."
            )

        now = self.store.now_iso()
        projection = await self.store.save_worker_control_secret(
            server_id=server.id,
            server_name=server.name,
            worker_id=worker_id,
            shared_secret=generate_shared_secret(),
            secret_version=(existing.secret_version + 1) if existing else 1,
            created_at=existing.created_at if existing else now,
            rotated_at=now if existing else None,
        )
        logger.info(
            "worker_control_secret_registered",
            server_id=server.id,
            server_name=server.name,
            worker_id=worker_id,
            rotate=rotate,
            secret_version=projection.secret_version,
        )
        return {
            "server_id": projection.server_id,
            "server_name": projection.server_name,
            "worker_id": projection.worker_id,
            "secret_version": projection.secret_version,
            "shared_secret": projection.shared_secret,
            "created_at": projection.created_at,
            "rotated_at": projection.rotated_at,
        }

    async def get_worker_control_secret_meta(self, server_id: str) -> Dict[str, Any]:
        server = await self.store.get_server(server_id)
        if not server:
            raise ValueError(f"Server not found: {server_id}")
        projection = await self.store.get_worker_control_secret(server.id)
        if not projection:
            raise ValueError(f"Worker control secret not found: {server.id}")
        return {
            "server_id": projection.server_id,
            "server_name": projection.server_name,
            "worker_id": projection.worker_id,
            "secret_version": projection.secret_version,
            "created_at": projection.created_at,
            "rotated_at": projection.rotated_at,
        }

    async def read_control_plane_settings(
        self,
        *,
        publish_event: bool = False,
        force: bool = False,
        target_server_ids: Optional[list[str]] = None,
    ) -> Dict[str, Any]:
        base_settings = build_control_plane_config_from_env()
        settings_hash = compute_settings_hash(base_settings)
        existing = await self.store.get_control_plane_state()
        has_changed = existing is None or existing.settings_hash != settings_hash
        if has_changed:
            config_version = generate_config_version(5)
        else:
            config_version = existing.config_version or str(existing.settings.get("config_version", "")).strip() or generate_config_version(5)
        settings = dict(base_settings)
        settings["config_version"] = config_version
        updated_at = existing.updated_at if existing and not has_changed else self.store.now_iso()
        projection = await self.store.save_control_plane_state(
            settings_hash=settings_hash,
            settings=settings,
            config_version=config_version,
            updated_at=updated_at,
            last_applied_at=existing.last_applied_at if existing else None,
        )
        event_published = False
        if publish_event and (has_changed or force):
            await self.bus.publish(
                EventEnvelope(
                    event_type=EventTypes.CONTROL_PLANE_SETTINGS_UPDATED,
                    aggregate_type="control_plane",
                    aggregate_id="settings",
                    payload={
                        "settings_hash": settings_hash,
                        "force": bool(force),
                        "target_server_ids": target_server_ids or [],
                    },
                )
            )
            event_published = True

        return {
            "settings_hash": projection.settings_hash,
            "settings": projection.settings,
            "config_version": projection.config_version,
            "updated_at": projection.updated_at,
            "last_applied_at": projection.last_applied_at,
            "has_changed": has_changed,
            "event_published": event_published,
        }

    async def get_control_plane_settings(self) -> Dict[str, Any]:
        state = await self.read_control_plane_settings(publish_event=False, force=False)
        return {
            "settings_hash": state["settings_hash"],
            "settings": redact_control_plane_config(state["settings"]),
            "config_version": state.get("config_version"),
            "updated_at": state["updated_at"],
            "last_applied_at": state["last_applied_at"],
        }

    async def trigger_control_plane_sync(self, force: bool = False) -> Dict[str, Any]:
        state = await self.read_control_plane_settings(
            publish_event=True,
            force=force,
        )
        return {
            "settings_hash": state["settings_hash"],
            "config_version": state.get("config_version"),
            "settings_changed": bool(state["has_changed"]),
            "updated_at": state["updated_at"],
            "last_applied_at": state["last_applied_at"],
            "event_published": state["event_published"],
        }

    async def trigger_server_control_plane_sync(
        self, server_id: str, force: bool = True
    ) -> Dict[str, Any]:
        server = await self.store.get_server(server_id)
        if not server:
            raise ValueError(f"Server not found: {server_id}")
        state = await self.read_control_plane_settings(
            publish_event=True,
            force=force,
            target_server_ids=[server.id],
        )
        return {
            "server_id": server.id,
            "server_name": server.name,
            "settings_hash": state["settings_hash"],
            "settings_changed": bool(state["has_changed"]),
            "event_published": state["event_published"],
            "force": force,
        }

    async def get_server_control_plane_status(self, server_id: str) -> Dict[str, Any]:
        server = await self.store.get_server(server_id)
        if not server:
            raise ValueError(f"Server not found: {server_id}")

        state = await self.read_control_plane_settings(publish_event=False, force=False)
        desired = state["settings"]
        desired_redacted = redact_control_plane_config(desired)
        desired_hash = state["settings_hash"]
        desired_version = str(desired.get("config_version", "")).strip() or None

        server_url = build_server_url(
            {"address": server.address, "port": server.port, "ssl": server.ssl}
        )
        client = ComfyHTTPClient(server_url)
        try:
            remote_payload = await client.get_bridge_config()
            remote_config = remote_payload.get("config")
            if not isinstance(remote_config, dict):
                remote_config = {}
            observed_version = str(remote_config.get("config_version", "")).strip() or None
            observed_hash = compute_settings_hash(remote_config)
            return {
                "server_id": server.id,
                "server_name": server.name,
                "desired_hash": desired_hash,
                "observed_hash": observed_hash,
                "desired_version": desired_version,
                "observed_version": observed_version,
                "desired_mode": desired_redacted.get("mode"),
                "observed_mode": remote_config.get("mode"),
                "is_outdated": bool(desired_version and observed_version != desired_version),
                "reachable": True,
                "error": None,
            }
        except Exception as error:
            return {
                "server_id": server.id,
                "server_name": server.name,
                "desired_hash": desired_hash,
                "observed_hash": None,
                "desired_version": desired_version,
                "observed_version": None,
                "desired_mode": desired_redacted.get("mode"),
                "observed_mode": None,
                "is_outdated": False,
                "reachable": False,
                "error": str(error),
            }
        finally:
            await client.close()

    async def list_worker_config_push_jobs(
        self,
        *,
        limit: int = 100,
        server_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        jobs = await self.store.list_worker_config_push_jobs(limit=limit, server_id=server_id)
        return {
            "jobs": [
                {
                    "id": job.id,
                    "server_id": job.server_id,
                    "server_name": job.server_name,
                    "target_hash": job.target_hash,
                    "status": job.status,
                    "attempts": job.attempts,
                    "last_error": job.last_error,
                    "next_retry_at": job.next_retry_at,
                    "updated_at": job.updated_at,
                    "created_at": job.created_at,
                }
                for job in jobs
            ],
            "count": len(jobs),
        }

    async def delete_server(self, server_id: str) -> Dict[str, Any]:
        server = await self.store.get_server(server_id)
        if not server:
            raise ValueError(f"Server not found: {server_id}")
        deleted = await self.store.delete_server(server_id)
        return {
            "server_id": server_id,
            "server_name": server.name,
            "deleted": bool(deleted),
        }

    async def refresh_server_object_info(self, server_id: str) -> Dict[str, Any]:
        server = await self.store.get_server(server_id)
        if not server:
            raise ValueError(f"Server not found: {server_id}")

        server_url = build_server_url(
            {"address": server.address, "port": server.port, "ssl": server.ssl}
        )
        client = ComfyHTTPClient(server_url)
        try:
            object_info = await client.get_object_info()
        finally:
            await client.close()

        projection = await self.store.save_server_object_info(
            server_id=server.id,
            server_name=server.name,
            object_info=object_info if isinstance(object_info, dict) else {},
        )
        logger.info(
            "server_object_info_projection_refreshed",
            server_id=server.id,
            server_name=server.name,
            node_count=projection.node_count,
        )
        return {
            "server_id": projection.server_id,
            "server_name": projection.server_name,
            "updated_at": projection.updated_at,
            "node_count": projection.node_count,
            "node_classes": projection.node_classes,
        }

    async def get_server_object_info(
        self, server_id: str, include_full: bool = False
    ) -> Dict[str, Any]:
        server = await self.store.get_server(server_id)
        if not server:
            raise ValueError(f"Server not found: {server_id}")

        projection = await self.store.get_server_object_info(server_id)
        if not projection:
            raise ValueError(f"Object info projection not found: {server_id}")

        response = {
            "server_id": projection.server_id,
            "server_name": projection.server_name,
            "updated_at": projection.updated_at,
            "node_count": projection.node_count,
            "node_classes": projection.node_classes,
        }
        if include_full:
            response["object_info"] = projection.object_info
        return response

    async def upsert_template_workflow(
        self,
        template_name: str,
        workflow: Dict[str, Any],
        force: bool = False,
    ) -> Dict[str, Any]:
        workflow_to_persist = copy.deepcopy(workflow)
        workflow_to_persist.pop("_ui_metadata", None)
        policy_result = check_template_policy(template_name, workflow_to_persist)
        result = await self.template_manager.upsert_workflow(
            template_name, workflow_to_persist, force=force
        )
        path = self.template_store._workflow_path(template_name)  # noqa: SLF001
        if result.get("skipped"):
            new_status = "active" if policy_result["valid"] else "invalid_policy"
            self._upsert_template_status(
                template_name,
                new_status,
                policy_errors=policy_result["errors"],
            )
            status_doc = self.template_store.get_status(template_name) or {}
            template_status = status_doc.get("status", "active")
            policy_errors = status_doc.get("policy_errors", [])
            logger.info(
                "template_workflow_skipped_hash_match",
                template=template_name,
                workflow_hash=result.get("workflow_hash"),
                existing_template=result.get("existing_template"),
                template_status=template_status,
            )
            return {
                "template_name": template_name,
                "path": str(path),
                "workflow_hash": result.get("workflow_hash"),
                "skipped": True,
                "existing_template": result.get("existing_template"),
                "status": template_status,
                "policy_errors": policy_errors,
                "force": force,
            }

        if not policy_result["valid"]:
            self._upsert_template_status(
                template_name,
                "invalid_policy",
                policy_errors=policy_result["errors"],
            )
        else:
            self._upsert_template_status(template_name, "active")

        await self.bus.publish(
            EventEnvelope(
                event_type=EventTypes.TEMPLATE_WORKFLOW_UPSERTED,
                aggregate_type="template",
                aggregate_id=template_name,
                payload={
                    "template_name": template_name,
                    "path": str(path),
                    "workflow_hash": result.get("workflow_hash"),
                    "status": "active" if policy_result["valid"] else "invalid_policy",
                    "policy_errors": policy_result["errors"],
                },
            )
        )
        if policy_result["valid"]:
            logger.info(
                "template_workflow_upserted",
                template=template_name,
                workflow_hash=result.get("workflow_hash"),
            )
        else:
            logger.warning(
                "template_workflow_policy_invalid",
                template=template_name,
                workflow_hash=result.get("workflow_hash"),
                policy_errors=policy_result["errors"],
            )
        return {
            "template_name": template_name,
            "path": str(path),
            "workflow_hash": result.get("workflow_hash"),
            "skipped": False,
            "status": "active" if policy_result["valid"] else "invalid_policy",
            "policy_errors": policy_result["errors"],
            "output_nodes": policy_result.get("output_nodes", []),
            "force": force,
        }

    async def upsert_template_overrides(
        self, template_name: str, overrides: Dict[str, Any]
    ) -> Dict[str, Any]:
        path = self.template_store.upsert_overrides(template_name, overrides)
        await self.bus.publish(
            EventEnvelope(
                event_type=EventTypes.TEMPLATE_OVERRIDES_UPSERTED,
                aggregate_type="template_override_set",
                aggregate_id=template_name,
                payload={"template_name": template_name, "path": str(path)},
            )
        )
        return {"template_name": template_name, "path": str(path)}

    async def patch_template_overrides(
        self,
        template_name: str,
        upserts: list[Dict[str, Any]],
        remove_keys: list[str],
    ) -> Dict[str, Any]:
        overrides = self.template_manager.patch_overrides(
            template_name, upserts=upserts, remove_keys=remove_keys
        )
        path = self.template_store._overrides_path(template_name)  # noqa: SLF001
        await self.bus.publish(
            EventEnvelope(
                event_type=EventTypes.TEMPLATE_OVERRIDES_UPSERTED,
                aggregate_type="template_override_set",
                aggregate_id=template_name,
                payload={
                    "template_name": template_name,
                    "path": str(path),
                    "patch": True,
                    "parameter_count": len(overrides.get("parameters", [])),
                },
            )
        )
        return {"template_name": template_name, "path": str(path), "overrides": overrides}

    async def generate_template_overrides(self, template_name: str) -> Dict[str, Any]:
        overrides = self.template_manager.generate_default_overrides(template_name)
        path = self.template_store._overrides_path(template_name)  # noqa: SLF001
        await self.bus.publish(
            EventEnvelope(
                event_type=EventTypes.TEMPLATE_OVERRIDES_UPSERTED,
                aggregate_type="template_override_set",
                aggregate_id=template_name,
                payload={
                    "template_name": template_name,
                    "path": str(path),
                    "generated": True,
                    "parameter_count": len(overrides.get("parameters", [])),
                },
            )
        )
        return {"template_name": template_name, "path": str(path), "overrides": overrides}

    async def apply_template_overrides(
        self, template_name: str, runtime_overrides: Dict[str, Any]
    ) -> Dict[str, Any]:
        workflow = self.template_manager.apply_runtime_overrides(
            template_name, runtime_overrides
        )
        return {"template_name": template_name, "workflow": workflow}

    async def delete_template(self, template_name: str) -> Dict[str, Any]:
        result = self.template_manager.delete_template(template_name)
        self.template_store.delete_status(template_name)
        await self.store.delete_template_hashes(template_name)
        return result

    async def refresh_validated_servers(self, template_name: str) -> Dict[str, Any]:
        status_doc = self.template_store.get_status(template_name) or {}
        template_status = status_doc.get("status", "active")
        if template_status != "active":
            logger.info(
                "template_validation_skipped_non_active",
                template_name=template_name,
                status=template_status,
            )
            return {
                "template_name": template_name,
                "validated_servers": [],
                "validated_count": 0,
                "skipped": True,
                "status": template_status,
                "policy_errors": status_doc.get("policy_errors", []),
            }

        workflow = self.template_store.get_workflow(template_name)
        if workflow is None:
            raise ValueError(f"Template workflow not found: {template_name}")

        overrides = self.template_store.get_overrides(template_name)
        if overrides is None:
            raise ValueError(f"Template overrides not found: {template_name}")

        prompt = {k: v for k, v in workflow.items() if not str(k).startswith("_")}
        servers = await self.store.list_servers()
        validated_servers: list[str] = []

        for server in servers:
            if server.status != "registered":
                continue

            server_url = build_server_url(
                {"address": server.address, "port": server.port, "ssl": server.ssl}
            )
            client = ComfyHTTPClient(server_url)
            try:
                object_info = await client.get_object_info()
            except Exception as e:
                logger.warning(
                    "template_validation_server_fetch_failed",
                    template_name=template_name,
                    server_name=server.name,
                    server_url=server_url,
                    error=str(e),
                )
                await client.close()
                continue
            await client.close()

            missing_nodes = False
            invalid_inputs = False
            for _, node_data in prompt.items():
                if not isinstance(node_data, dict):
                    continue
                class_type = node_data.get("class_type")
                if not class_type:
                    continue

                if class_type not in object_info:
                    missing_nodes = True
                    break

                for input_name, value in node_data.get("inputs", {}).items():
                    if isinstance(value, list) or not isinstance(value, str):
                        continue
                    options = self._get_combo_options_from_object_info(
                        object_info, class_type, input_name
                    )
                    if options is not None and value not in options:
                        invalid_inputs = True
                        break
                if invalid_inputs:
                    break

            if not missing_nodes and not invalid_inputs:
                validated_servers.append(server.name)

        merged = copy.deepcopy(overrides)
        merged["validated_servers"] = sorted(set(validated_servers))
        self.template_store.upsert_overrides(template_name, merged)
        logger.info(
            "template_validated_servers_refreshed",
            template_name=template_name,
            validated_count=len(merged["validated_servers"]),
            registered_servers=len([s for s in servers if s.status == "registered"]),
        )
        return {
            "template_name": template_name,
            "validated_servers": merged["validated_servers"],
            "validated_count": len(merged["validated_servers"]),
        }
