import json
import uuid
from unittest.mock import AsyncMock

import pytest

from app.dependencies.portfolio import AlpacaAccountContext
from app.services.portfolio import PortfolioService, SNAPSHOT_TTL


@pytest.fixture
def alpaca():
    svc = AsyncMock()
    svc.get_trading_account = AsyncMock()
    return svc


@pytest.fixture
def redis():
    mock = AsyncMock()
    mock.get = AsyncMock(return_value=None)
    mock.setex = AsyncMock()
    return mock


@pytest.fixture
def service(alpaca, redis):
    return PortfolioService(alpaca=alpaca, redis=redis)


def _ctx(status: str = "ACTIVE") -> AlpacaAccountContext:
    return AlpacaAccountContext(
        user_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        alpaca_account_id="alp_acc_1",
        account_status=status,
    )


class TestSnapshotHappyPath:
    async def test_active_account_builds_response_from_alpaca(
        self, service, alpaca, redis
    ):
        alpaca.get_trading_account.return_value = {
            "equity": "1084.92",
            "last_equity": "852.10",
            "cash": "40291.92",
            "buying_power": "40291.92",
            "currency": "USD",
        }

        snapshot = await service.get_snapshot(_ctx())
        dumped = snapshot.model_dump(mode="json")

        assert dumped["account_status"] == "ACTIVE"
        assert dumped["currency"] == "USD"
        assert dumped["equity"] == "1084.92"
        assert dumped["last_equity"] == "852.10"
        assert dumped["cash"] == "40291.92"
        assert dumped["buying_power"] == "40291.92"
        assert dumped["daily_change_abs"] == "232.82"
        assert dumped["daily_change_pct"] == "0.2732"

        alpaca.get_trading_account.assert_awaited_once_with("alp_acc_1")
        redis.setex.assert_awaited_once()
        args, _ = redis.setex.call_args
        key, ttl, _payload = args
        assert key == f"portfolio:snapshot:{_ctx().user_id}"
        assert ttl == SNAPSHOT_TTL


class TestSnapshotEdgeCases:
    async def test_negative_daily_change_preserves_sign(
        self, service, alpaca
    ):
        alpaca.get_trading_account.return_value = {
            "equity": "800.00",
            "last_equity": "1000.00",
            "cash": "50.00",
            "buying_power": "50.00",
            "currency": "USD",
        }

        snapshot = await service.get_snapshot(_ctx())
        dumped = snapshot.model_dump(mode="json")

        assert dumped["daily_change_abs"] == "-200.00"
        assert dumped["daily_change_pct"] == "-0.2000"

    async def test_zero_last_equity_returns_zero_pct_no_crash(
        self, service, alpaca
    ):
        alpaca.get_trading_account.return_value = {
            "equity": "0",
            "last_equity": "0",
            "cash": "0",
            "buying_power": "0",
            "currency": "USD",
        }

        snapshot = await service.get_snapshot(_ctx())
        dumped = snapshot.model_dump(mode="json")

        assert dumped["daily_change_abs"] == "0.00"
        assert dumped["daily_change_pct"] == "0.0000"

    async def test_null_money_fields_default_to_zero(self, service, alpaca):
        alpaca.get_trading_account.return_value = {
            "equity": None,
            "last_equity": None,
            "cash": None,
            "buying_power": None,
        }

        snapshot = await service.get_snapshot(_ctx())
        dumped = snapshot.model_dump(mode="json")

        assert dumped["equity"] == "0.00"
        assert dumped["last_equity"] == "0.00"
        assert dumped["cash"] == "0.00"
        assert dumped["buying_power"] == "0.00"
        assert dumped["currency"] == "USD"  # default when missing


class TestSnapshotCaching:
    async def test_cache_hit_skips_alpaca_call(self, service, alpaca, redis):
        cached_payload = {
            "account_status": "ACTIVE",
            "currency": "USD",
            "equity": "500.00",
            "last_equity": "400.00",
            "cash": "10.00",
            "buying_power": "10.00",
            "daily_change_abs": "100.00",
            "daily_change_pct": "0.2500",
        }
        redis.get.return_value = json.dumps(cached_payload)

        snapshot = await service.get_snapshot(_ctx())

        assert snapshot.model_dump(mode="json") == cached_payload
        alpaca.get_trading_account.assert_not_awaited()
        redis.setex.assert_not_awaited()
