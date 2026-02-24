"""Activity: push signed control-plane settings to one worker."""

from __future__ import annotations

from typing import Any

import httpx
from temporalio import activity

from core.clients.comfy.http import ComfyHTTPClient
from core.registry_service.comfy_checks import build_server_url
from core.registry_service.control_plane import build_bridge_hmac_headers, canonical_json
from core.registry_service.projection import ProjectionStore


@activity.defn
async def push_control_plane_config_to_worker_activity(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Push config to a single worker and persist push-job updates.

    Payload keys:
    - server_id: str
    - settings: dict
    - settings_hash: str
    - force: bool
    """
    server_id = str(payload.get("server_id", "")).strip()
    settings = payload.get("settings")
    settings_hash = str(payload.get("settings_hash", "")).strip()
    force = bool(payload.get("force", False))
    if not server_id:
        raise ValueError("server_id is required")
    if not isinstance(settings, dict):
        raise ValueError("settings must be an object")
    if not settings_hash:
        raise ValueError("settings_hash is required")

    store = ProjectionStore()
    await store.connect()
    try:
        server = await store.get_server(server_id)
        if not server or server.status != "registered":
            return {
                "server_id": server_id,
                "status": "skipped",
                "reason": "server not found or not registered",
                "job": None,
            }

        latest_jobs = await store.list_worker_config_push_jobs(limit=1, server_id=server.id)
        if (
            latest_jobs
            and not force
            and latest_jobs[0].target_hash == settings_hash
            and latest_jobs[0].status == "applied"
        ):
            return {
                "server_id": server.id,
                "server_name": server.name,
                "status": "skipped",
                "reason": "already applied for hash",
                "job": latest_jobs[0].__dict__,
            }

        attempt = activity.info().attempt
        if (
            attempt > 1
            and latest_jobs
            and latest_jobs[0].target_hash == settings_hash
            and latest_jobs[0].status == "failed"
        ):
            job = latest_jobs[0]
        else:
            job = await store.create_worker_config_push_job(
                server_id=server.id,
                server_name=server.name,
                target_hash=settings_hash,
            )

        secret = await store.get_worker_control_secret(server.id)
        if not secret:
            updated = await store.update_worker_config_push_job(
                job.id,
                status="failed",
                attempts=attempt,
                last_error="worker control secret not registered",
            )
            return {
                "server_id": server.id,
                "server_name": server.name,
                "status": "failed",
                "retryable": False,
                "job": (updated or job).__dict__,
            }

        body = canonical_json(settings)
        headers = build_bridge_hmac_headers(
            secret.shared_secret,
            method="POST",
            path="/graviton-bridge/config",
            body=body,
        )
        headers["Content-Type"] = "application/json"

        client = ComfyHTTPClient(
            build_server_url(
                {"address": server.address, "port": server.port, "ssl": server.ssl}
            )
        )
        try:
            await client.set_bridge_config(settings, headers=headers, raw_body=body)
            updated = await store.update_worker_config_push_job(
                job.id,
                status="applied",
                attempts=attempt,
                last_error="",
                next_retry_at="",
            )
            await store.set_control_plane_last_applied()
            return {
                "server_id": server.id,
                "server_name": server.name,
                "status": "applied",
                "retryable": False,
                "job": (updated or job).__dict__,
            }
        except Exception as error:
            is_retryable = isinstance(
                error,
                (
                    httpx.ConnectError,
                    httpx.ConnectTimeout,
                    httpx.ReadTimeout,
                    httpx.WriteTimeout,
                    httpx.NetworkError,
                ),
            )
            updated = await store.update_worker_config_push_job(
                job.id,
                status="failed",
                attempts=attempt,
                last_error=str(error),
            )
            if is_retryable:
                raise
            return {
                "server_id": server.id,
                "server_name": server.name,
                "status": "failed",
                "retryable": False,
                "job": (updated or job).__dict__,
            }
        finally:
            await client.close()
    finally:
        await store.close()
