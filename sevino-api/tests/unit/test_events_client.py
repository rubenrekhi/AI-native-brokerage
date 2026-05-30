"""Unit tests for the Radar EventsClient (cached FMP calendar wrapper)."""

import json
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
import redis.asyncio as aioredis

from app.services.radar_job.events_client import (
    DEFAULT_WINDOW_DAYS,
    EVENTS_CACHE_TTL_SECONDS,
    EventsClient,
)

EARNINGS_ROWS = [
    {"symbol": "AAPL", "date": "2026-07-30", "epsEstimated": 1.42},
    {"symbol": "MSFT", "date": "2026-07-29", "epsEstimated": 3.1},
]
DIVIDEND_ROWS = [
    {"symbol": "AAPL", "date": "2026-08-10", "dividend": 0.24},
]


@pytest.fixture
def redis_mock():
    mock = AsyncMock()
    mock.get = AsyncMock(return_value=None)
    mock.setex = AsyncMock()
    return mock


@pytest.fixture
def fmp_mock():
    mock = MagicMock()
    mock.earnings_calendar = AsyncMock(return_value=EARNINGS_ROWS)
    mock.dividend_calendar = AsyncMock(return_value=DIVIDEND_ROWS)
    return mock


@pytest.fixture
def client(fmp_mock, redis_mock):
    return EventsClient(fmp=fmp_mock, redis=redis_mock)


def _window(days_ahead: int) -> tuple[date, date]:
    today = date.today()
    return today, today + timedelta(days=days_ahead)


class TestUpcomingEarnings:
    async def test_miss_calls_fmp_and_caches(self, client, fmp_mock, redis_mock):
        from_date, to_date = _window(DEFAULT_WINDOW_DAYS)
        expected_key = (
            f"radar:events:earnings:{from_date.isoformat()}:{to_date.isoformat()}"
        )

        result = await client.upcoming_earnings()

        assert result == EARNINGS_ROWS
        fmp_mock.earnings_calendar.assert_awaited_once_with(from_date, to_date)
        redis_mock.setex.assert_awaited_once_with(
            expected_key,
            EVENTS_CACHE_TTL_SECONDS,
            json.dumps(EARNINGS_ROWS, default=str),
        )

    async def test_hit_returns_cached_without_fmp(
        self, client, fmp_mock, redis_mock
    ):
        redis_mock.get.return_value = json.dumps(EARNINGS_ROWS)

        result = await client.upcoming_earnings()

        assert result == EARNINGS_ROWS
        fmp_mock.earnings_calendar.assert_not_awaited()
        redis_mock.setex.assert_not_awaited()

    async def test_redis_down_falls_back_to_direct_fmp(
        self, client, fmp_mock, redis_mock
    ):
        redis_mock.get.side_effect = aioredis.RedisError("down")

        result = await client.upcoming_earnings()

        assert result == EARNINGS_ROWS
        fmp_mock.earnings_calendar.assert_awaited_once()
        redis_mock.setex.assert_not_awaited()

    async def test_custom_window_widens_date_range(
        self, client, fmp_mock
    ):
        from_date, to_date = _window(30)

        await client.upcoming_earnings(days_ahead=30)

        fmp_mock.earnings_calendar.assert_awaited_once_with(from_date, to_date)


class TestUpcomingDividends:
    async def test_miss_uses_dividend_method_and_key(
        self, client, fmp_mock, redis_mock
    ):
        from_date, to_date = _window(DEFAULT_WINDOW_DAYS)
        expected_key = (
            f"radar:events:dividends:{from_date.isoformat()}:{to_date.isoformat()}"
        )

        result = await client.upcoming_dividends()

        assert result == DIVIDEND_ROWS
        fmp_mock.dividend_calendar.assert_awaited_once_with(from_date, to_date)
        fmp_mock.earnings_calendar.assert_not_awaited()
        redis_mock.setex.assert_awaited_once_with(
            expected_key,
            EVENTS_CACHE_TTL_SECONDS,
            json.dumps(DIVIDEND_ROWS, default=str),
        )

    async def test_hit_returns_cached_without_fmp(
        self, client, fmp_mock, redis_mock
    ):
        redis_mock.get.return_value = json.dumps(DIVIDEND_ROWS)

        result = await client.upcoming_dividends()

        assert result == DIVIDEND_ROWS
        fmp_mock.dividend_calendar.assert_not_awaited()
