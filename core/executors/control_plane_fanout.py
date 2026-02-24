"""Temporal workflow: fan out control-plane settings via per-worker activities."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from core.activities import push_control_plane_config_to_worker_activity


@workflow.defn
class ControlPlaneFanoutWorkflow:
    @workflow.run
    async def run(self, request: dict[str, Any]) -> dict[str, Any]:
        settings = request.get("settings") or {}
        settings_hash = str(request.get("settings_hash", ""))
        force = bool(request.get("force", False))
        targets = [str(sid) for sid in (request.get("target_server_ids") or []) if sid]
        if not targets:
            return {
                "settings_hash": settings_hash,
                "target_count": 0,
                "applied": 0,
                "failed": 0,
                "skipped": 0,
                "results": [],
            }

        async def _push_to_server(server_id: str):
            return await workflow.execute_activity(
                push_control_plane_config_to_worker_activity,
                args=[
                    {
                        "server_id": server_id,
                        "settings": settings,
                        "settings_hash": settings_hash,
                        "force": force,
                    }
                ],
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=5),
                    backoff_coefficient=2.0,
                    maximum_interval=timedelta(minutes=2),
                    maximum_attempts=8,
                ),
            )

        task_results = await asyncio.gather(
            *[_push_to_server(server_id) for server_id in targets],
            return_exceptions=True,
        )
        results: list[dict[str, Any]] = []
        applied = 0
        failed = 0
        skipped = 0

        for index, item in enumerate(task_results):
            server_id = targets[index]
            if isinstance(item, Exception):
                failed += 1
                results.append(
                    {
                        "server_id": server_id,
                        "status": "failed",
                        "error": str(item),
                    }
                )
                continue

            results.append(item)
            status = str(item.get("status", "")).lower()
            if status == "applied":
                applied += 1
            elif status == "skipped":
                skipped += 1
            else:
                failed += 1

        return {
            "settings_hash": settings_hash,
            "target_count": len(targets),
            "applied": applied,
            "failed": failed,
            "skipped": skipped,
            "results": results,
        }
