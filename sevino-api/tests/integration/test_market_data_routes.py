"""Integration tests for /v1/market-data/* routes.

Mounts the full app, uses the `authenticated_client` fixture (mocked auth +
mocked DB), and stubs `app.state.market_data` so handlers never reach FMP,
Alpaca, or Redis.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.exceptions import MarketDataError, MarketDataInvalidInputError
from app.main import app

FIXTURES = Path(__file__).parent.parent / "fixtures" / "mock_responses"


def _load(name: str) -> dict:
    with (FIXTURES / name).open() as f:
        return json.load(f)


@pytest.fixture
def market_data_mock():
    svc = AsyncMock()
    svc.get_stock_info.return_value = _load("market_data_stock_info.json")
    svc.get_batch_quotes.return_value = _load("market_data_batch_quotes.json")
    svc.get_chart.return_value = _load("market_data_chart.json")
    svc.get_market_status.return_value = _load("market_data_market_status.json")
    return svc


@pytest.fixture(autouse=True)
def patch_market_data_state(monkeypatch, market_data_mock):
    """Replace `app.state.market_data` for the duration of each test."""
    monkeypatch.setattr(app.state, "market_data", market_data_mock, raising=False)


class TestGetStockInfoRoute:
    async def test_200_returns_stock_info(
        self, authenticated_client, market_data_mock
    ):
        response = await authenticated_client.get("/v1/market-data/stocks/AAPL")

        assert response.status_code == 200
        body = response.json()
        assert body["quote"]["symbol"] == "AAPL"
        assert body["profile"]["name"] == "Apple Inc."
        assert body["ratios"]["roe"] == "1.50"
        assert body["financials"]["revenue"] == "400000000000"
        assert body["financials"]["annual_trend"][0]["fiscal_year"] == "2025"
        assert body["valuation"]["pe"] == "28.50"
        assert body["valuation"]["sector_pe"] == "50.00"
        assert body["valuation"]["pe_vs_sector"] == "-0.43"
        assert body["valuation"]["valuation_history"][0]["fiscal_year"] == "2025"
        assert body["earnings"]["next_period_end"] == "2026-09-28"
        assert body["earnings"]["quarterly"][0]["eps_surprise_pct"] == "0.0308"
        assert body["earnings"]["avg_post_earnings_move_pct"] == "0.0365"
        assert body["sector_context"]["sector_vs_market_pct"] == "1.0589"
        assert body["sector_context"]["peers"][0]["symbol"] == "MSFT"
        assert body["sector_context"]["rank_by_market_cap"] == 2
        assert body["analyst"]["target_consensus"] == "200.00"
        market_data_mock.get_stock_info.assert_awaited_once_with("AAPL")

    async def test_invalid_symbol_returns_422(
        self, authenticated_client, market_data_mock
    ):
        market_data_mock.get_stock_info.side_effect = MarketDataInvalidInputError(
            "Invalid symbol", symbol="!!!"
        )
        response = await authenticated_client.get("/v1/market-data/stocks/!!!")
        assert response.status_code == 422
        assert response.json()["code"] == "MARKET_DATA_INVALID_INPUT"

    async def test_unknown_symbol_returns_404(
        self, authenticated_client, market_data_mock
    ):
        market_data_mock.get_stock_info.side_effect = MarketDataError(
            "Quote not found", symbol="ZZZZ"
        )
        response = await authenticated_client.get("/v1/market-data/stocks/ZZZZ")
        assert response.status_code == 404
        assert response.json()["code"] == "MARKET_DATA_NOT_FOUND"

    async def test_requires_auth(self, client):
        response = await client.get("/v1/market-data/stocks/AAPL")
        assert response.status_code == 401


class TestGetChartRoute:
    async def test_200_default_timeframe_is_1M(
        self, authenticated_client, market_data_mock
    ):
        response = await authenticated_client.get(
            "/v1/market-data/stocks/AAPL/chart"
        )

        assert response.status_code == 200
        body = response.json()
        assert body["symbol"] == "AAPL"
        assert body["timeframe"] == "1M"
        assert len(body["bars"]) == 1
        market_data_mock.get_chart.assert_awaited_once_with("AAPL", "1M")

    async def test_200_with_explicit_timeframe(
        self, authenticated_client, market_data_mock
    ):
        market_data_mock.get_chart.return_value = {
            **market_data_mock.get_chart.return_value,
            "timeframe": "1Y",
        }
        response = await authenticated_client.get(
            "/v1/market-data/stocks/AAPL/chart?timeframe=1Y"
        )

        assert response.status_code == 200
        assert response.json()["timeframe"] == "1Y"
        market_data_mock.get_chart.assert_awaited_once_with("AAPL", "1Y")

    async def test_invalid_timeframe_returns_422(self, authenticated_client):
        response = await authenticated_client.get(
            "/v1/market-data/stocks/AAPL/chart?timeframe=BOGUS"
        )
        assert response.status_code == 422

    async def test_requires_auth(self, client):
        response = await client.get("/v1/market-data/stocks/AAPL/chart")
        assert response.status_code == 401


class TestBatchQuotesRoute:
    async def test_200_returns_batch_quotes(
        self, authenticated_client, market_data_mock
    ):
        response = await authenticated_client.get(
            "/v1/market-data/stocks/batch?symbols=AAPL,MSFT"
        )

        assert response.status_code == 200
        body = response.json()
        assert body["quotes"][0]["symbol"] == "AAPL"
        market_data_mock.get_batch_quotes.assert_awaited_once_with(["AAPL", "MSFT"])

    async def test_normalizes_and_caps_symbols(
        self, authenticated_client, market_data_mock
    ):
        # 25 symbols sent → service should only see the first 20, uppercased.
        symbols = ",".join(f"sym{i}" for i in range(25))
        await authenticated_client.get(
            f"/v1/market-data/stocks/batch?symbols={symbols}"
        )

        sent = market_data_mock.get_batch_quotes.call_args.args[0]
        assert len(sent) == 20
        assert all(s == s.upper() for s in sent)

    async def test_batch_route_not_shadowed_by_symbol_route(
        self, authenticated_client, market_data_mock
    ):
        # If route ordering were wrong, FastAPI would dispatch to /stocks/{symbol}
        # with symbol="batch" and never invoke get_batch_quotes.
        await authenticated_client.get(
            "/v1/market-data/stocks/batch?symbols=AAPL"
        )

        market_data_mock.get_batch_quotes.assert_awaited_once()
        market_data_mock.get_stock_info.assert_not_called()

    async def test_missing_symbols_query_returns_422(self, authenticated_client):
        response = await authenticated_client.get("/v1/market-data/stocks/batch")
        assert response.status_code == 422

    async def test_requires_auth(self, client):
        response = await client.get(
            "/v1/market-data/stocks/batch?symbols=AAPL"
        )
        assert response.status_code == 401


class TestMarketStatusRoute:
    async def test_200_returns_market_status(
        self, authenticated_client, market_data_mock
    ):
        response = await authenticated_client.get("/v1/market-data/market/status")

        assert response.status_code == 200
        body = response.json()
        assert body["is_open"] is True
        assert body["next_open"] == "2026-04-29T13:30:00Z"
        market_data_mock.get_market_status.assert_awaited_once()

    async def test_requires_auth(self, client):
        response = await client.get("/v1/market-data/market/status")
        assert response.status_code == 401


class TestServiceUnavailable:
    async def test_503_when_market_data_is_none(
        self, authenticated_client, monkeypatch
    ):
        monkeypatch.setattr(app.state, "market_data", None, raising=False)

        response = await authenticated_client.get("/v1/market-data/stocks/AAPL")

        assert response.status_code == 503
        assert response.json()["code"] == "MARKET_DATA_UNAVAILABLE"
