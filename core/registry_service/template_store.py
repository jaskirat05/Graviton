"""Filesystem-backed template storage for registry service.

Uses a dedicated directory tree:
- <root>/workflows/<template>.json
- <root>/overrides/<template>.json
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import settings

_SAFE_NAME = re.compile(r"^[a-zA-Z0-9._-]+$")


class TemplateStore:
    def __init__(self):
        self.workflows_dir = settings.template_workflows_dir
        self.overrides_dir = settings.template_overrides_dir
        self.status_dir = Path(settings.template_root_dir) / "status"
        self.workflows_dir.mkdir(parents=True, exist_ok=True)
        self.overrides_dir.mkdir(parents=True, exist_ok=True)
        self.status_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _normalize_name(template_name: str) -> str:
        name = template_name.replace(".json", "")
        if _SAFE_NAME.match(name):
            return name
        # Keep sync resilient to external names (spaces, +, etc.).
        sanitized = re.sub(r"[^a-zA-Z0-9._-]+", "_", name).strip("._-")
        if not sanitized:
            raise ValueError("Invalid template name")
        return sanitized

    def _workflow_path(self, template_name: str) -> Path:
        name = self._normalize_name(template_name)
        return self.workflows_dir / f"{name}.json"

    def _overrides_path(self, template_name: str) -> Path:
        name = self._normalize_name(template_name)
        return self.overrides_dir / f"{name}.json"

    def _status_path(self, template_name: str) -> Path:
        name = self._normalize_name(template_name)
        return self.status_dir / f"{name}.json"

    def list_templates(self) -> List[str]:
        names = set()
        for p in self.workflows_dir.glob("*.json"):
            names.add(p.stem)
        for p in self.overrides_dir.glob("*.json"):
            names.add(p.stem)
        return sorted(names)

    def upsert_workflow(self, template_name: str, workflow: Dict[str, Any]) -> Path:
        path = self._workflow_path(template_name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(workflow, f, indent=2, ensure_ascii=False)
        return path

    def upsert_overrides(self, template_name: str, overrides: Dict[str, Any]) -> Path:
        path = self._overrides_path(template_name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(overrides, f, indent=2, ensure_ascii=False)
        return path

    def upsert_status(self, template_name: str, status: Dict[str, Any]) -> Path:
        path = self._status_path(template_name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(status, f, indent=2, ensure_ascii=False)
        return path

    def get_workflow(self, template_name: str) -> Optional[Dict[str, Any]]:
        path = self._workflow_path(template_name)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_overrides(self, template_name: str) -> Optional[Dict[str, Any]]:
        path = self._overrides_path(template_name)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_status(self, template_name: str) -> Optional[Dict[str, Any]]:
        path = self._status_path(template_name)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def delete_workflow(self, template_name: str) -> bool:
        path = self._workflow_path(template_name)
        if not path.exists():
            return False
        path.unlink()
        return True

    def delete_overrides(self, template_name: str) -> bool:
        path = self._overrides_path(template_name)
        if not path.exists():
            return False
        path.unlink()
        return True

    def delete_status(self, template_name: str) -> bool:
        path = self._status_path(template_name)
        if not path.exists():
            return False
        path.unlink()
        return True
