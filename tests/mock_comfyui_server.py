"""Mock ComfyUI server for registry service tests."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


def create_mock_comfyui_app() -> FastAPI:
    app = FastAPI(title="Mock ComfyUI")

    state = {
        "devices": [
            {
                "name": "Mock GPU",
                "vram_total": 16384,
                "vram_used": 4096,
            }
        ],
        "queue_running": ["job-a"],
        "queue_pending": ["job-b"],
        "object_info": {
            "CheckpointLoaderSimple": {
                "input": {
                    "required": {
                        "ckpt_name": [["model-a.safetensors", "model-b.safetensors"]]
                    }
                }
            }
        },
        "templates": ["mock_template.json"],
        "view_content": b'{"1": {"class_type": "SaveImage", "inputs": {"filename_prefix": "x"}}}',
    }

    class StateUpdate(BaseModel):
        vram_used: int | None = None
        queue_running: list[str] | None = None
        queue_pending: list[str] | None = None

    @app.get("/system_stats")
    async def system_stats() -> dict:
        return {"devices": state["devices"]}

    @app.get("/queue")
    async def queue() -> dict:
        return {
            "queue_running": state["queue_running"],
            "queue_pending": state["queue_pending"],
        }

    @app.get("/object_info")
    async def object_info() -> dict:
        return state["object_info"]

    @app.get("/models/templates")
    async def models_templates() -> list[str]:
        return state["templates"]

    @app.get("/graviton-bridge/templates")
    async def bridge_templates() -> dict:
        return {
            "path": "/mock/graviton_bridge/templates",
            "count": len(state["templates"]),
            "files": [
                {"filename": name, "size_bytes": len(state["view_content"]), "modified_at": 0}
                for name in state["templates"]
            ],
        }

    @app.get("/graviton-bridge/templates/download/{filename}")
    async def bridge_download_template(filename: str) -> bytes:
        if filename not in state["templates"]:
            raise HTTPException(status_code=404, detail="template not found")
        return state["view_content"]

    @app.get("/view")
    async def view() -> bytes:
        return state["view_content"]

    @app.post("/__state")
    async def update_state(update: StateUpdate) -> dict:
        if update.vram_used is not None:
            state["devices"][0]["vram_used"] = update.vram_used
        if update.queue_running is not None:
            state["queue_running"] = update.queue_running
        if update.queue_pending is not None:
            state["queue_pending"] = update.queue_pending
        return {"ok": True}

    return app
