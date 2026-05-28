import json
from unittest.mock import AsyncMock

import pytest
import redis.asyncio as aioredis

from app.cache import cache_get_or_set, cache_invalidate


@pytest.fixture
def redis_mock():
    mock = AsyncMock()
    mock.get = AsyncMock()
    mock.setex = AsyncMock()
    mock.delete = AsyncMock()
    return mock


async def test_miss_calls_fetcher_and_sets_cache(redis_mock):
    redis_mock.get.return_value = None
    fetcher = AsyncMock(return_value={"a": 1})

    result = await cache_get_or_set(redis_mock, "k", 30, fetcher)

    assert result == {"a": 1}
    fetcher.assert_awaited_once()
    redis_mock.setex.assert_awaited_once_with("k", 30, json.dumps({"a": 1}, default=str))


async def test_hit_returns_cached_without_fetching(redis_mock):
    redis_mock.get.return_value = json.dumps({"cached": True})
    fetcher = AsyncMock()

    result = await cache_get_or_set(redis_mock, "k", 30, fetcher)

    assert result == {"cached": True}
    fetcher.assert_not_awaited()
    redis_mock.setex.assert_not_awaited()


async def test_get_failure_falls_back_to_fetcher(redis_mock):
    redis_mock.get.side_effect = aioredis.RedisError("boom")
    fetcher = AsyncMock(return_value={"fresh": True})

    result = await cache_get_or_set(redis_mock, "k", 30, fetcher)

    assert result == {"fresh": True}
    fetcher.assert_awaited_once()
    redis_mock.setex.assert_not_awaited()


async def test_set_failure_swallows_error(redis_mock):
    redis_mock.get.return_value = None
    redis_mock.setex.side_effect = aioredis.RedisError("boom")
    fetcher = AsyncMock(return_value={"v": 2})

    result = await cache_get_or_set(redis_mock, "k", 30, fetcher)

    assert result == {"v": 2}
    fetcher.assert_awaited_once()
    redis_mock.setex.assert_awaited_once()


async def test_malformed_cached_json_falls_back_to_fetcher(redis_mock):
    redis_mock.get.return_value = "{not valid json"
    fetcher = AsyncMock(return_value={"fresh": True})

    result = await cache_get_or_set(redis_mock, "k", 30, fetcher)

    assert result == {"fresh": True}
    fetcher.assert_awaited_once()
    redis_mock.setex.assert_awaited_once_with("k", 30, json.dumps({"fresh": True}, default=str))


async def test_second_call_uses_cache(redis_mock):
    fetcher = AsyncMock(return_value={"v": "first"})
    redis_mock.get.side_effect = [None, json.dumps({"v": "first"})]

    first = await cache_get_or_set(redis_mock, "k", 30, fetcher)
    second = await cache_get_or_set(redis_mock, "k", 30, fetcher)

    assert first == {"v": "first"}
    assert second == {"v": "first"}
    fetcher.assert_awaited_once()
    redis_mock.setex.assert_awaited_once()


async def test_cache_invalidate_empty_list_is_no_op(redis_mock):
    await cache_invalidate(redis_mock, [])

    redis_mock.delete.assert_not_awaited()


async def test_cache_invalidate_calls_delete_with_all_keys(redis_mock):
    await cache_invalidate(redis_mock, ["a", "b", "c"])

    redis_mock.delete.assert_awaited_once_with("a", "b", "c")


async def test_cache_invalidate_swallows_redis_error(redis_mock):
    redis_mock.delete.side_effect = aioredis.RedisError("boom")

    await cache_invalidate(redis_mock, ["k"])

    redis_mock.delete.assert_awaited_once_with("k")
