import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.dependencies.portfolio import AlpacaAccountContext
from app.services.portfolio import HOLDINGS_TTL, PortfolioService


@pytest.fixture
def alpaca():
    svc = AsyncMock()
    svc.get_trading_account = AsyncMock()
    svc.list_positions = AsyncMock()
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


def _account(**overrides) -> dict:
    base = {
        "cash": "1500.00",
        "currency": "USD",
    }
    base.update(overrides)
    return base


def _position(symbol: str, market_value: str, **overrides) -> dict:
    base = {
        "symbol": symbol,
        "qty": "1",
        "avg_entry_price": "100.00",
        "current_price": "100.00",
        "market_value": market_value,
        "cost_basis": "100.00",
        "unrealized_pl": "0.00",
        "unrealized_plpc": "0.0000",
        "lastday_price": "100.00",
        "change_today": "0.0000",
    }
    base.update(overrides)
    return base


class TestHoldingsHappyPath:
    async def test_two_positions_sorted_descending_by_market_value(
        self, service, alpaca, redis
    ):
        alpaca.get_trading_account.return_value = _account()
        alpaca.list_positions.return_value = [
            _position("AAPL", "200.00"),
            _position("TSLA", "1500.00"),
        ]

        with patch(
            "app.services.portfolio.AssetRepository.get_names_by_symbols",
            new_callable=AsyncMock,
            return_value={"AAPL": "Apple Inc.", "TSLA": "Tesla, Inc."},
        ):
            response = await service.get_holdings(_ctx())

        dumped = response.model_dump(mode="json")

        assert dumped["account_status"] == "ACTIVE"
        assert dumped["currency"] == "USD"
        assert dumped["cash"] == "1500.00"
        assert dumped["total_market_value"] == "1700.00"
        symbols = [p["symbol"] for p in dumped["positions"]]
        assert symbols == ["TSLA", "AAPL"]
        assert dumped["positions"][0]["name"] == "Tesla, Inc."
        assert dumped["positions"][1]["name"] == "Apple Inc."

        redis.setex.assert_awaited_once()
        args, _ = redis.setex.call_args
        key, ttl, _payload = args
        assert key == f"portfolio:holdings:{_ctx().user_id}"
        assert ttl == HOLDINGS_TTL

    async def test_unknown_symbol_falls_back_to_symbol_as_name(
        self, service, alpaca
    ):
        alpaca.get_trading_account.return_value = _account()
        alpaca.list_positions.return_value = [_position("XYZ", "50.00")]

        with patch(
            "app.services.portfolio.AssetRepository.get_names_by_symbols",
            new_callable=AsyncMock,
            return_value={},  # no name in DB
        ):
            response = await service.get_holdings(_ctx())

        dumped = response.model_dump(mode="json")
        assert dumped["positions"][0]["name"] == "XYZ"


class TestHoldingsTotals:
    async def test_total_market_value_sums_positions_excluding_cash(
        self, service, alpaca
    ):
        alpaca.get_trading_account.return_value = _account(cash="9999.99")
        alpaca.list_positions.return_value = [
            _position("AAA", "100.00"),
            _position("BBB", "200.00"),
            _position("CCC", "50.50"),
        ]

        with patch(
            "app.services.portfolio.AssetRepository.get_names_by_symbols",
            new_callable=AsyncMock,
            return_value={},
        ):
            response = await service.get_holdings(_ctx())

        dumped = response.model_dump(mode="json")
        assert dumped["total_market_value"] == "350.50"
        assert dumped["cash"] == "9999.99"

    async def test_empty_positions_returns_empty_list_with_cash(
        self, service, alpaca
    ):
        alpaca.get_trading_account.return_value = _account(cash="500.00")
        alpaca.list_positions.return_value = []

        with patch(
            "app.services.portfolio.AssetRepository.get_names_by_symbols",
            new_callable=AsyncMock,
            return_value={},
        ) as get_names:
            response = await service.get_holdings(_ctx())

        dumped = response.model_dump(mode="json")
        assert dumped["positions"] == []
        assert dumped["total_market_value"] == "0.00"
        assert dumped["cash"] == "500.00"
        # Empty symbol list short-circuits the repo call.
        get_names.assert_awaited_once_with(service._db, [])


class TestHoldingsChangeToday:
    async def test_positive_change_today_is_position_level(self, service, alpaca):
        # 100 shares moved $10 each = $1000 position-level today.
        alpaca.get_trading_account.return_value = _account()
        alpaca.list_positions.return_value = [
            _position(
                "TSLA",
                "11000.00",
                qty="100",
                current_price="110.00",
                lastday_price="100.00",
                change_today="0.10",
            ),
        ]

        with patch(
            "app.services.portfolio.AssetRepository.get_names_by_symbols",
            new_callable=AsyncMock,
            return_value={},
        ):
            response = await service.get_holdings(_ctx())

        dumped = response.model_dump(mode="json")
        assert dumped["positions"][0]["change_today"] == "1000.00"
        assert dumped["positions"][0]["change_today_percent"] == "0.1000"

    async def test_negative_change_today_is_position_level(self, service, alpaca):
        alpaca.get_trading_account.return_value = _account()
        alpaca.list_positions.return_value = [
            _position(
                "AMD",
                "9000.00",
                qty="100",
                current_price="90.00",
                lastday_price="100.00",
                change_today="-0.10",
            ),
        ]

        with patch(
            "app.services.portfolio.AssetRepository.get_names_by_symbols",
            new_callable=AsyncMock,
            return_value={},
        ):
            response = await service.get_holdings(_ctx())

        dumped = response.model_dump(mode="json")
        assert dumped["positions"][0]["change_today"] == "-1000.00"
        assert dumped["positions"][0]["change_today_percent"] == "-0.1000"

    async def test_fractional_qty_scales_change_today(self, service, alpaca):
        # 0.5 shares × $10 move = $5.00 position-level.
        alpaca.get_trading_account.return_value = _account()
        alpaca.list_positions.return_value = [
            _position(
                "AAPL",
                "55.00",
                qty="0.5",
                current_price="110.00",
                lastday_price="100.00",
                change_today="0.10",
            ),
        ]

        with patch(
            "app.services.portfolio.AssetRepository.get_names_by_symbols",
            new_callable=AsyncMock,
            return_value={},
        ):
            response = await service.get_holdings(_ctx())

        dumped = response.model_dump(mode="json")
        assert dumped["positions"][0]["change_today"] == "5.00"
        assert dumped["positions"][0]["change_today_percent"] == "0.1000"

    async def test_missing_lastday_price_zeros_both_fields(self, service, alpaca):
        # New listing with no prior trading day. Both $ and % must zero
        # together — the response must never pair $0.00 with a non-zero %.
        alpaca.get_trading_account.return_value = _account()
        position = _position(
            "NEW",
            "100.00",
            current_price="100.00",
            change_today="0.0084",  # stale residual percent from Alpaca
        )
        position.pop("lastday_price")
        alpaca.list_positions.return_value = [position]

        with patch(
            "app.services.portfolio.AssetRepository.get_names_by_symbols",
            new_callable=AsyncMock,
            return_value={},
        ):
            response = await service.get_holdings(_ctx())

        dumped = response.model_dump(mode="json")
        assert dumped["positions"][0]["change_today"] == "0.00"
        assert dumped["positions"][0]["change_today_percent"] == "0.0000"


class TestHoldingsFractionalQty:
    async def test_fractional_qty_survives_serialization(self, service, alpaca):
        alpaca.get_trading_account.return_value = _account()
        alpaca.list_positions.return_value = [
            _position("AAPL", "12.34", qty="0.125", avg_entry_price="98.72"),
        ]

        with patch(
            "app.services.portfolio.AssetRepository.get_names_by_symbols",
            new_callable=AsyncMock,
            return_value={"AAPL": "Apple Inc."},
        ):
            response = await service.get_holdings(_ctx())

        dumped = response.model_dump(mode="json")
        assert dumped["positions"][0]["qty"] == "0.125"


class TestHoldingsConcurrency:
    async def test_account_and_positions_are_both_fetched(
        self, service, alpaca
    ):
        alpaca.get_trading_account.return_value = _account()
        alpaca.list_positions.return_value = []

        with patch(
            "app.services.portfolio.AssetRepository.get_names_by_symbols",
            new_callable=AsyncMock,
            return_value={},
        ):
            await service.get_holdings(_ctx())

        # Both calls must have happened — `asyncio.gather` fans them out
        # concurrently. We can't observe the parallelism directly in a
        # mock, but we can verify both were awaited with the right args.
        alpaca.get_trading_account.assert_awaited_once_with("alp_acc_1")
        alpaca.list_positions.assert_awaited_once_with("alp_acc_1")


class TestHoldingsCaching:
    async def test_cache_hit_skips_alpaca_and_db(
        self, service, alpaca, redis, db
    ):
        cached_payload = {
            "account_status": "ACTIVE",
            "currency": "USD",
            "cash": "100.00",
            "total_market_value": "200.00",
            "positions": [
                {
                    "symbol": "AAPL",
                    "name": "Apple Inc.",
                    "qty": "1",
                    "avg_entry_price": "150.00",
                    "current_price": "200.00",
                    "market_value": "200.00",
                    "cost_basis": "150.00",
                    "unrealized_pl": "50.00",
                    "unrealized_plpc": "0.3333",
                    "change_today": "5.00",
                    "change_today_percent": "0.0257",
                }
            ],
        }
        redis.get.return_value = json.dumps(cached_payload)

        with patch(
            "app.services.portfolio.AssetRepository.get_names_by_symbols",
            new_callable=AsyncMock,
        ) as get_names:
            response = await service.get_holdings(_ctx())

        assert response.model_dump(mode="json") == cached_payload
        alpaca.get_trading_account.assert_not_awaited()
        alpaca.list_positions.assert_not_awaited()
        get_names.assert_not_awaited()
        redis.setex.assert_not_awaited()
