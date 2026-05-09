import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.dependencies.portfolio import AlpacaAccountContext
from app.services.portfolio import (
    HISTORY_TTL,
    PortfolioRange,
    PortfolioService,
    _to_dt,
)


@pytest.fixture
def alpaca():
    svc = AsyncMock()
    svc.get_portfolio_history = AsyncMock()
    return svc


@pytest.fixture
def redis():
    mock = AsyncMock()
    mock.get = AsyncMock(return_value=None)
    mock.setex = AsyncMock()
    return mock


@pytest.fixture
def db():
    return AsyncMock()


@pytest.fixture
def service(alpaca, redis, db):
    return PortfolioService(alpaca=alpaca, redis=redis, db=db)


def _ctx(status: str = "ACTIVE") -> AlpacaAccountContext:
    return AlpacaAccountContext(
        user_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        alpaca_account_id="alp_acc_1",
        account_status=status,
    )


class TestHistoryHappyPath:
    async def test_builds_points_in_order_with_summary(
        self, service, alpaca, redis
    ):
        alpaca.get_portfolio_history.return_value = {
            "timestamp": [1700000000, 1700086400, 1700172800],
            "equity": [1000.00, 1100.00, 1250.00],
            "base_value": 1000.00,
            "timeframe": "1D",
        }

        response = await service.get_history(_ctx(), PortfolioRange.ONE_MONTH)
        dumped = response.model_dump(mode="json")

        assert dumped["range"] == "1M"
        assert dumped["timeframe"] == "1D"
        assert dumped["currency"] == "USD"
        assert dumped["base_value"] == "1000.00"
        assert dumped["end_value"] == "1250.00"
        assert dumped["gain_abs"] == "250.00"
        assert dumped["gain_pct"] == "0.2500"
        assert [p["v"] for p in dumped["points"]] == [
            "1000.00",
            "1100.00",
            "1250.00",
        ]

        redis.setex.assert_awaited_once()
        args, _ = redis.setex.call_args
        key, ttl, _payload = args
        assert key == f"portfolio:history:{_ctx().user_id}:1M"
        assert ttl == HISTORY_TTL


class TestHistoryFiltering:
    async def test_zero_equity_bars_dropped(self, service, alpaca):
        # Pre-market / no-trade bars commonly come back as 0.
        alpaca.get_portfolio_history.return_value = {
            "timestamp": [1700000000, 1700003600, 1700086400],
            "equity": [0, 0, 1100.00],
            "base_value": 1000.00,
            "timeframe": "5Min",
        }

        response = await service.get_history(_ctx(), PortfolioRange.ONE_DAY)
        dumped = response.model_dump(mode="json")

        assert len(dumped["points"]) == 1
        assert dumped["points"][0]["v"] == "1100.00"
        assert dumped["end_value"] == "1100.00"
        assert dumped["gain_abs"] == "100.00"

    async def test_null_equity_entries_dropped(self, service, alpaca):
        alpaca.get_portfolio_history.return_value = {
            "timestamp": [1700000000, 1700086400, 1700172800],
            "equity": [None, 1100.00, None],
            "base_value": 1000.00,
            "timeframe": "1D",
        }

        response = await service.get_history(_ctx(), PortfolioRange.ONE_WEEK)
        dumped = response.model_dump(mode="json")

        assert len(dumped["points"]) == 1
        assert dumped["points"][0]["v"] == "1100.00"


class TestHistoryEmptySeries:
    async def test_empty_arrays_zero_summary_no_crash(self, service, alpaca):
        alpaca.get_portfolio_history.return_value = {
            "timestamp": [],
            "equity": [],
            "base_value": 0,
            "timeframe": "1D",
        }

        response = await service.get_history(_ctx(), PortfolioRange.ONE_MONTH)
        dumped = response.model_dump(mode="json")

        assert dumped["points"] == []
        assert dumped["base_value"] == "0.00"
        assert dumped["end_value"] == "0.00"
        assert dumped["gain_abs"] == "0.00"
        assert dumped["gain_pct"] == "0.0000"

    async def test_missing_top_level_arrays_treated_as_empty(
        self, service, alpaca
    ):
        # Defensive: if Alpaca omits keys entirely, we shouldn't KeyError.
        alpaca.get_portfolio_history.return_value = {
            "base_value": 0,
            "timeframe": "",
        }

        response = await service.get_history(_ctx(), PortfolioRange.ALL)
        dumped = response.model_dump(mode="json")
        assert dumped["points"] == []
        assert dumped["timeframe"] == ""


class TestTimestampWidth:
    def test_seconds_and_milliseconds_resolve_to_same_utc(self):
        seconds = 1580826600
        millis = 1580826600000
        assert _to_dt(seconds) == _to_dt(millis)
        assert _to_dt(seconds) == datetime(
            2020, 2, 4, 14, 30, tzinfo=timezone.utc
        )


class TestHistoryCacheKeyIncludesRange:
    async def test_different_ranges_use_different_keys(
        self, service, alpaca, redis
    ):
        alpaca.get_portfolio_history.return_value = {
            "timestamp": [1700000000],
            "equity": [1000.00],
            "base_value": 1000.00,
            "timeframe": "1D",
        }

        await service.get_history(_ctx(), PortfolioRange.ONE_MONTH)
        await service.get_history(_ctx(), PortfolioRange.ONE_YEAR)

        keys = [call.args[0] for call in redis.setex.await_args_list]
        assert keys == [
            f"portfolio:history:{_ctx().user_id}:1M",
            f"portfolio:history:{_ctx().user_id}:1Y",
        ]


class TestHistoryCaching:
    async def test_cache_hit_skips_alpaca(self, service, alpaca, redis):
        cached_payload = {
            "range": "1M",
            "timeframe": "1D",
            "currency": "USD",
            "base_value": "1000.00",
            "end_value": "1250.00",
            "gain_abs": "250.00",
            "gain_pct": "0.2500",
            "points": [
                {"t": "2024-01-01T00:00:00Z", "v": "1000.00"},
                {"t": "2024-01-02T00:00:00Z", "v": "1250.00"},
            ],
        }
        redis.get.return_value = json.dumps(cached_payload)

        response = await service.get_history(_ctx(), PortfolioRange.ONE_MONTH)
        dumped = response.model_dump(mode="json")

        # Pydantic round-trips datetimes — compare on key fields only.
        assert dumped["range"] == "1M"
        assert dumped["base_value"] == "1000.00"
        assert dumped["end_value"] == "1250.00"
        assert len(dumped["points"]) == 2
        alpaca.get_portfolio_history.assert_not_awaited()
        redis.setex.assert_not_awaited()
