"""NATS JetStream event bus implementation."""

from __future__ import annotations

from typing import Awaitable, Callable

from nats.aio.client import Client as NATS
from nats.aio.msg import Msg

from .config import settings
from .events import EventEnvelope


class JetStreamEventBus:
    def __init__(self):
        self._nc = NATS()
        self._js = None

    async def connect(self) -> None:
        await self._nc.connect(servers=[settings.nats_url])
        self._js = self._nc.jetstream()

        # Ensure stream exists (idempotent-ish initialization)
        await self._js.add_stream(
            name=settings.nats_stream,
            subjects=[f"{settings.nats_subject_prefix}.>"]
        )

    async def close(self) -> None:
        if self._nc.is_connected:
            await self._nc.close()

    async def publish(self, envelope: EventEnvelope) -> None:
        subject = f"{settings.nats_subject_prefix}.{envelope.aggregate_type}.{envelope.event_type}"
        data = envelope.model_dump_json().encode("utf-8")
        await self._js.publish(subject, data)

    async def subscribe(
        self,
        subject: str,
        handler: Callable[[Msg], Awaitable[None]],
        durable: str | None = None,
    ):
        return await self._js.subscribe(subject, cb=handler, durable=durable)
