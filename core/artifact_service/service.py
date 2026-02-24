from __future__ import annotations

import json
from typing import Any

from core.artifact_service.models import AssetRef
from core.artifact_service.providers.base import ArtifactProvider
from core.artifact_service.providers.cloudinary import CloudinaryArtifactProvider
from core.artifact_service.providers.s3 import S3ArtifactProvider


class ArtifactService:
    """
    Provider-routed artifact CRUD service.

    Uses provider in asset_ref for read/update/delete/download-url operations.
    """

    def __init__(self, providers: dict[str, ArtifactProvider] | None = None) -> None:
        if providers is not None:
            self._providers = providers
            self._provider_init_errors: dict[str, str] = {}
            return

        resolved: dict[str, ArtifactProvider] = {}
        init_errors: dict[str, str] = {}
        for provider_cls in (S3ArtifactProvider, CloudinaryArtifactProvider):
            try:
                provider = provider_cls()
            except Exception as error:
                inferred_name = provider_cls.__name__.replace("ArtifactProvider", "").lower()
                init_errors[inferred_name] = str(error)
                continue
            resolved[provider.name] = provider
        self._providers = resolved
        self._provider_init_errors = init_errors

    def _provider(self, name: str) -> ArtifactProvider:
        provider = self._providers.get(name)
        if provider is None:
            init_error = self._provider_init_errors.get(name)
            if init_error:
                raise ValueError(f"Artifact provider '{name}' is unconfigured: {init_error}")
            raise ValueError(f"Unsupported or unconfigured artifact provider: {name}")
        return provider

    def _to_asset_ref(self, asset_ref: dict[str, Any] | str) -> AssetRef:
        payload: dict[str, Any]
        if isinstance(asset_ref, str):
            raw = asset_ref.strip()
            if not raw:
                raise ValueError("asset_ref is empty")
            try:
                parsed = json.loads(raw)
            except Exception as error:
                raise ValueError("asset_ref string must be valid JSON") from error
            if not isinstance(parsed, dict):
                raise ValueError("asset_ref JSON must be an object")
            payload = parsed
        elif isinstance(asset_ref, dict):
            payload = asset_ref
        else:
            raise ValueError("asset_ref must be a dict or JSON string")
        parsed = AssetRef.from_dict(payload)
        if not parsed.provider:
            raise ValueError("asset_ref.provider is required")
        if not parsed.asset_id:
            raise ValueError("asset_ref.asset_id is required")
        return parsed

    def create(
        self,
        *,
        provider: str,
        payload: bytes,
        filename: str,
        kind: str,
        mime_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        created = self._provider(provider).create(
            payload,
            filename=filename,
            kind=kind,
            mime_type=mime_type,
            metadata=metadata,
        )
        return created.to_dict()

    def read(self, *, asset_ref: dict[str, Any] | str) -> dict[str, Any]:
        parsed = self._to_asset_ref(asset_ref)
        loaded = self._provider(parsed.provider).read(parsed.asset_id)
        if loaded is None:
            raise ValueError(f"Asset not found: {parsed.asset_id}")
        return loaded.to_dict()

    def get_download_url(
        self,
        *,
        asset_ref: dict[str, Any] | str,
        expires_in: int = 3600,
    ) -> str:
        parsed = self._to_asset_ref(asset_ref)
        return self._provider(parsed.provider).get_download_url(
            parsed.asset_id,
            expires_in=expires_in,
        )

    def update(
        self,
        *,
        asset_ref: dict[str, Any] | str,
        payload: bytes,
        filename: str | None = None,
        mime_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        parsed = self._to_asset_ref(asset_ref)
        updated = self._provider(parsed.provider).update(
            parsed.asset_id,
            payload,
            filename=filename,
            mime_type=mime_type,
            metadata=metadata,
        )
        return updated.to_dict()

    def delete(self, *, asset_ref: dict[str, Any] | str) -> None:
        parsed = self._to_asset_ref(asset_ref)
        self._provider(parsed.provider).delete(parsed.asset_id)
