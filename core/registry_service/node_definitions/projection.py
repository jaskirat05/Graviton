"""In-memory projection store for node definitions."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class InMemoryNodeDefinitionsProjection:
    def __init__(self):
        self._by_workflow: Dict[str, Dict[str, Any]] = {}

    def upsert(self, workflow_name: str, node_definition: Dict[str, Any]) -> None:
        self._by_workflow[workflow_name] = node_definition

    def delete(self, workflow_name: str) -> bool:
        if workflow_name not in self._by_workflow:
            return False
        del self._by_workflow[workflow_name]
        return True

    def get(self, workflow_name: str) -> Optional[Dict[str, Any]]:
        return self._by_workflow.get(workflow_name)

    def list(self) -> List[Dict[str, Any]]:
        return [self._by_workflow[k] for k in sorted(self._by_workflow.keys())]
