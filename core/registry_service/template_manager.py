"""Template lifecycle and override application logic for registry service."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .policy import check_template_policy
from .projection import ProjectionStore
from .template_store import TemplateStore

GRAVITON_LOAD_NODE_INPUT_TYPES = {
    "GravitonLoadImage": "image",
    "GravitonLoadVideo": "video",
    "GravitonLoadText": "text",
    "GravitonLoadFile": "file",
    "GravitonLoadAudio": "audio",
    "GravitonLoad3D": "3d",
}


class TemplateManager:
    def __init__(
        self,
        store: TemplateStore,
        projection_store: Optional[ProjectionStore] = None,
    ):
        self.store = store
        self.projection_store = projection_store

    @staticmethod
    def hash_workflow(workflow: Dict[str, Any]) -> str:
        canonical = json.dumps(workflow, sort_keys=True, ensure_ascii=False)
        return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"

    @staticmethod
    def _extract_parameters(workflow: Dict[str, Any]) -> List[Dict[str, Any]]:
        params: List[Dict[str, Any]] = []
        for node_id, node in workflow.items():
            if not isinstance(node, dict):
                continue
            inputs = node.get("inputs", {})
            node_class = str(node.get("class_type", "Unknown"))
            node_title = node.get("_meta", {}).get("title", node_class)
            io_type = GRAVITON_LOAD_NODE_INPUT_TYPES.get(node_class)

            for input_key, value in inputs.items():
                if isinstance(value, list):
                    continue
                category = "other"
                param_io_type: str | None = None
                if io_type and input_key == "asset_ref":
                    category = "bridge_input"
                    param_io_type = io_type
                params.append(
                    {
                        "key": f"{node_id}.{input_key}",
                        "node_id": str(node_id),
                        "input_key": input_key,
                        "default_value": value,
                        "type": type(value).__name__,
                        "node_class": node_class,
                        "node_title": node_title,
                        "description": "",
                        "category": category,
                        "io_type": param_io_type,
                    }
                )
        return params

    @staticmethod
    def _default_output_socket(output_type: str) -> Dict[str, Any]:
        label = "Output"
        if output_type == "image":
            label = "Image"
        elif output_type == "video":
            label = "Video"
        elif output_type == "text":
            label = "Text"
        elif output_type == "audio":
            label = "Audio"
        elif output_type == "3d":
            label = "3D"
        elif output_type == "file":
            label = "File"
        return {"id": "output", "type": output_type, "label": label}

    def _build_ui_metadata(
        self,
        template_name: str,
        workflow: Dict[str, Any],
        existing_overrides: Dict[str, Any],
    ) -> Dict[str, Any]:
        raw = existing_overrides.get("ui_metadata")
        if not isinstance(raw, dict):
            legacy = existing_overrides.get("_ui_metadata")
            raw = legacy if isinstance(legacy, dict) else {}

        output_sockets = raw.get("outputSockets")
        if not isinstance(output_sockets, list) or len(output_sockets) == 0:
            policy_result = check_template_policy(template_name, workflow)
            output_types = policy_result.get("output_types", [])
            if policy_result.get("valid") and len(output_types) == 1:
                output_sockets = [self._default_output_socket(str(output_types[0]))]
            else:
                output_sockets = []

        category = raw.get("category")
        if category not in {"image", "video", "utility"}:
            if len(output_sockets) == 1 and output_sockets[0].get("type") in {"image", "video"}:
                category = str(output_sockets[0]["type"])
            else:
                category = "utility"

        return {
            "nodeType": raw.get("nodeType", "utility_workflow"),
            "label": raw.get("label", template_name),
            "icon": raw.get("icon", "workflow"),
            "color": raw.get("color", "#666666"),
            "category": category,
            "outputSockets": output_sockets,
        }

    def generate_default_overrides(self, template_name: str) -> Dict[str, Any]:
        workflow = self.store.get_workflow(template_name)
        if workflow is None:
            raise ValueError(f"Template workflow not found: {template_name}")

        existing = self.store.get_overrides(template_name) or {}
        overrides = {
            "workflow_hash": self.hash_workflow(workflow),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "workflow_name": template_name,
            "description": (
                "Auto-generated parameter overrides. "
                "Remove parameters to make them immutable."
            ),
            "parameters": self._extract_parameters(workflow),
            "validated_servers": existing.get("validated_servers", []),
            "ui_metadata": self._build_ui_metadata(template_name, workflow, existing),
        }
        self.store.upsert_overrides(template_name, overrides)
        return overrides

    def get_or_generate_overrides(self, template_name: str) -> Dict[str, Any]:
        overrides = self.store.get_overrides(template_name)
        if overrides is not None:
            return overrides
        return self.generate_default_overrides(template_name)

    async def upsert_workflow(
        self,
        template_name: str,
        workflow: Dict[str, Any],
        force: bool = False,
    ) -> Dict[str, Any]:
        if self.projection_store is None:
            raise ValueError("Projection store is required for workflow upsert")
        content_hash = self.hash_workflow(workflow)
        existing_template = await self.projection_store.get_template_by_hash(content_hash)
        if existing_template and not force:
            return {
                "template_name": template_name,
                "workflow_hash": content_hash,
                "skipped": True,
                "existing_template": existing_template,
            }

        self.store.upsert_workflow(template_name, workflow)
        await self.projection_store.save_template_hash(content_hash, template_name)
        return {
            "template_name": template_name,
            "workflow_hash": content_hash,
            "workflow": workflow,
            "skipped": False,
            "forced": force,
        }

    def apply_runtime_overrides(
        self, template_name: str, runtime_overrides: Dict[str, Any]
    ) -> Dict[str, Any]:
        workflow = self.store.get_workflow(template_name)
        if workflow is None:
            raise ValueError(f"Template workflow not found: {template_name}")

        overrides = self.get_or_generate_overrides(template_name)
        allowed = {p.get("key"): p for p in overrides.get("parameters", []) if p.get("key")}

        result = copy.deepcopy(workflow)
        for key, value in runtime_overrides.items():
            if key not in allowed:
                raise ValueError(
                    f"Parameter '{key}' is not overridable in template '{template_name}'"
                )
            param = allowed[key]
            node_id = str(param["node_id"])
            input_key = param["input_key"]
            if node_id not in result or "inputs" not in result[node_id]:
                raise ValueError(f"Invalid parameter mapping for '{key}'")
            result[node_id]["inputs"][input_key] = value

        return result

    def patch_overrides(
        self,
        template_name: str,
        upserts: Optional[List[Dict[str, Any]]] = None,
        remove_keys: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        overrides = self.get_or_generate_overrides(template_name)
        params = overrides.get("parameters", [])
        by_key = {p.get("key"): p for p in params if p.get("key")}

        for entry in upserts or []:
            key = entry.get("key")
            if not key:
                continue
            by_key[key] = entry

        for key in remove_keys or []:
            by_key.pop(key, None)

        overrides["parameters"] = list(by_key.values())
        self.store.upsert_overrides(template_name, overrides)
        return overrides

    def delete_template(self, template_name: str) -> Dict[str, Any]:
        wf_deleted = self.store.delete_workflow(template_name)
        ov_deleted = self.store.delete_overrides(template_name)
        return {
            "template_name": template_name,
            "workflow_deleted": wf_deleted,
            "overrides_deleted": ov_deleted,
        }

    def get_workflow_info(self, template_name: str) -> Optional[Dict[str, Any]]:
        workflow = self.store.get_workflow(template_name)
        if workflow is None:
            return None
        overrides = self.get_or_generate_overrides(template_name)
        return {
            "name": template_name,
            "parameters": overrides.get("parameters", []),
        }
