"""Node-definition builders and override-parameter mutation helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from core.registry_service.template_store import TemplateStore
from .projection import InMemoryNodeDefinitionsProjection


class NodeDefinitionsService:
    def __init__(
        self,
        template_store: TemplateStore,
        projection: InMemoryNodeDefinitionsProjection,
    ):
        self.template_store = template_store
        self.projection = projection

    @staticmethod
    def _normalize_socket_type(input_key: str) -> str:
        key = input_key.lower()
        if "text" in key:
            return "text"
        if "audio" in key:
            return "audio"
        if "3d" in key:
            return "3d"
        if "file" in key:
            return "file"
        if "video" in key:
            return "video"
        if "image" in key:
            return "image"
        return "any"

    @staticmethod
    def _ui_metadata(overrides: Dict[str, Any], template_name: str) -> Dict[str, Any]:
        raw = overrides.get("ui_metadata")
        if not isinstance(raw, dict):
            legacy = overrides.get("_ui_metadata")
            raw = legacy if isinstance(legacy, dict) else {}
        return {
            "nodeType": raw.get("nodeType", "utility_workflow"),
            "label": raw.get("label", template_name),
            "icon": raw.get("icon", "workflow"),
            "color": raw.get("color", "#666666"),
            "category": raw.get("category", "utility"),
            "outputSockets": raw.get("outputSockets", []),
        }

    def build_node_definition(
        self,
        template_name: str,
        overrides: Dict[str, Any],
    ) -> Dict[str, Any]:
        ui = self._ui_metadata(overrides, template_name)
        parameters = overrides.get("parameters", [])
        status_doc = self.template_store.get_status(template_name) or {}
        template_status = status_doc.get("status", "active")
        is_invalid = template_status != "active"

        input_sockets: List[Dict[str, Any]] = []
        for param in parameters:
            if str(param.get("category", "")) != "bridge_input":
                continue
            key = param.get("key")
            if not key:
                continue
            input_key = str(param.get("input_key", ""))
            io_type = str(param.get("io_type", "")).strip().lower()
            input_sockets.append(
                {
                    "id": key,
                    "type": io_type or self._normalize_socket_type(input_key),
                    "label": param.get("node_title") or input_key,
                }
            )

        output_sockets = ui.get("outputSockets", [])
        if not isinstance(output_sockets, list):
            output_sockets = []

        return {
            "workflow_name": template_name,
            "workflow_hash": overrides.get("workflow_hash"),
            "nodeType": ui["nodeType"],
            "label": ui["label"],
            "icon": ui["icon"],
            "color": ui["color"],
            "category": "invalid" if is_invalid else ui["category"],
            "status": template_status,
            "is_invalid": is_invalid,
            "validation_errors": status_doc.get("policy_errors", []),
            "inputSockets": input_sockets,
            "outputSockets": output_sockets,
            "parameters": [
                {
                    "key": p.get("key"),
                    "input_key": p.get("input_key"),
                    "default_value": p.get("default_value"),
                    "type": p.get("type", "str"),
                    "description": p.get("description", ""),
                    "category": p.get("category", "other"),
                }
                for p in parameters
                if p.get("key") and p.get("input_key")
            ],
        }

    def bootstrap_from_templates(self) -> int:
        count = 0
        for template_name in self.template_store.list_templates():
            if self.refresh_projection(template_name):
                count += 1
        return count

    def refresh_projection(self, template_name: str) -> bool:
        workflow = self.template_store.get_workflow(template_name)
        overrides = self.template_store.get_overrides(template_name)
        if workflow is None or overrides is None:
            return False
        node_definition = self.build_node_definition(template_name, overrides)
        self.projection.upsert(template_name, node_definition)
        return True

    def list_node_definitions(self) -> List[Dict[str, Any]]:
        return self.projection.list()

    def get_node_definition(self, template_name: str) -> Dict[str, Any]:
        node_definition = self.projection.get(template_name)
        if node_definition is None:
            raise ValueError(f"Node definition not found: {template_name}")
        return node_definition

    def delete_node_definition(self, template_name: str) -> bool:
        return self.projection.delete(template_name)

    def build_overrides_for_replace(
        self, template_name: str, parameters: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        existing = self.template_store.get_overrides(template_name) or {}
        merged = dict(existing)
        merged["workflow_name"] = template_name
        merged["generated_at"] = datetime.now(timezone.utc).isoformat()
        merged["parameters"] = parameters
        return merged

    def build_overrides_for_patch(
        self,
        template_name: str,
        upserts: List[Dict[str, Any]],
        remove_keys: List[str],
    ) -> Dict[str, Any]:
        existing = self.template_store.get_overrides(template_name) or {}
        by_key = {
            p.get("key"): p
            for p in existing.get("parameters", [])
            if isinstance(p, dict) and p.get("key")
        }

        for entry in upserts:
            key = entry.get("key")
            if key:
                by_key[key] = entry

        for key in remove_keys:
            by_key.pop(key, None)

        merged = dict(existing)
        merged["workflow_name"] = template_name
        merged["generated_at"] = datetime.now(timezone.utc).isoformat()
        merged["parameters"] = list(by_key.values())
        return merged
