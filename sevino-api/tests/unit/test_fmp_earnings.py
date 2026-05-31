import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from app.exceptions import MarketDataError
from app.schemas.fmp import EarningsCalendarItem, HistoricalEarningsItem
from app.services.fmp import FmpClient

FIXTURES = Path(__file__).parent.parent / "fixtures" / "mock_responses"


def _load(name: str) -> list[dict]:
    with (FIXTURES / name).open() as f:
        return json.load(f)


def _make_client(handler) -> FmpClient:
    return FmpClient(
        api_key="test-api-key",
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler), timeout=30.0
        ),
    )


class TestGetEarningsCalendar:
    async def test_hits_v3_path_with_from_and_to(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json=_load("fmp_earnings_calendar.json"))

        client = _make_client(handler)
        await client.get_earnings_calendar(date(2026, 7, 1), date(2026, 7, 31))

        assert captured["path"] == "/api/v3/earning_calendar"
        assert captured["params"]["from"] == "2026-07-01"
        assert captured["params"]["to"] == "2026-07-31"
        assert captured["params"]["apikey"] == "test-api-key"

    async def test_returns_typed_decimal_rows(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_load("fmp_earnings_calendar.json"))

        client = _make_client(handler)
        result = await client.get_earnings_calendar(
            date(2026, 7, 1), date(2026, 7, 31)
        )

        assert all(isinstance(item, EarningsCalendarItem) for item in result)
        assert [item.symbol for item in result] == ["AAPL", "MSFT"]
        assert result[0].symbol == "AAPL"
        assert result[0].reported_date == date(2026, 7, 30)
        assert result[0].eps_actual is None
        assert result[0].eps_estimate == Decimal("1.42")
        assert result[0].revenue_actual is None
        assert result[0].revenue_estimate == Decimal("90000000000")
        assert isinstance(result[0].eps_estimate, Decimal)
        assert isinstance(result[0].revenue_estimate, Decimal)
        assert result[0].last_updated == date(2026, 5, 1)
        assert result[0].model_dump(mode="json")["eps_estimate"] == "1.42"
        assert result[0].model_dump(mode="json")["revenue_estimate"] == (
            "90000000000.00"
        )

    async def test_empty_window_returns_empty_list(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[])

        client = _make_client(handler)
        result = await client.get_earnings_calendar(
            date(2026, 7, 1), date(2026, 7, 1)
        )

        assert result == []

    async def test_drops_out_of_window_rows_from_provider(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_load("fmp_earnings_calendar.json"))

        client = _make_client(handler)
        result = await client.get_earnings_calendar(
            date(2026, 7, 1), date(2026, 7, 31)
        )

        assert [item.symbol for item in result] == ["AAPL", "MSFT"]

    async def test_malformed_rows_are_skipped_not_fatal(self):
        rows = [
            {
                "symbol": "BAD",
                "date": "",
                "epsEstimated": "not-a-number",
            },
            {
                "symbol": "AAPL",
                "date": "2026-07-30",
                "epsEstimated": 1.42,
                "revenueEstimated": 90000000000,
                "fiscalDateEnding": "2026-06-30",
                "lastUpdated": "2026-05-01",
            },
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=rows)

        client = _make_client(handler)
        result = await client.get_earnings_calendar(
            date(2026, 7, 1), date(2026, 7, 31)
        )

        assert [item.symbol for item in result] == ["AAPL"]

    async def test_blank_optional_dates_validate_as_none(self):
        rows = [
            {
                "symbol": "AAPL",
                "date": "2026-07-30",
                "epsEstimated": 1.42,
                "revenueEstimated": 90000000000,
                "fiscalDateEnding": "",
                "lastUpdated": "",
            },
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=rows)

        client = _make_client(handler)
        result = await client.get_earnings_calendar(
            date(2026, 7, 1), date(2026, 7, 31)
        )

        assert result[0].fiscal_date_ending is None
        assert result[0].last_updated is None


class TestGetHistoricalEarnings:
    async def test_hits_v3_historical_path(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json=_load("fmp_earnings_historical.json"))

        client = _make_client(handler)
        await client.get_historical_earnings("AAPL")

        assert captured["path"] == "/api/v3/historical/earning_calendar/AAPL"
        assert captured["params"]["apikey"] == "test-api-key"

    async def test_returns_most_recent_entries_newest_first(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_load("fmp_earnings_historical.json"))

        client = _make_client(handler)
        result = await client.get_historical_earnings("AAPL", limit=2)

        assert all(isinstance(item, HistoricalEarningsItem) for item in result)
        assert [item.reported_date for item in result] == [
            date(2026, 4, 30),
            date(2026, 1, 29),
        ]
        assert result[0].eps_actual == Decimal("1.65")
        assert result[0].eps_estimate == Decimal("1.62")
        assert result[0].revenue_actual == Decimal("95359000000")
        assert result[0].revenue_estimate == Decimal("94120000000")
        assert isinstance(result[0].eps_actual, Decimal)
        assert isinstance(result[0].eps_estimate, Decimal)
        assert isinstance(result[0].revenue_actual, Decimal)
        assert isinstance(result[0].revenue_estimate, Decimal)

    async def test_limit_at_or_below_zero_returns_empty_list_without_request(self):
        called = False

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal called
            called = True
            return httpx.Response(200, json=_load("fmp_earnings_historical.json"))

        client = _make_client(handler)
        result = await client.get_historical_earnings("AAPL", limit=0)

        assert result == []
        assert called is False

    async def test_402_maps_to_market_data_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(402, text="Premium Query Parameter")

        client = _make_client(handler)

        with pytest.raises(MarketDataError) as info:
            await client.get_historical_earnings("AAPL")

        assert info.value.symbol == "AAPL"
