"""Redis-backed read-through cache helper.

Stores JSON-serializable values. Non-pickled, by design — keeps payloads
portable across Python versions and avoids deserialization CVEs.

Note: serialization uses ``json.dumps(..., default=str)`` so non-JSON-native
types (``Decimal``, ``datetime``, etc.) round-trip as strings. Callers that
need exact numeric types must re-coerce after decoding.
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
        try:
            return json.loads(cached)
        except json.JSONDecodeError:
            logger.warning("cache_decode_failed", key=key, exc_info=True)

    value = await fetcher()
    try:
        await client.setex(key, ttl, json.dumps(value, default=str))
    except aioredis.RedisError:
        logger.warning("cache_set_failed", key=key, exc_info=True)
    return value


async def cache_invalidate(client: aioredis.Redis, keys: list[str]) -> None:
    """Best-effort DELETE of one or more cache keys.

    Empty list is a no-op (Redis ``DEL`` rejects zero args). ``RedisError``
    is logged and swallowed — callers (SSE listeners, etc.) shouldn't crash
    on a transient Redis blip; cache items live to their TTL.
    """
    if not keys:
        return
    try:
        await client.delete(*keys)
    except aioredis.RedisError:
        logger.warning("cache_invalidate_failed", keys=keys, exc_info=True)
