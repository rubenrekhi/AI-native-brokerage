"""Unit tests for FMP news wrappers."""

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from app.exceptions import MarketDataUpstreamError
from app.services.fmp import FmpClient, GeneralNewsItem, StockNewsItem


FIXTURES = Path(__file__).parent.parent / "fixtures" / "mock_responses"


def _load(name: str):
    return json.loads((FIXTURES / name).read_text())


def _make_client(handler) -> FmpClient:
    return FmpClient(
        api_key="test-api-key",
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler), timeout=30.0
        ),
    )


class TestStockNews:
    async def test_hits_legacy_v3_path_with_tickers_from_and_limit(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json=_load("fmp_news_stock.json"))

        client = _make_client(handler)
        await client.get_stock_news(
            ["aapl", "MSFT"],
            datetime(2026, 5, 30, 0, 0, tzinfo=timezone.utc),
            limit=2,
        )

        assert captured["path"] == "/api/v3/stock_news"
        assert captured["params"]["tickers"] == "AAPL,MSFT"
        assert captured["params"]["from"] == "2026-05-30"
        assert captured["params"]["limit"] == "2"
        assert captured["params"]["apikey"] == "test-api-key"

    async def test_strips_stable_base_for_legacy_v3_path(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["path"] = request.url.path
            return httpx.Response(200, json=[])

        client = FmpClient(
            api_key="test-api-key",
            base_url="https://example.test/stable",
            client=httpx.AsyncClient(
                transport=httpx.MockTransport(handler), timeout=30.0
            ),
        )
        await client.get_stock_news(
            ["AAPL"],
            datetime(2026, 5, 30, 0, 0, tzinfo=timezone.utc),
        )

        assert captured["url"].startswith("https://example.test/api/v3/stock_news")
        assert captured["path"] == "/api/v3/stock_news"

    async def test_returns_typed_items_filtered_by_since_and_limit(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_load("fmp_news_stock.json"))

        client = _make_client(handler)
        result = await client.get_stock_news(
            ["AAPL", "MSFT"],
            datetime(2026, 5, 30, 0, 0, tzinfo=timezone.utc),
            limit=1,
        )

        assert len(result) == 1
        assert isinstance(result[0], StockNewsItem)
        assert result[0].symbol == "AAPL"
        assert result[0].headline == "Apple shares rise after product update"
        assert result[0].source == "Reuters"

    async def test_requests_headroom_for_intraday_since_before_filtering(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json=_load("fmp_news_stock.json"))

        client = _make_client(handler)
        result = await client.get_stock_news(
            ["AAPL", "MSFT"],
            datetime(2026, 5, 30, 13, 0, tzinfo=timezone.utc),
            limit=2,
        )

        assert captured["params"]["from"] == "2026-05-30"
        assert captured["params"]["limit"] == "100"
        assert [item.headline for item in result] == [
            "Apple shares rise after product update"
        ]

    async def test_skips_malformed_rows(self):
        rows = [
            _load("fmp_news_stock.json")[0],
            {
                "symbol": "MSFT",
                "publishedDate": "2026-05-30T12:00:00+00:00",
                "title": "Missing URL should not drop batch",
            },
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=rows)

        client = _make_client(handler)
        result = await client.get_stock_news(
            ["AAPL", "MSFT"],
            datetime(2026, 5, 30, 0, 0, tzinfo=timezone.utc),
            limit=2,
        )

        assert len(result) == 1
        assert result[0].headline == "Apple shares rise after product update"

    async def test_empty_symbols_returns_empty_list_without_request(self):
        called = False

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal called
            called = True
            return httpx.Response(200, json=_load("fmp_news_stock.json"))

        client = _make_client(handler)
        result = await client.get_stock_news(
            [],
            datetime(2026, 5, 30, 0, 0, tzinfo=timezone.utc),
        )

        assert result == []
        assert called is False

    async def test_non_positive_limit_returns_empty_list_without_request(self):
        called = False

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal called
            called = True
            return httpx.Response(200, json=_load("fmp_news_stock.json"))

        client = _make_client(handler)
        result = await client.get_stock_news(
            ["AAPL"],
            datetime(2026, 5, 30, 0, 0, tzinfo=timezone.utc),
            limit=0,
        )

        assert result == []
        assert called is False


class TestGeneralNews:
    async def test_hits_legacy_v4_path_with_from_and_limit(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json=_load("fmp_news_general.json"))

        client = _make_client(handler)
        await client.get_general_news(
            datetime(2026, 5, 30, 0, 0, tzinfo=timezone.utc),
            limit=2,
        )

        assert captured["path"] == "/api/v4/general_news"
        assert captured["params"]["from"] == "2026-05-30"
        assert captured["params"]["limit"] == "2"

    async def test_strips_stable_base_for_legacy_v4_path(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["path"] = request.url.path
            return httpx.Response(200, json=[])

        client = FmpClient(
            api_key="test-api-key",
            base_url="https://example.test/stable",
            client=httpx.AsyncClient(
                transport=httpx.MockTransport(handler), timeout=30.0
            ),
        )
        await client.get_general_news(
            datetime(2026, 5, 30, 0, 0, tzinfo=timezone.utc),
        )

        assert captured["url"].startswith("https://example.test/api/v4/general_news")
        assert captured["path"] == "/api/v4/general_news"

    async def test_returns_typed_items_filtered_by_since_and_limit(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_load("fmp_news_general.json"))

        client = _make_client(handler)
        result = await client.get_general_news(
            datetime(2026, 5, 30, 0, 0, tzinfo=timezone.utc),
            limit=2,
        )

        assert len(result) == 2
        assert all(isinstance(item, GeneralNewsItem) for item in result)
        assert result[0].headline == "Stocks climb as yields fall"
        assert result[1].image_url is None
        assert all(
            item.published_at.date().isoformat() == "2026-05-30"
            for item in result
        )

    async def test_empty_payload_returns_empty_list(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[])

        client = _make_client(handler)
        result = await client.get_general_news(
            datetime(2026, 5, 30, 0, 0, tzinfo=timezone.utc)
        )

        assert result == []

    async def test_non_positive_limit_returns_empty_list_without_request(self):
        called = False

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal called
            called = True
            return httpx.Response(200, json=_load("fmp_news_general.json"))

        client = _make_client(handler)
        result = await client.get_general_news(
            datetime(2026, 5, 30, 0, 0, tzinfo=timezone.utc),
            limit=0,
        )

        assert result == []
        assert called is False

    async def test_non_200_raises_existing_fmp_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, text="rate limited")

        client = _make_client(handler)
        with pytest.raises(MarketDataUpstreamError):
            await client.get_general_news(
                datetime(2026, 5, 30, 0, 0, tzinfo=timezone.utc)
            )
