from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.artifact_service.models import AssetRef
from core.artifact_service.providers.base import ArtifactProvider


class S3ArtifactProvider(ArtifactProvider):
    def __init__(self) -> None:
        self.bucket = os.getenv("REGISTRY_DATAPLANE_S3_BUCKET", "").strip()
        self.region = os.getenv("REGISTRY_DATAPLANE_S3_REGION", "").strip()
        self.prefix = os.getenv("REGISTRY_DATAPLANE_S3_PREFIX", "").strip().strip("/")
        self.access_key = os.getenv("REGISTRY_DATAPLANE_S3_ACCESS_KEY", "").strip()
        self.secret_key = os.getenv("REGISTRY_DATAPLANE_S3_SECRET_KEY", "").strip()

        if not self.bucket:
            raise ValueError("Missing REGISTRY_DATAPLANE_S3_BUCKET")
        if not self.region:
            raise ValueError("Missing REGISTRY_DATAPLANE_S3_REGION")
        if not self.access_key or not self.secret_key:
            raise ValueError("Missing REGISTRY_DATAPLANE_S3_ACCESS_KEY / REGISTRY_DATAPLANE_S3_SECRET_KEY")

        self._s3 = self._build_client()

    @property
    def name(self) -> str:
        return "s3"

    def _build_client(self):
        try:
            import boto3
        except Exception as error:  # pragma: no cover - depends on runtime install
            raise RuntimeError("S3 artifact provider requires boto3") from error
        return boto3.client(
            "s3",
            region_name=self.region,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
        )

    def _join_key(self, *parts: str) -> str:
        return "/".join(p.strip("/") for p in parts if p and p.strip("/"))

    def _meta_key(self, asset_id: str) -> str:
        return self._join_key(self.prefix, "meta", f"{asset_id}.json")

    def _blob_key(self, asset_id: str, filename: str) -> str:
        suffix = Path(filename).suffix or ".bin"
        return self._join_key(self.prefix, "blobs", f"{asset_id}{suffix}")

    def _build_locator(self, key: str) -> str:
        return f"s3://{self.bucket}/{key}"

    def _parse_locator_key(self, locator: str) -> str:
        expected_prefix = f"s3://{self.bucket}/"
        if not locator.startswith(expected_prefix):
            raise ValueError(f"Invalid S3 locator: {locator}")
        return locator[len(expected_prefix) :]

    def _write_meta(self, data: dict[str, Any]) -> None:
        self._s3.put_object(
            Bucket=self.bucket,
            Key=self._meta_key(str(data.get("asset_id", ""))),
            Body=json.dumps(data, sort_keys=True).encode("utf-8"),
            ContentType="application/json",
        )

    def _read_meta_raw(self, asset_id: str) -> dict[str, Any] | None:
        try:
            res = self._s3.get_object(Bucket=self.bucket, Key=self._meta_key(asset_id))
        except Exception:
            return None
        body = res.get("Body")
        if body is None:
            return None
        try:
            parsed = json.loads(body.read().decode("utf-8"))
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) else None

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
        resolved_mime = mime_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        blob_key = self._blob_key(asset_id, filename)
        checksum = f"sha256:{hashlib.sha256(payload).hexdigest()}"

        self._s3.put_object(
            Bucket=self.bucket,
            Key=blob_key,
            Body=payload,
            ContentType=resolved_mime,
        )

        ref = AssetRef(
            asset_id=asset_id,
            provider=self.name,
            kind=kind,
            mime_type=resolved_mime,
            size_bytes=len(payload),
            checksum=checksum,
            locator=self._build_locator(blob_key),
            filename=filename,
            created_at=datetime.now(timezone.utc).isoformat(),
            metadata=metadata or {},
        )
        self._write_meta(ref.to_dict())
        return ref

    def read(self, asset_id: str) -> AssetRef | None:
        raw = self._read_meta_raw(asset_id)
        if not raw:
            return None
        return AssetRef.from_dict(raw)

    def get_download_url(self, asset_id: str, *, expires_in: int = 3600) -> str:
        ref = self.read(asset_id)
        if ref is None:
            raise ValueError(f"Asset not found: {asset_id}")
        key = self._parse_locator_key(ref.locator)
        return str(
            self._s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=max(60, int(expires_in)),
            )
        )

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

        next_filename = filename or existing.filename or f"{asset_id}.bin"
        next_mime = mime_type or mimetypes.guess_type(next_filename)[0] or existing.mime_type
        next_meta = dict(existing.metadata)
        if metadata:
            next_meta.update(metadata)

        blob_key = self._blob_key(asset_id, next_filename)
        checksum = f"sha256:{hashlib.sha256(payload).hexdigest()}"

        self._s3.put_object(
            Bucket=self.bucket,
            Key=blob_key,
            Body=payload,
            ContentType=next_mime,
        )

        updated = AssetRef(
            asset_id=asset_id,
            provider=self.name,
            kind=existing.kind,
            mime_type=next_mime,
            size_bytes=len(payload),
            checksum=checksum,
            locator=self._build_locator(blob_key),
            filename=next_filename,
            created_at=existing.created_at,
            metadata=next_meta,
        )
        self._write_meta(updated.to_dict())
        return updated

    def delete(self, asset_id: str) -> None:
        existing = self.read(asset_id)
        if existing is None:
            return
        blob_key = self._parse_locator_key(existing.locator)
        self._s3.delete_object(Bucket=self.bucket, Key=blob_key)
        self._s3.delete_object(Bucket=self.bucket, Key=self._meta_key(asset_id))
