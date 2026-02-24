"""API request/response models for registry rewrite service."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class ServerUpsertRequest(BaseModel):
    name: str = Field(..., min_length=1)
    provider: str = Field(default="comfyui")
    address: str
    port: Optional[int] = None
    ssl: bool = False
    tags: Dict[str, Any] = Field(default_factory=dict)
    weight: int = 1


class ServerResponse(BaseModel):
    id: str
    name: str
    provider: str
    address: str
    port: Optional[int]
    ssl: bool
    status: str
    tags: Dict[str, Any]
    weight: int


class PingRequest(BaseModel):
    reported_at: Optional[str] = None
    ok: bool
    latency_ms: Optional[float] = None
    queue_depth: Optional[int] = None
    gpu_utilization: Optional[float] = None
    vram_free_mb: Optional[float] = None
    error: Optional[str] = None
    raw_payload: Dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    server_id: str
    health_state: str
    reason: str
    last_seen_at: Optional[str] = None


class TemplateWorkflowRequest(BaseModel):
    workflow: Dict[str, Any]


class TemplateOverridesRequest(BaseModel):
    overrides: Dict[str, Any]


class TemplateOverridesPatchRequest(BaseModel):
    upserts: list[Dict[str, Any]] = Field(default_factory=list)
    remove_keys: list[str] = Field(default_factory=list)


class TemplateApplyOverridesRequest(BaseModel):
    runtime_overrides: Dict[str, Any] = Field(default_factory=dict)


class TemplateRevalidateRequest(BaseModel):
    workflow: Dict[str, Any]
    server_name: Optional[str] = None


class DataPlaneModeRequest(BaseModel):
    mode: str = Field(..., description="Bridge data plane mode: local|orchestrator|s3|cloudinary")


class WorkerControlSecretResponse(BaseModel):
    server_id: str
    server_name: str
    worker_id: str
    secret_version: int
    shared_secret: str
    created_at: str
    rotated_at: Optional[str] = None


class WorkerControlSecretMetaResponse(BaseModel):
    server_id: str
    server_name: str
    worker_id: str
    secret_version: int
    created_at: str
    rotated_at: Optional[str] = None


class RegisterWorkerSecretRequest(BaseModel):
    rotate: bool = False


class ControlPlaneSettingsResponse(BaseModel):
    settings_hash: str
    config_version: Optional[str] = None
    settings: Dict[str, Any]
    updated_at: str
    last_applied_at: Optional[str] = None


class ControlPlaneSyncRequest(BaseModel):
    force: bool = False


class WorkerConfigPushJobResponse(BaseModel):
    id: str
    server_id: str
    server_name: str
    target_hash: str
    status: str
    attempts: int
    last_error: Optional[str] = None
    next_retry_at: Optional[str] = None
    updated_at: str
    created_at: str


class ServerControlPlaneStatusResponse(BaseModel):
    server_id: str
    server_name: str
    desired_hash: str
    observed_hash: Optional[str] = None
    desired_version: Optional[str] = None
    observed_version: Optional[str] = None
    desired_mode: Optional[str] = None
    observed_mode: Optional[str] = None
    is_outdated: bool = False
    reachable: bool = True
    error: Optional[str] = None
