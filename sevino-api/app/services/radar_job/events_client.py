"""Cached read access to FMP's earnings/dividend calendars for Radar.

`EventsClient` wraps `FmpClient.earnings_calendar` / `dividend_calendar`
with a Redis cache. Calendars are universe-wide and don't change intraday,
so a single forward-window key (keyed only on the date range) serves every
user for a full day — the candidate sourcer (T3) hits this once per batch
run instead of FMP once per user.

Caching goes through `cache_get_or_set`, which degrades cleanly: a Redis
read error falls through to a direct FMP call, and a write error is
swallowed. The returned rows are raw FMP shapes; downstream code projects
them.
"""

from datetime import date, timedelta
from typing import Any

from redis.asyncio import Redis

from app.cache import cache_get_or_set
from app.services.fmp import FmpClient

EVENTS_CACHE_TTL_SECONDS = 86_400  # 24h — calendars are stable within a day
DEFAULT_WINDOW_DAYS = 14


class EventsClient:
    def __init__(self, *, fmp: FmpClient, redis: Redis) -> None:
        self._fmp = fmp
        self._redis = redis

    async def upcoming_earnings(
        self, days_ahead: int = DEFAULT_WINDOW_DAYS
    ) -> list[dict[str, Any]]:
        """Earnings events from today through `days_ahead` (inclusive)."""
        from_date, to_date = _window(days_ahead)
        key = f"radar:events:earnings:{from_date.isoformat()}:{to_date.isoformat()}"
        return await cache_get_or_set(
            self._redis,
            key,
            EVENTS_CACHE_TTL_SECONDS,
            lambda: self._fmp.earnings_calendar(from_date, to_date),
        )

    async def upcoming_dividends(
        self, days_ahead: int = DEFAULT_WINDOW_DAYS
    ) -> list[dict[str, Any]]:
        """Dividend events from today through `days_ahead` (inclusive)."""
        from_date, to_date = _window(days_ahead)
        key = f"radar:events:dividends:{from_date.isoformat()}:{to_date.isoformat()}"
        return await cache_get_or_set(
            self._redis,
            key,
            EVENTS_CACHE_TTL_SECONDS,
            lambda: self._fmp.dividend_calendar(from_date, to_date),
        )


def _window(days_ahead: int) -> tuple[date, date]:
    today = date.today()
    return today, today + timedelta(days=days_ahead)
