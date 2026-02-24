from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from core.artifact_service.models import AssetRef


class ArtifactProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def create(
        self,
        payload: bytes,
        *,
        filename: str,
        kind: str,
        mime_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AssetRef:
        raise NotImplementedError

    @abstractmethod
    def read(self, asset_id: str) -> AssetRef | None:
        raise NotImplementedError

    @abstractmethod
    def get_download_url(self, asset_id: str, *, expires_in: int = 3600) -> str:
        raise NotImplementedError

    @abstractmethod
    def update(
        self,
        asset_id: str,
        payload: bytes,
        *,
        filename: str | None = None,
        mime_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AssetRef:
        raise NotImplementedError

    @abstractmethod
    def delete(self, asset_id: str) -> None:
        raise NotImplementedError
