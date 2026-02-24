"""JetStream consumers for registry service domain events."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone

from core.clients.comfy.http import ComfyHTTPClient
from core.config import get_temporal_address
from core.logging_config import get_logger
from temporalio.client import Client as TemporalClient
from temporalio.exceptions import WorkflowAlreadyStartedError

from .comfy_checks import build_server_url
from .config import settings
from .events import EventEnvelope, EventTypes
from .jetstream_bus import JetStreamEventBus
from .node_definitions import NodeDefinitionsService
from .realtime import RegistryEventHub
from .service import RegistryService

logger = get_logger("registry_service.consumers")
_health_ping_tasks: dict[str, asyncio.Task] = {}
_temporal_client: TemporalClient | None = None


async def _get_temporal_client() -> TemporalClient:
    global _temporal_client
    if _temporal_client is None:
        _temporal_client = await TemporalClient.connect(get_temporal_address())
    return _temporal_client


def _extract_vram_free_mb(stats: dict) -> float | None:
    devices = stats.get("devices", [])
    if not isinstance(devices, list) or not devices:
        return None

    total_free = 0.0
    has_value = False
    for device in devices:
        if not isinstance(device, dict):
            continue
        vram_total = device.get("vram_total")
        vram_used = device.get("vram_used")
        if isinstance(vram_total, (int, float)) and isinstance(vram_used, (int, float)):
            total_free += max(0.0, float(vram_total) - float(vram_used))
            has_value = True
    return total_free if has_value else None


async def _run_server_health_ping_loop(
    service: RegistryService,
    event_hub: RegistryEventHub,
    server_id: str,
    server_name: str,
    server_url: str,
) -> None:
    logger.info(
        "server_health_ping_loop_started",
        server_id=server_id,
        server_name=server_name,
        server_url=server_url,
        interval_seconds=settings.health_ping_interval_seconds,
    )
    last_ping_ok: bool | None = None
    while True:
        server = await service.store.get_server(server_id)
        if server is None:
            logger.info("server_health_ping_loop_stopped_server_deleted", server_id=server_id)
            return

        started = time.perf_counter()
        payload = {
            "reported_at": datetime.now(timezone.utc).isoformat(),
            "ok": False,
            "queue_depth": None,
            "gpu_utilization": None,
            "vram_free_mb": None,
            "error": None,
            "raw_payload": {},
        }

        client = ComfyHTTPClient(server_url)
        try:
            queue = await client.get_queue()
            stats = await client.get_system_stats()
            latency_ms = (time.perf_counter() - started) * 1000.0
            queue_running = queue.get("queue_running", [])
            queue_pending = queue.get("queue_pending", [])
            queue_depth = len(queue_running) + len(queue_pending)
            payload.update(
                {
                    "ok": True,
                    "latency_ms": latency_ms,
                    "queue_depth": queue_depth,
                    "vram_free_mb": _extract_vram_free_mb(stats),
                    "raw_payload": {
                        "queue": queue,
                        "system_stats": stats,
                    },
                }
            )
        except Exception as e:
            payload["latency_ms"] = (time.perf_counter() - started) * 1000.0
            payload["error"] = str(e)
        finally:
            await client.close()

        health = await service.ingest_ping(server_id, payload)
        ping_ok = bool(payload.get("ok", False))
        if last_ping_ok is not None and ping_ok != last_ping_ok:
            await event_hub.broadcast(
                {
                    "type": "server_ping_status_changed",
                    "server_id": server_id,
                    "server_name": server_name,
                    "ok": ping_ok,
                    "health_state": health.get("health_state", "stale"),
                    "reason": health.get("reason", ""),
                    "last_seen_at": health.get("last_seen_at"),
                }
            )
        last_ping_ok = ping_ok
        await asyncio.sleep(settings.health_ping_interval_seconds)


async def _ensure_server_health_ping_loop(
    service: RegistryService,
    event_hub: RegistryEventHub,
    server_id: str,
    server_name: str,
    server_url: str,
) -> bool:
    existing = _health_ping_tasks.get(server_id)
    if existing and not existing.done():
        return False

    task = asyncio.create_task(
        _run_server_health_ping_loop(
            service=service,
            event_hub=event_hub,
            server_id=server_id,
            server_name=server_name,
            server_url=server_url,
        )
    )
    _health_ping_tasks[server_id] = task
    return True


async def stop_server_health_ping_loops() -> None:
    tasks = list(_health_ping_tasks.values())
    _health_ping_tasks.clear()
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def close_control_plane_temporal_client() -> None:
    global _temporal_client
    if _temporal_client is not None:
        await _temporal_client.close()
        _temporal_client = None


async def bootstrap_server_health_ping_loops(
    service: RegistryService,
    event_hub: RegistryEventHub,
) -> int:
    started = 0
    servers = await service.store.list_servers()
    for server in servers:
        if server.status != "registered":
            continue
        server_url = build_server_url(
            {"address": server.address, "port": server.port, "ssl": server.ssl}
        )
        created = await _ensure_server_health_ping_loop(
            service=service,
            event_hub=event_hub,
            server_id=server.id,
            server_name=server.name,
            server_url=server_url,
        )
        if created:
            started += 1
    logger.info("server_health_ping_loops_bootstrapped", started=started)
    return started


async def consume_server_registered(
    bus: JetStreamEventBus,
    service: RegistryService,
) -> None:
    """Consume ServerRegistered events and sync template workflows."""

    async def _handle(msg):
        try:
            envelope = EventEnvelope.model_validate_json(msg.data.decode("utf-8"))
            if envelope.event_type != EventTypes.SERVER_REGISTERED:
                await msg.ack()
                return

            payload = envelope.payload
            server_url = build_server_url(payload)
            force = bool(payload.get("force", False))
            logger.info(
                "template_sync_started",
                server=payload.get("name"),
                server_url=server_url,
                force=force,
            )

            client = ComfyHTTPClient(server_url)
            try:
                template_payload = await client.list_bridge_templates()
                templates = [
                    item.get("filename")
                    for item in template_payload.get("files", [])
                    if isinstance(item, dict) and isinstance(item.get("filename"), str)
                ]
                synced = 0
                skipped = 0
                invalid = 0
                failed = 0
                for template_name in templates:
                    if not template_name.endswith(".json"):
                        continue
                    try:
                        content_bytes = await client.download_bridge_template(template_name)
                        workflow = json.loads(content_bytes.decode("utf-8"))
                        template_id = template_name.replace(".json", "")
                        result = await service.upsert_template_workflow(
                            template_id,
                            workflow,
                            force=force,
                        )
                        if result.get("skipped"):
                            skipped += 1
                        elif result.get("status") == "invalid_policy":
                            invalid += 1
                        else:
                            synced += 1
                    except Exception as template_error:
                        failed += 1
                        logger.error(
                            "template_sync_item_failed",
                            template_name=template_name,
                            error=str(template_error),
                        )
                        continue

                logger.info(
                    "template_sync_completed",
                    server=payload.get("name"),
                    synced=synced,
                    skipped=skipped,
                    invalid=invalid,
                    failed=failed,
                )
            finally:
                await client.close()

            await msg.ack()
        except Exception as e:
            logger.error("template_sync_failed", error=str(e))
            # Do not ack on error so message can be retried.

    await bus.subscribe(
        "registry.server.ServerRegistered",
        _handle,
        durable="registry-template-sync",
    )
    logger.info("consumer_started", subject="registry.server.ServerRegistered")


async def consume_server_registered_health_ping(
    bus: JetStreamEventBus,
    service: RegistryService,
    event_hub: RegistryEventHub,
) -> None:
    """Consume ServerRegistered and ensure periodic health pings are running."""

    async def _handle(msg):
        try:
            envelope = EventEnvelope.model_validate_json(msg.data.decode("utf-8"))
            if envelope.event_type != EventTypes.SERVER_REGISTERED:
                await msg.ack()
                return

            payload = envelope.payload
            server_id = payload.get("id")
            server_name = payload.get("name", "unknown")
            if not server_id:
                await msg.ack()
                return

            server_url = build_server_url(payload)
            await _ensure_server_health_ping_loop(
                service=service,
                event_hub=event_hub,
                server_id=server_id,
                server_name=server_name,
                server_url=server_url,
            )
            await msg.ack()
        except Exception as e:
            logger.error("server_health_ping_consumer_failed", error=str(e))
            # Do not ack on error so message can be retried.

    await bus.subscribe(
        "registry.server.ServerRegistered",
        _handle,
        durable="registry-server-health-ping",
    )
    logger.info("consumer_started", subject="registry.server.ServerRegistered")


async def consume_server_registered_object_info(
    bus: JetStreamEventBus,
    service: RegistryService,
) -> None:
    """Consume ServerRegistered and refresh object_info projection."""

    async def _handle(msg):
        try:
            envelope = EventEnvelope.model_validate_json(msg.data.decode("utf-8"))
            if envelope.event_type != EventTypes.SERVER_REGISTERED:
                await msg.ack()
                return

            payload = envelope.payload
            server_id = payload.get("id")
            if not server_id:
                await msg.ack()
                return

            await service.refresh_server_object_info(server_id)
            await msg.ack()
        except Exception as e:
            logger.error("server_object_info_projection_failed", error=str(e))
            # Do not ack on error so message can be retried.

    await bus.subscribe(
        "registry.server.ServerRegistered",
        _handle,
        durable="registry-server-object-info-projection",
    )
    logger.info("consumer_started", subject="registry.server.ServerRegistered")


async def consume_server_registered_apply_data_plane_mode(
    bus: JetStreamEventBus,
    service: RegistryService,
) -> None:
    """Consume ServerRegistered and trigger control-plane sync for that server."""

    async def _handle(msg):
        try:
            envelope = EventEnvelope.model_validate_json(msg.data.decode("utf-8"))
            if envelope.event_type != EventTypes.SERVER_REGISTERED:
                await msg.ack()
                return

            payload = envelope.payload
            server_id = payload.get("id")
            if not server_id:
                await msg.ack()
                return

            state = await service.read_control_plane_settings(
                publish_event=True,
                force=True,
                target_server_ids=[server_id],
            )

            logger.info(
                "server_registered_control_plane_sync_requested",
                server_id=server_id,
                server_name=payload.get("name"),
                settings_hash=state.get("settings_hash"),
            )
            await msg.ack()
        except Exception as e:
            logger.error("server_registered_control_plane_sync_request_failed", error=str(e))
            # Do not ack on error so message can be retried.

    await bus.subscribe(
        "registry.server.ServerRegistered",
        _handle,
        durable="registry-server-control-plane-sync-request",
    )
    logger.info("consumer_started", subject="registry.server.ServerRegistered")


async def consume_data_plane_mode_updated(
    bus: JetStreamEventBus,
    service: RegistryService,
) -> None:
    """Consume DataPlaneModeUpdated and push bridge mode config to all registered servers."""

    async def _handle(msg):
        try:
            envelope = EventEnvelope.model_validate_json(msg.data.decode("utf-8"))
            if envelope.event_type != EventTypes.DATA_PLANE_MODE_UPDATED:
                await msg.ack()
                return

            mode = str(envelope.payload.get("mode", "")).strip().lower()
            if mode not in {"local", "orchestrator", "s3", "cloudinary"}:
                logger.warning("data_plane_mode_invalid_event_payload", payload=envelope.payload)
                await msg.ack()
                return

            servers = await service.store.list_servers()
            failures: list[dict[str, str]] = []
            applied = 0

            for server in servers:
                if server.status != "registered":
                    continue
                server_url = build_server_url(
                    {"address": server.address, "port": server.port, "ssl": server.ssl}
                )
                client = ComfyHTTPClient(server_url)
                try:
                    await client.set_bridge_mode(mode)
                    applied += 1
                except Exception as error:
                    failures.append(
                        {
                            "server_id": server.id,
                            "server_name": server.name,
                            "error": str(error),
                        }
                    )
                    logger.error(
                        "data_plane_mode_apply_failed",
                        server_id=server.id,
                        server_name=server.name,
                        mode=mode,
                        error=str(error),
                    )
                finally:
                    await client.close()

            if failures:
                raise RuntimeError(
                    f"Failed to apply mode to {len(failures)} server(s): "
                    + ", ".join(f["server_name"] for f in failures)
                )

            logger.info(
                "data_plane_mode_applied_to_servers",
                mode=mode,
                server_count=applied,
            )
            await msg.ack()
        except Exception as e:
            logger.error("data_plane_mode_consumer_failed", error=str(e))
            # Do not ack on error so message can be retried.

    await bus.subscribe(
        "registry.server.DataPlaneModeUpdated",
        _handle,
        durable="registry-dataplane-mode-fanout",
    )
    logger.info("consumer_started", subject="registry.server.DataPlaneModeUpdated")


async def consume_control_plane_settings_updated(
    bus: JetStreamEventBus,
    service: RegistryService,
) -> None:
    """Consume ControlPlaneSettingsUpdated and run durable Temporal fanout."""

    async def _handle(msg):
        try:
            envelope = EventEnvelope.model_validate_json(msg.data.decode("utf-8"))
            if envelope.event_type != EventTypes.CONTROL_PLANE_SETTINGS_UPDATED:
                await msg.ack()
                return

            payload = envelope.payload
            settings = payload.get("settings")
            settings_hash = str(payload.get("settings_hash", "")).strip()
            force = bool(payload.get("force", False))
            target_server_ids_raw = payload.get("target_server_ids") or []
            target_server_ids = [
                str(server_id).strip()
                for server_id in target_server_ids_raw
                if str(server_id).strip()
            ]
            if not isinstance(settings, dict) or not settings_hash:
                state = await service.read_control_plane_settings(
                    publish_event=False,
                    force=False,
                )
                settings = state["settings"]
                settings_hash = state["settings_hash"]

            if not target_server_ids:
                servers = await service.store.list_servers()
                target_server_ids = [server.id for server in servers if server.status == "registered"]

            temporal_client = await _get_temporal_client()
            workflow_id = f"control-plane-fanout-{envelope.event_id}"
            workflow_input = {
                "settings": settings,
                "settings_hash": settings_hash,
                "target_server_ids": target_server_ids,
                "force": force,
            }
            try:
                await temporal_client.start_workflow(
                    "ControlPlaneFanoutWorkflow",
                    workflow_input,
                    id=workflow_id,
                    task_queue="comfyui-gpu-farm",
                )
            except WorkflowAlreadyStartedError:
                logger.info(
                    "control_plane_fanout_workflow_already_started",
                    workflow_id=workflow_id,
                )

            logger.info(
                "control_plane_fanout_workflow_started",
                workflow_id=workflow_id,
                settings_hash=settings_hash,
                target_count=len(target_server_ids),
                force=force,
            )
            await msg.ack()
        except Exception as e:
            logger.error("control_plane_settings_updated_consumer_failed", error=str(e))
            # Do not ack on error so message can be retried.

    await bus.subscribe(
        "registry.control_plane.ControlPlaneSettingsUpdated",
        _handle,
        durable="registry-control-plane-settings-fanout",
    )
    logger.info("consumer_started", subject="registry.control_plane.ControlPlaneSettingsUpdated")


async def consume_template_workflow_upserted(
    bus: JetStreamEventBus,
    service: RegistryService,
) -> None:
    """Consume TemplateWorkflowUpserted events and generate default overrides."""

    async def _handle(msg):
        try:
            envelope = EventEnvelope.model_validate_json(msg.data.decode("utf-8"))
            if envelope.event_type != EventTypes.TEMPLATE_WORKFLOW_UPSERTED:
                await msg.ack()
                return

            template_name = envelope.payload.get("template_name")
            if not template_name:
                logger.warning("template_override_generation_skipped_missing_template_name")
                await msg.ack()
                return

            result = await service.generate_template_overrides(template_name)
            logger.info(
                "template_overrides_generated",
                template_name=template_name,
                parameter_count=len(result.get("overrides", {}).get("parameters", [])),
            )
            await msg.ack()
        except Exception as e:
            logger.error("template_override_generation_failed", error=str(e))
            # Do not ack on error so message can be retried.

    await bus.subscribe(
        "registry.template.TemplateWorkflowUpserted",
        _handle,
        durable="registry-template-overrides",
    )
    logger.info("consumer_started", subject="registry.template.TemplateWorkflowUpserted")


async def consume_template_overrides_upserted(
    bus: JetStreamEventBus,
    service: RegistryService,
) -> None:
    """Consume TemplateOverridesUpserted and refresh validated_servers."""

    async def _handle(msg):
        try:
            envelope = EventEnvelope.model_validate_json(msg.data.decode("utf-8"))
            if envelope.event_type != EventTypes.TEMPLATE_OVERRIDES_UPSERTED:
                await msg.ack()
                return

            template_name = envelope.payload.get("template_name")
            if not template_name:
                logger.warning("template_validation_skipped_missing_template_name")
                await msg.ack()
                return

            result = await service.refresh_validated_servers(template_name)
            logger.info(
                "template_validated_servers_updated",
                template_name=template_name,
                validated_count=result.get("validated_count", 0),
            )
            await msg.ack()
        except Exception as e:
            logger.error("template_validation_refresh_failed", error=str(e))
            # Do not ack on error so message can be retried.

    await bus.subscribe(
        "registry.template_override_set.TemplateOverridesUpserted",
        _handle,
        durable="registry-template-validation",
    )
    logger.info(
        "consumer_started",
        subject="registry.template_override_set.TemplateOverridesUpserted",
    )


async def consume_template_overrides_upserted_node_definitions(
    bus: JetStreamEventBus,
    node_definitions: NodeDefinitionsService,
    event_hub: RegistryEventHub | None = None,
) -> None:
    """Consume TemplateOverridesUpserted and upsert in-memory node definitions."""

    async def _handle(msg):
        try:
            envelope = EventEnvelope.model_validate_json(msg.data.decode("utf-8"))
            if envelope.event_type != EventTypes.TEMPLATE_OVERRIDES_UPSERTED:
                await msg.ack()
                return

            template_name = envelope.payload.get("template_name")
            if not template_name:
                logger.warning("node_definition_projection_skipped_missing_template_name")
                await msg.ack()
                return

            projected = node_definitions.refresh_projection(template_name)
            if projected:
                logger.info(
                    "node_definition_projection_upserted",
                    template_name=template_name,
                )
                if event_hub is not None:
                    await event_hub.broadcast(
                        {
                            "type": "template_changed",
                            "template_name": template_name,
                        }
                    )
            else:
                logger.warning(
                    "node_definition_projection_skipped_missing_template_or_overrides",
                    template_name=template_name,
                )
            await msg.ack()
        except Exception as e:
            logger.error("node_definition_projection_failed", error=str(e))
            # Do not ack on error so message can be retried.

    await bus.subscribe(
        "registry.template_override_set.TemplateOverridesUpserted",
        _handle,
        durable="registry-node-definition-projection",
    )
    logger.info(
        "consumer_started",
        subject="registry.template_override_set.TemplateOverridesUpserted",
    )
