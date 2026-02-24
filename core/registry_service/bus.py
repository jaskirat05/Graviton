"""Event bus interface for registry rewrite."""

from __future__ import annotations

from typing import Protocol

from .events import EventEnvelope


class EventBus(Protocol):
    async def connect(self) -> None:
        ...

    async def close(self) -> None:
        ...

    async def publish(self, envelope: EventEnvelope) -> None:
        ...
