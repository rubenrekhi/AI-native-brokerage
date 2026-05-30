"""Unit tests for the FMP earnings/dividend calendar wrappers."""

from datetime import date

import httpx

from app.services.fmp import FmpClient


def _make_client(handler) -> FmpClient:
    return FmpClient(
        api_key="test-api-key",
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler), timeout=30.0
        ),
    )


EARNINGS_ROWS = [
    {
        "symbol": "AAPL",
        "date": "2026-07-30",
        "epsActual": None,
        "epsEstimated": 1.42,
        "revenueActual": None,
        "revenueEstimated": 90_000_000_000,
        "lastUpdated": "2026-05-01",
    },
    {
        "symbol": "MSFT",
        "date": "2026-07-29",
        "epsActual": None,
        "epsEstimated": 3.1,
        "revenueActual": None,
        "revenueEstimated": 64_000_000_000,
        "lastUpdated": "2026-05-01",
    },
]

DIVIDEND_ROWS = [
    {
        "symbol": "AAPL",
        "date": "2026-08-10",
        "recordDate": "2026-08-11",
        "paymentDate": "2026-08-15",
        "declarationDate": "2026-07-30",
        "adjDividend": 0.24,
        "dividend": 0.24,
        "yield": 0.0044,
        "frequency": "Quarterly",
    }
]


class TestEarningsCalendar:
    async def test_hits_path_with_from_and_to(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json=EARNINGS_ROWS)

        client = _make_client(handler)
        result = await client.earnings_calendar(
            date(2026, 7, 1), date(2026, 7, 31)
        )

        assert captured["path"] == "/stable/earnings-calendar"
        assert captured["params"]["from"] == "2026-07-01"
        assert captured["params"]["to"] == "2026-07-31"
        assert captured["params"]["apikey"] == "test-api-key"

    async def test_returns_raw_rows(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=EARNINGS_ROWS)

        client = _make_client(handler)
        result = await client.earnings_calendar(
            date(2026, 7, 1), date(2026, 7, 31)
        )

        assert result == EARNINGS_ROWS

    async def test_empty_window_returns_empty_list(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[])

        client = _make_client(handler)
        result = await client.earnings_calendar(
            date(2026, 7, 1), date(2026, 7, 1)
        )

        assert result == []


class TestDividendCalendar:
    async def test_hits_path_with_from_and_to(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json=DIVIDEND_ROWS)

        client = _make_client(handler)
        await client.dividend_calendar(date(2026, 8, 1), date(2026, 8, 31))

        assert captured["path"] == "/stable/dividends-calendar"
        assert captured["params"]["from"] == "2026-08-01"
        assert captured["params"]["to"] == "2026-08-31"

    async def test_returns_raw_rows(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=DIVIDEND_ROWS)

        client = _make_client(handler)
        result = await client.dividend_calendar(
            date(2026, 8, 1), date(2026, 8, 31)
        )

        assert result == DIVIDEND_ROWS

    async def test_empty_window_returns_empty_list(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[])

        client = _make_client(handler)
        result = await client.dividend_calendar(
            date(2026, 8, 1), date(2026, 8, 1)
        )

        assert result == []
