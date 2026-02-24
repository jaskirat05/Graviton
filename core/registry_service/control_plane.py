"""Control-plane config helpers for bridge fanout."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import string
import time
from typing import Any
from uuid import uuid4

from .env import load_root_env

load_root_env()


def _env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def build_control_plane_config_from_env() -> dict[str, Any]:
    """Build sparse bridge config payload from env without filling missing keys."""
    mode = (_env("REGISTRY_DATAPLANE_MODE") or "local").lower()
    config: dict[str, Any] = {"mode": mode}

    orchestrator = {
        "base_url": _env("REGISTRY_DATAPLANE_ORCHESTRATOR_BASE_URL"),
        "token": _env("REGISTRY_DATAPLANE_ORCHESTRATOR_TOKEN"),
    }
    if any(v is not None for v in orchestrator.values()):
        config["orchestrator"] = {k: v for k, v in orchestrator.items() if v is not None}

    s3 = {
        "bucket": _env("REGISTRY_DATAPLANE_S3_BUCKET"),
        "region": _env("REGISTRY_DATAPLANE_S3_REGION"),
        "prefix": _env("REGISTRY_DATAPLANE_S3_PREFIX"),
        "access_key": _env("REGISTRY_DATAPLANE_S3_ACCESS_KEY"),
        "secret_key": _env("REGISTRY_DATAPLANE_S3_SECRET_KEY"),
    }
    if any(v is not None for v in s3.values()):
        config["s3"] = {k: v for k, v in s3.items() if v is not None}

    cloudinary = {
        "cloud_name": _env("REGISTRY_DATAPLANE_CLOUDINARY_CLOUD_NAME"),
        "api_key": _env("REGISTRY_DATAPLANE_CLOUDINARY_API_KEY"),
        "api_secret": _env("REGISTRY_DATAPLANE_CLOUDINARY_API_SECRET"),
        "folder": _env("REGISTRY_DATAPLANE_CLOUDINARY_FOLDER"),
    }
    if any(v is not None for v in cloudinary.values()):
        config["cloudinary"] = {k: v for k, v in cloudinary.items() if v is not None}

    return config


def canonical_json(data: dict[str, Any]) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def compute_settings_hash(data: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(data)).hexdigest()


def build_bridge_hmac_headers(
    secret: str,
    method: str,
    path: str,
    body: bytes,
) -> dict[str, str]:
    timestamp = str(int(time.time()))
    nonce = uuid4().hex
    message = (
        method.upper().encode("utf-8")
        + b"\n"
        + path.encode("utf-8")
        + b"\n"
        + timestamp.encode("utf-8")
        + b"\n"
        + nonce.encode("utf-8")
        + b"\n"
        + body
    )
    signature = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return {
        "X-Graviton-Timestamp": timestamp,
        "X-Graviton-Nonce": nonce,
        "X-Graviton-Signature": signature,
    }


def generate_shared_secret() -> str:
    return secrets.token_urlsafe(48)


def generate_config_version(length: int = 5) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(max(1, int(length))))


def redact_control_plane_config(config: dict[str, Any]) -> dict[str, Any]:
    redacted = json.loads(json.dumps(config))
    for section, key in (
        ("orchestrator", "token"),
        ("s3", "access_key"),
        ("s3", "secret_key"),
        ("cloudinary", "api_key"),
        ("cloudinary", "api_secret"),
    ):
        data = redacted.get(section)
        if isinstance(data, dict) and key in data and data[key]:
            data[key] = "***"
    return redacted
