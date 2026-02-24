from __future__ import annotations

import hashlib
import mimetypes
import os
import time
import uuid
from typing import Any
from urllib.parse import quote

import httpx

from core.artifact_service.models import AssetRef
from core.artifact_service.providers.base import ArtifactProvider


class CloudinaryArtifactProvider(ArtifactProvider):
    def __init__(self) -> None:
        self.cloud_name = os.getenv("REGISTRY_DATAPLANE_CLOUDINARY_CLOUD_NAME", "").strip()
        self.api_key = os.getenv("REGISTRY_DATAPLANE_CLOUDINARY_API_KEY", "").strip()
        self.api_secret = os.getenv("REGISTRY_DATAPLANE_CLOUDINARY_API_SECRET", "").strip()
        self.folder = os.getenv("REGISTRY_DATAPLANE_CLOUDINARY_FOLDER", "").strip().strip("/")

        if not self.cloud_name:
            raise ValueError("Missing REGISTRY_DATAPLANE_CLOUDINARY_CLOUD_NAME")
        if not self.api_key or not self.api_secret:
            raise ValueError(
                "Missing REGISTRY_DATAPLANE_CLOUDINARY_API_KEY / REGISTRY_DATAPLANE_CLOUDINARY_API_SECRET"
            )

        self.upload_base = f"https://api.cloudinary.com/v1_1/{self.cloud_name}"

    @property
    def name(self) -> str:
        return "cloudinary"

    def _public_id_for(self, asset_id: str) -> str:
        if self.folder:
            return f"{self.folder}/{asset_id}"
        return asset_id

    def _asset_id_from_public_id(self, public_id: str) -> str:
        return public_id.split("/")[-1]

    def _resource_url(self, resource_type: str, public_id: str) -> str:
        encoded = quote(public_id, safe="")
        return f"{self.upload_base}/resources/{resource_type}/upload/{encoded}"

    def _signature(self, params: dict[str, Any]) -> str:
        filtered = {
            k: v
            for k, v in params.items()
            if v is not None and v != "" and k not in {"file", "api_key", "signature"}
        }
        serialized = "&".join(f"{k}={filtered[k]}" for k in sorted(filtered))
        return hashlib.sha1(f"{serialized}{self.api_secret}".encode("utf-8")).hexdigest()

    def _auth(self) -> tuple[str, str]:
        return (self.api_key, self.api_secret)

    def _kind_from_resource(self, resource_type: str, fallback: str = "file") -> str:
        if resource_type == "image":
            return "image"
        if resource_type == "video":
            return "video"
        return fallback

    def _mime_from_resource(self, resource_type: str, fmt: str | None, fallback: str) -> str:
        if resource_type == "image" and fmt:
            return f"image/{fmt}"
        if resource_type == "video" and fmt:
            return f"video/{fmt}"
        if fmt:
            guessed = mimetypes.guess_type(f"x.{fmt}")[0]
            if guessed:
                return guessed
        return fallback

    def _to_asset_ref(self, resource: dict[str, Any], *, checksum: str = "") -> AssetRef:
        public_id = str(resource.get("public_id", ""))
        resource_type = str(resource.get("resource_type", "raw"))
        fmt = str(resource.get("format", "")).strip() or None
        secure_url = str(resource.get("secure_url", "")).strip()
        bytes_size = int(resource.get("bytes", 0) or 0)
        created_at = str(resource.get("created_at", ""))
        original_name = str(resource.get("original_filename", "")).strip()
        filename = (
            f"{original_name}.{fmt}" if original_name and fmt else (original_name or self._asset_id_from_public_id(public_id))
        )

        return AssetRef(
            asset_id=self._asset_id_from_public_id(public_id),
            provider=self.name,
            kind=self._kind_from_resource(resource_type),
            mime_type=self._mime_from_resource(resource_type, fmt, "application/octet-stream"),
            size_bytes=bytes_size,
            checksum=checksum,
            locator=f"cloudinary://{self.cloud_name}/{resource_type}/upload/{public_id}",
            filename=filename,
            created_at=created_at,
            metadata={
                "public_id": public_id,
                "resource_type": resource_type,
                "secure_url": secure_url,
            },
        )

    def _fetch_resource(self, public_id: str) -> dict[str, Any] | None:
        with httpx.Client(timeout=30.0) as client:
            for resource_type in ("image", "video", "raw"):
                response = client.get(self._resource_url(resource_type, public_id), auth=self._auth())
                if response.status_code == 404:
                    continue
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, dict):
                    return payload
        return None

    def create(
        self,
        payload: bytes,
        *,
        filename: str,
        kind: str,
        mime_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AssetRef:
        asset_id = str(uuid.uuid4())
        public_id = self._public_id_for(asset_id)
        checksum = f"sha256:{hashlib.sha256(payload).hexdigest()}"
        ts = int(time.time())
        params: dict[str, Any] = {
            "timestamp": ts,
            "public_id": public_id,
            "overwrite": "true",
            "unique_filename": "false",
        }
        signature = self._signature(params)

        data: dict[str, Any] = {**params, "api_key": self.api_key, "signature": signature}
        if metadata:
            data["context"] = "|".join(f"{k}={v}" for k, v in metadata.items() if v is not None)

        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                f"{self.upload_base}/auto/upload",
                data=data,
                files={"file": (filename, payload, mime_type or "application/octet-stream")},
            )
            response.raise_for_status()
            raw = response.json()
            if not isinstance(raw, dict):
                raise ValueError("Invalid Cloudinary upload response")
            ref = self._to_asset_ref(raw, checksum=checksum)
            merged_meta = dict(ref.metadata)
            if metadata:
                merged_meta.update(metadata)
            return AssetRef(
                asset_id=ref.asset_id,
                provider=ref.provider,
                kind=kind or ref.kind,
                mime_type=ref.mime_type,
                size_bytes=ref.size_bytes,
                checksum=ref.checksum,
                locator=ref.locator,
                filename=ref.filename,
                created_at=ref.created_at,
                metadata=merged_meta,
            )

    def read(self, asset_id: str) -> AssetRef | None:
        resource = self._fetch_resource(self._public_id_for(asset_id))
        if not resource:
            return None
        return self._to_asset_ref(resource)

    def get_download_url(self, asset_id: str, *, expires_in: int = 3600) -> str:
        ref = self.read(asset_id)
        if ref is None:
            raise ValueError(f"Asset not found: {asset_id}")
        secure_url = str(ref.metadata.get("secure_url", "")).strip()
        if not secure_url:
            raise ValueError(f"Missing secure_url for Cloudinary asset: {asset_id}")
        return secure_url

    def update(
        self,
        asset_id: str,
        payload: bytes,
        *,
        filename: str | None = None,
        mime_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AssetRef:
        existing = self.read(asset_id)
        if existing is None:
            raise ValueError(f"Asset not found: {asset_id}")

        public_id = str(existing.metadata.get("public_id", "")).strip() or self._public_id_for(asset_id)
        ts = int(time.time())
        params: dict[str, Any] = {
            "timestamp": ts,
            "public_id": public_id,
            "overwrite": "true",
            "unique_filename": "false",
        }
        signature = self._signature(params)

        data: dict[str, Any] = {**params, "api_key": self.api_key, "signature": signature}
        if metadata:
            data["context"] = "|".join(f"{k}={v}" for k, v in metadata.items() if v is not None)
        checksum = f"sha256:{hashlib.sha256(payload).hexdigest()}"
        next_filename = filename or existing.filename or f"{asset_id}.bin"

        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                f"{self.upload_base}/auto/upload",
                data=data,
                files={"file": (next_filename, payload, mime_type or existing.mime_type)},
            )
            response.raise_for_status()
            raw = response.json()
            if not isinstance(raw, dict):
                raise ValueError("Invalid Cloudinary upload response")
            ref = self._to_asset_ref(raw, checksum=checksum)
            merged_meta = dict(ref.metadata)
            merged_meta.update(existing.metadata)
            if metadata:
                merged_meta.update(metadata)
            return AssetRef(
                asset_id=ref.asset_id,
                provider=ref.provider,
                kind=existing.kind,
                mime_type=ref.mime_type,
                size_bytes=ref.size_bytes,
                checksum=ref.checksum,
                locator=ref.locator,
                filename=next_filename,
                created_at=existing.created_at or ref.created_at,
                metadata=merged_meta,
            )

    def delete(self, asset_id: str) -> None:
        existing = self.read(asset_id)
        if existing is None:
            return
        public_id = str(existing.metadata.get("public_id", "")).strip() or self._public_id_for(asset_id)
        ts = int(time.time())
        for resource_type in ("image", "video", "raw"):
            params: dict[str, Any] = {"public_id": public_id, "timestamp": ts, "invalidate": "true"}
            signature = self._signature(params)
            data = {**params, "api_key": self.api_key, "signature": signature}
            with httpx.Client(timeout=30.0) as client:
                response = client.post(f"{self.upload_base}/{resource_type}/destroy", data=data)
                if response.status_code in (200, 404):
                    continue
                response.raise_for_status()
