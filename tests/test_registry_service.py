"""Tests for the new registry service using a mock ComfyUI server."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from core.registry_service import main as registry_main
from core.registry_service.health import HealthEvaluator
from core.registry_service.projection import ProjectionStore
from core.registry_service.service import RegistryService
from core.registry_service.template_manager import TemplateManager
from core.registry_service.template_store import TemplateStore
from tests.mock_comfyui_server import create_mock_comfyui_app


class DummyBus:
    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def publish(self, envelope) -> None:
        return None


class RegistryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()

        # Replace JetStream dependency with no-op bus for local tests.
        dummy_bus = DummyBus()
        registry_main._bus = dummy_bus
        registry_main._store = ProjectionStore()
        registry_main._health_evaluator = HealthEvaluator(registry_main._store)

        # Route template storage to an isolated temporary directory.
        registry_main.settings.template_root_dir = self.tempdir.name
        registry_main._template_store = TemplateStore()
        registry_main._template_manager = TemplateManager(registry_main._template_store)
        registry_main._service = RegistryService(
            registry_main._bus,
            registry_main._store,
            registry_main._health_evaluator,
            registry_main._template_store,
            registry_main._template_manager,
        )

        self.checks_patcher = patch(
            "core.registry_service.service.run_basic_server_checks",
            return_value={
                "ok": True,
                "server_url": "http://mock.local:8188",
                "gpu_count": 1,
                "node_count": 100,
            },
        )
        self.checks_patcher.start()

        self.client = TestClient(registry_main.app)
        self.mock_comfy = TestClient(create_mock_comfyui_app())

    def tearDown(self) -> None:
        self.checks_patcher.stop()
        self.client.close()
        self.mock_comfy.close()
        self.tempdir.cleanup()

    def _build_ping_from_mock_comfy(self) -> dict:
        stats = self.mock_comfy.get("/system_stats").json()
        queue = self.mock_comfy.get("/queue").json()

        queue_depth = len(queue.get("queue_running", [])) + len(queue.get("queue_pending", []))
        devices = stats.get("devices", [])
        vram_free_mb = None
        if devices:
            total = devices[0].get("vram_total", 0) or 0
            used = devices[0].get("vram_used", 0) or 0
            vram_free_mb = total - used

        return {
            "ok": True,
            "latency_ms": 120.0,
            "queue_depth": queue_depth,
            "gpu_utilization": 45.0,
            "vram_free_mb": vram_free_mb,
            "raw_payload": {
                "system_stats": stats,
                "queue": queue,
            },
        }

    def test_register_server_and_ping_via_mock_comfy(self) -> None:
        # Register server
        resp = self.client.post(
            "/v1/servers",
            json={
                "name": "mock-1",
                "provider": "comfyui",
                "address": "mock.local",
                "port": 8188,
                "ssl": False,
                "tags": {"zone": "test"},
                "weight": 1,
            },
        )
        self.assertEqual(resp.status_code, 200)
        server = resp.json()

        # Build ping from mock ComfyUI API responses
        ping_payload = self._build_ping_from_mock_comfy()
        ping_resp = self.client.post(f"/v1/servers/{server['id']}/pings", json=ping_payload)
        self.assertEqual(ping_resp.status_code, 200)

        health = ping_resp.json()
        self.assertIn(health["health_state"], ["healthy", "degraded"])

    def test_unhealthy_after_consecutive_failures(self) -> None:
        resp = self.client.post(
            "/v1/servers",
            json={
                "name": "mock-2",
                "provider": "comfyui",
                "address": "mock.local",
                "port": 8188,
                "ssl": False,
            },
        )
        self.assertEqual(resp.status_code, 200)
        server_id = resp.json()["id"]

        for _ in range(3):
            fail_resp = self.client.post(
                f"/v1/servers/{server_id}/pings",
                json={
                    "ok": False,
                    "error": "timeout",
                    "latency_ms": 9999,
                    "queue_depth": 0,
                    "raw_payload": {},
                },
            )
            self.assertEqual(fail_resp.status_code, 200)

        health_resp = self.client.get(f"/v1/servers/{server_id}/health")
        self.assertEqual(health_resp.status_code, 200)
        self.assertEqual(health_resp.json()["health_state"], "unhealthy")

    def test_eligible_servers_excludes_stale(self) -> None:
        resp = self.client.post(
            "/v1/servers",
            json={
                "name": "mock-3",
                "provider": "comfyui",
                "address": "mock.local",
                "port": 8188,
                "ssl": False,
            },
        )
        self.assertEqual(resp.status_code, 200)
        server_id = resp.json()["id"]

        self.client.post(
            f"/v1/servers/{server_id}/pings",
            json={"ok": True, "latency_ms": 100, "queue_depth": 0, "raw_payload": {}},
        )

        # Force staleness by setting old timestamp in projection.
        old = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
        registry_main._store.health_by_server_id[server_id].last_seen_at = old

        eligible = self.client.get("/v1/health/eligible")
        self.assertEqual(eligible.status_code, 200)
        self.assertEqual(eligible.json()["count"], 0)

    def test_template_workflow_and_overrides_updates(self) -> None:
        wf_resp = self.client.put(
            "/v1/templates/video_mock/workflow",
            json={
                "workflow": {
                    "1": {
                        "class_type": "SaveImage",
                        "inputs": {"filename_prefix": "demo"},
                    }
                }
            },
        )
        self.assertEqual(wf_resp.status_code, 200)

        ov_resp = self.client.put(
            "/v1/templates/video_mock/overrides",
            json={
                "overrides": {
                    "workflow_hash": "sha256:test",
                    "parameters": [{"key": "1.filename_prefix", "default_value": "demo"}],
                }
            },
        )
        self.assertEqual(ov_resp.status_code, 200)

        list_resp = self.client.get("/v1/templates")
        self.assertEqual(list_resp.status_code, 200)
        self.assertIn("video_mock", list_resp.json()["templates"])

        get_wf = self.client.get("/v1/templates/video_mock/workflow")
        self.assertEqual(get_wf.status_code, 200)
        self.assertIn("workflow", get_wf.json())

        get_ov = self.client.get("/v1/templates/video_mock/overrides")
        self.assertEqual(get_ov.status_code, 200)
        self.assertIn("overrides", get_ov.json())

    def test_template_generate_apply_and_delete(self) -> None:
        self.client.put(
            "/v1/templates/editable/workflow",
            json={
                "workflow": {
                    "1": {
                        "class_type": "KSampler",
                        "inputs": {"steps": 20, "cfg": 7.0},
                    }
                }
            },
        )

        gen = self.client.post("/v1/templates/editable:generate-overrides")
        self.assertEqual(gen.status_code, 200)
        self.assertGreater(len(gen.json()["overrides"]["parameters"]), 0)

        applied = self.client.post(
            "/v1/templates/editable:apply-overrides",
            json={"runtime_overrides": {"1.steps": 33}},
        )
        self.assertEqual(applied.status_code, 200)
        self.assertEqual(applied.json()["workflow"]["1"]["inputs"]["steps"], 33)

        deleted = self.client.delete("/v1/templates/editable")
        self.assertEqual(deleted.status_code, 200)
        self.assertTrue(deleted.json()["workflow_deleted"])

    def test_upsert_server_returns_400_when_preflight_fails(self) -> None:
        with patch(
            "core.registry_service.service.run_basic_server_checks",
            return_value={"ok": False, "error": "connection refused"},
        ):
            resp = self.client.post(
                "/v1/servers",
                json={
                    "name": "bad-server",
                    "provider": "comfyui",
                    "address": "127.0.0.1",
                    "port": 8188,
                    "ssl": False,
                },
            )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("preflight checks failed", resp.json()["detail"].lower())


if __name__ == "__main__":
    unittest.main()
