"""ComfyUI preflight checks used during server upsert."""

from __future__ import annotations

from typing import Any, Dict

from core.clients.comfy.http import ComfyHTTPClient


def build_server_url(payload: Dict[str, Any]) -> str:
    address = payload.get("address", "")
    port = payload.get("port")
    ssl = bool(payload.get("ssl", False))

    if address.startswith(("http://", "https://")):
        base = address.rstrip("/")
    else:
        scheme = "https" if ssl else "http"
        base = f"{scheme}://{address}"

    host_part = base.split("//", 1)[1]
    if port and ":" not in host_part:
        base = f"{base}:{port}"

    return base


async def run_basic_server_checks(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Run minimal checks to verify a ComfyUI server is responsive.

    Checks:
    - /system_stats
    - /object_info
    """
    server_url = build_server_url(payload)
    client = ComfyHTTPClient(server_url)

    try:
        system_stats = await client.get_system_stats()
        object_info = await client.get_object_info()

        if not isinstance(system_stats, dict):
            return {"ok": False, "error": "Invalid /system_stats response"}
        if not isinstance(object_info, dict):
            return {"ok": False, "error": "Invalid /object_info response"}

        return {
            "ok": True,
            "server_url": server_url,
            "gpu_count": len(system_stats.get("devices", [])),
            "node_count": len(object_info.keys()),
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "server_url": server_url}
    finally:
        await client.close()
