from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AssetRef:
    asset_id: str
    provider: str
    kind: str
    mime_type: str
    size_bytes: int
    checksum: str
    locator: str
    filename: str
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "provider": self.provider,
            "kind": self.kind,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "checksum": self.checksum,
            "locator": self.locator,
            "filename": self.filename,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AssetRef":
        return cls(
            asset_id=str(raw.get("asset_id", "")),
            provider=str(raw.get("provider", "")),
            kind=str(raw.get("kind", "file")),
            mime_type=str(raw.get("mime_type", "application/octet-stream")),
            size_bytes=int(raw.get("size_bytes", 0) or 0),
            checksum=str(raw.get("checksum", "")),
            locator=str(raw.get("locator", "")),
            filename=str(raw.get("filename", "")),
            created_at=str(raw.get("created_at", "")),
            metadata=raw.get("metadata", {}) if isinstance(raw.get("metadata"), dict) else {},
        )
