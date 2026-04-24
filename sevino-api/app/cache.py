"""Redis-backed read-through cache helper.

Stores JSON-serializable values. Non-pickled, by design — keeps payloads
portable across Python versions and avoids deserialization CVEs.
"""
from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

import redis.asyncio as aioredis
import structlog

logger = structlog.get_logger(__name__)


async def cache_get_or_set(
    client: aioredis.Redis,
    key: str,
    ttl: int,
    fetcher: Callable[[], Awaitable[Any]],
) -> Any:
    """Return cached value at `key` or compute-and-store it with SETEX ttl (seconds)."""
    try:
        cached = await client.get(key)
    except aioredis.RedisError:
        logger.warning("cache_get_failed", key=key, exc_info=True)
        return await fetcher()

    if cached is not None:
        return json.loads(cached)

    value = await fetcher()
    try:
        await client.setex(key, ttl, json.dumps(value, default=str))
    except aioredis.RedisError:
        logger.warning("cache_set_failed", key=key, exc_info=True)
    return value
