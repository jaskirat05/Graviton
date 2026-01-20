"""
Broadcast Service

Redis pub/sub for chain events using Broadcaster library.
"""

import json
import logging
from typing import Optional

from broadcaster import Broadcast

from ..config import get_redis_url

logger = logging.getLogger(__name__)

# Singleton broadcast instance
_broadcast: Optional[Broadcast] = None


def get_broadcast() -> Broadcast:
    """Get singleton broadcast instance"""
    global _broadcast
    if _broadcast is None:
        redis_url = get_redis_url()
        _broadcast = Broadcast(redis_url)
        logger.info(f"Created broadcast instance for {redis_url}")
    return _broadcast


async def connect_broadcast():
    """Connect to Redis (call on startup)"""
    broadcast = get_broadcast()
    await broadcast.connect()
    logger.info("Broadcast connected to Redis")


async def disconnect_broadcast():
    """Disconnect from Redis (call on shutdown)"""
    broadcast = get_broadcast()
    await broadcast.disconnect()
    logger.info("Broadcast disconnected from Redis")


async def publish_chain_event(chain_id: str, event: dict):
    """
    Publish an event to a chain's channel.

    Args:
        chain_id: The chain ID to publish to
        event: Event dict with 'type' and other fields

    Note: Callers are responsible for logging to chain_logger.
    """
    broadcast = get_broadcast()
    channel = f"chain:{chain_id}"
    message = json.dumps(event)

    await broadcast.publish(channel=channel, message=message)
