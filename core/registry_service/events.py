"""Domain events and event envelope definitions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


AggregateType = Literal["server", "template", "template_override_set", "control_plane"]


class EventEnvelope(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: str
    aggregate_type: AggregateType
    aggregate_id: str
    aggregate_version: int = 1
    occurred_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    schema_version: int = 1
    payload: Dict[str, Any]


class EventTypes:
    SERVER_REGISTERED = "ServerRegistered"
    SERVER_UPDATED = "ServerUpdated"
    DATA_PLANE_MODE_UPDATED = "DataPlaneModeUpdated"
    CONTROL_PLANE_SETTINGS_UPDATED = "ControlPlaneSettingsUpdated"
    SERVER_PING_RECEIVED = "ServerPingReceived"
    SERVER_HEALTH_EVALUATED = "ServerHealthEvaluated"
    TEMPLATE_WORKFLOW_UPSERTED = "TemplateWorkflowUpserted"
    TEMPLATE_OVERRIDES_UPSERTED = "TemplateOverridesUpserted"
