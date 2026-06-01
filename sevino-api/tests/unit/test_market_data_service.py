"""Unit tests for app.services.market_data.MarketDataService."""

import json
from collections.abc import Callable
from datetime import date, datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import Request

from app.exceptions import (
    MarketDataError,
    MarketDataInvalidInputError,
    MarketDataUnavailableError,
    MarketDataUpstreamError,
)
from app.services.alpaca_broker import (
    AlpacaBrokerError,
    AlpacaBrokerUnavailableError,
)
from app.services.fmp import FmpClient
from app.services.market_data import (
    MarketDataService,
    _market_today,
    get_market_data_service,
)


class FakeRedis:
    """In-memory Redis stand-in. Records every set call for TTL assertions."""

    def __init__(
        self, *, get_raises: Exception | None = None, set_raises: Exception | None = None
    ) -> None:
        self.store: dict[str, str] = {}
        self.set_calls: list[tuple[str, Any, int | None]] = []
        self.get_calls: list[str] = []
        self._get_raises = get_raises
        self._set_raises = set_raises

    async def get(self, key: str) -> str | None:
        self.get_calls.append(key)
        if self._get_raises is not None:
            raise self._get_raises
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.set_calls.append((key, value, ex))
        if self._set_raises is not None:
            raise self._set_raises
        self.store[key] = value


class FakeAlpacaBroker:
    """Stand-in for AlpacaBrokerService that returns a static token."""

    def __init__(
        self, *, token: str = "fake-token", raises: Exception | None = None
    ) -> None:
        self._token = token
        self._raises = raises
        self.calls = 0

    async def access_token(self) -> str:
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return self._token


def _service(
    *,
    fmp_handler: Callable[[httpx.Request], httpx.Response] | None = None,
    alpaca_handler: Callable[[httpx.Request], httpx.Response] | None = None,
    alpaca_broker: FakeAlpacaBroker | None = None,
    redis: FakeRedis | None = None,
    is_market_open: bool | None = True,
) -> tuple[MarketDataService, FakeRedis]:
    """Construct a MarketDataService with mock transports for FMP/Alpaca."""
    fake_redis = redis or FakeRedis()
    fmp = FmpClient(
        api_key="test-key",
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                fmp_handler or (lambda r: httpx.Response(200, json=[]))
            )
        ),
    )
    alpaca_client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            alpaca_handler or (lambda r: httpx.Response(200, json={}))
        )
    )
    service = MarketDataService(
        fmp=fmp,
        alpaca_broker=alpaca_broker or FakeAlpacaBroker(),
        redis=fake_redis,
        alpaca_data_url="https://data.sandbox.alpaca.markets",
        alpaca_broker_url="https://broker-api.sandbox.alpaca.markets",
        client=alpaca_client,
    )

    # Pre-populate market status cache so `_is_market_open()` doesn't need
    # to hit Alpaca in tests that don't care about market hours. Pass
    # `is_market_open=None` to leave the cache empty (forces the real path).
    if is_market_open is not None:
        fake_redis.store["market:status"] = json.dumps(
            {
                "is_open": is_market_open,
                "next_open": "2026-05-08T13:30:00Z",
                "next_close": "2026-05-07T20:00:00Z",
                "timestamp": "2026-05-07T15:00:00Z",
            }
        )

    return service, fake_redis


# ── _market_today ──────────────────────────────────────────


class TestMarketToday:
    @pytest.mark.parametrize(
        "utc_instant, expected",
        [
            # Late-evening US window where UTC has rolled to the next day but the
            # US trading day hasn't. Both DST states, since the fix relies on
            # ZoneInfo (not a fixed offset) staying correct year-round:
            # Summer (EDT, UTC-4): 01:30 UTC Jun 1 == 21:30 May 31 ET.
            (datetime(2026, 6, 1, 1, 30, tzinfo=timezone.utc), date(2026, 5, 31)),
            # Winter (EST, UTC-5): 01:30 UTC Jan 1 == 20:30 Dec 31 ET.
            (datetime(2026, 1, 1, 1, 30, tzinfo=timezone.utc), date(2025, 12, 31)),
        ],
    )
    def test_uses_eastern_date_not_utc(self, mocker, utc_instant, expected):
        fake_datetime = mocker.patch("app.services.market_data.datetime")
        fake_datetime.now.side_effect = lambda tz=None: utc_instant.astimezone(tz)

        assert _market_today() == expected


# ── _normalize_symbol ──────────────────────────────────────


class TestSymbolNormalization:
    async def test_lowercase_input_is_uppercased(self):
        called: dict = {}

        def fmp_handler(request: httpx.Request) -> httpx.Response:
            called["path"] = request.url.path
            return httpx.Response(200, json=[{"symbol": "AAPL"}])

        service, redis = _service(fmp_handler=fmp_handler)

        await service._get_quote_cached("AAPL")  # warm path
        # Call the public API with mixed case — should normalize.
        result = await service.get_batch_quotes(["aapl"])

        assert result["quotes"][0]["symbol"] == "AAPL"
        # Cache key uses the normalized form.
        assert any(c[0] == "market:quote:AAPL" for c in redis.set_calls)

    async def test_leading_trailing_whitespace_is_stripped(self):
        captured: dict = {}

        def alpaca_handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            return httpx.Response(200, json={"bars": []})

        service, _ = _service(alpaca_handler=alpaca_handler)

        await service.get_chart("  AAPL ", "1M")

        # Whitespace stripped, normalized to AAPL in the upstream URL.
        assert captured["path"] == "/v2/stocks/AAPL/bars"

    async def test_empty_symbol_raises(self):
        service, _ = _service()

        with pytest.raises(MarketDataInvalidInputError):
            await service.get_stock_info("")

    async def test_invalid_chars_raise(self):
        service, _ = _service()

        for bad in ["../foo", "A,B", "A/B", "A B"]:
            with pytest.raises(MarketDataInvalidInputError):
                await service.get_chart(bad, "1M")

    async def test_too_long_symbol_raises(self):
        service, _ = _service()

        with pytest.raises(MarketDataInvalidInputError):
            await service.get_stock_info("A" * 11)


# ── Cache helpers ──────────────────────────────────────────


class TestCacheGet:
    async def test_returns_none_on_miss(self):
        service, _ = _service()

        assert await service._cache_get("market:nope") is None

    async def test_decodes_json(self):
        service, redis = _service()
        redis.store["k"] = json.dumps({"a": 1})

        assert await service._cache_get("k") == {"a": 1}

    async def test_redis_error_is_swallowed(self):
        service, _ = _service(redis=FakeRedis(get_raises=RuntimeError("boom")))

        # Pre-populated market:status read also routes through _cache_get;
        # the helper must return None instead of crashing.
        assert await service._cache_get("market:quote:AAPL") is None

    async def test_invalid_json_returns_none(self):
        service, redis = _service()
        redis.store["k"] = "not-json"

        assert await service._cache_get("k") is None


class TestCacheSet:
    async def test_writes_with_ttl(self):
        service, redis = _service()

        await service._cache_set("k", {"a": 1}, 60)

        # FakeRedis records every set; the pre-seeded market:status entry
        # only goes through `store`, not `set_calls`, so we filter to "k".
        calls = [c for c in redis.set_calls if c[0] == "k"]
        assert calls == [("k", json.dumps({"a": 1}), 60)]

    async def test_redis_error_is_swallowed(self):
        service, _ = _service(redis=FakeRedis(set_raises=RuntimeError("boom")))

        # Should not raise.
        await service._cache_set("k", {"a": 1}, 60)


# ── get_stock_info ─────────────────────────────────────────


class TestGetStockInfo:
    async def test_parallel_fetch_merges_keys(self):
        def fmp_handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path.endswith("/quote"):
                return httpx.Response(
                    200,
                    json=[{"symbol": "AAPL", "name": "Apple", "price": 195.5}],
                )
            if path.endswith("/profile"):
                return httpx.Response(
                    200,
                    json=[
                        {
                            "companyName": "Apple Inc.",
                            "exchangeShortName": "NASDAQ",
                            "exchange": "NASDAQ",
                            "sector": "Technology",
                            "industry": "Consumer Electronics",
                        }
                    ],
                )
            if path.endswith("/ratios-ttm"):
                return httpx.Response(
                    200,
                    json=[
                        {"dividendYieldTTM": 0.005, "priceToEarningsRatioTTM": 25.0}
                    ],
                )
            if path.endswith("/ratios"):
                return httpx.Response(
                    200,
                    json=[
                        {"fiscalYear": "2025", "priceToEarningsRatio": 30.0},
                        {"fiscalYear": "2024", "priceToEarningsRatio": 20.0},
                    ],
                )
            if path.endswith("/sector-pe-snapshot"):
                return httpx.Response(
                    200,
                    json=[{"sector": "Technology", "exchange": "NASDAQ", "pe": 50.0}],
                )
            if path.endswith("/industry-pe-snapshot"):
                return httpx.Response(
                    200,
                    json=[
                        {
                            "industry": "Consumer Electronics",
                            "exchange": "NASDAQ",
                            "pe": 40.0,
                        }
                    ],
                )
            if path.endswith("/price-target-consensus"):
                return httpx.Response(200, json=[{"targetConsensus": 200}])
            if path.endswith("/grades-consensus"):
                return httpx.Response(200, json=[{"strongBuy": 12}])
            if path.endswith("/income-statement-ttm"):
                return httpx.Response(
                    200,
                    json=[
                        {
                            "revenue": 400000000000,
                            "netIncome": 100000000000,
                            "epsDiluted": 6.4,
                            "date": "2026-03-28",
                            "reportedCurrency": "USD",
                        }
                    ],
                )
            if path.endswith("/balance-sheet-statement-ttm"):
                return httpx.Response(200, json=[{"totalDebt": 110000000000}])
            if path.endswith("/cash-flow-statement-ttm"):
                return httpx.Response(200, json=[{"freeCashFlow": 90000000000}])
            if path.endswith("/income-statement"):
                return httpx.Response(
                    200,
                    json=[
                        {"fiscalYear": 2025, "revenue": 400000000000},
                        {"fiscalYear": 2024, "revenue": 380000000000},
                    ],
                )
            if path.endswith("/earnings"):
                return httpx.Response(
                    200,
                    json=[
                        {"date": "2026-04-30", "epsActual": 2.01,
                         "epsEstimated": 1.95, "revenueActual": 111,
                         "revenueEstimated": 109},
                        {"date": "2026-01-29", "epsActual": 2.85,
                         "epsEstimated": 2.67, "revenueActual": 143,
                         "revenueEstimated": 138},
                    ],
                )
            if path.endswith("/analyst-estimates"):
                return httpx.Response(
                    200,
                    json=[
                        {"date": "2099-09-28", "revenueAvg": 130, "epsAvg": 2.45,
                         "numAnalystsEps": 9},
                        {"date": "2099-06-28", "revenueAvg": 100,
                         "revenueLow": 95, "revenueHigh": 105, "epsAvg": 1.5,
                         "numAnalystsEps": 12},
                    ],
                )
            return httpx.Response(404)

        def alpaca_handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/bars"):
                return httpx.Response(
                    200,
                    json={
                        "bars": [
                            # Contiguous sessions straddling each report date so
                            # the window has a close before and after both events.
                            {"t": "2026-01-28T05:00:00Z", "o": 100, "h": 100,
                             "l": 100, "c": 100, "v": 1},
                            {"t": "2026-01-29T05:00:00Z", "o": 102, "h": 102,
                             "l": 102, "c": 102, "v": 1},
                            {"t": "2026-01-30T05:00:00Z", "o": 105, "h": 105,
                             "l": 105, "c": 105, "v": 1},
                            {"t": "2026-04-29T05:00:00Z", "o": 200, "h": 200,
                             "l": 200, "c": 200, "v": 1},
                            {"t": "2026-04-30T05:00:00Z", "o": 210, "h": 210,
                             "l": 210, "c": 210, "v": 1},
                            {"t": "2026-05-01T05:00:00Z", "o": 220, "h": 220,
                             "l": 220, "c": 220, "v": 1},
                        ]
                    },
                )
            return httpx.Response(200, json={})

        service, _ = _service(
            fmp_handler=fmp_handler, alpaca_handler=alpaca_handler
        )

        result = await service.get_stock_info("AAPL")

        assert set(result.keys()) == {
            "quote",
            "profile",
            "ratios",
            "financials",
            "valuation",
            "earnings",
            "analyst",
        }
        assert result["quote"]["symbol"] == "AAPL"
        assert result["profile"]["name"] == "Apple Inc."
        assert result["ratios"]["dividend_yield"] == "0.005"
        assert result["analyst"]["target_consensus"] == "200"
        assert result["analyst"]["strong_buy"] == 12
        financials = result["financials"]
        assert financials["revenue"] == "400000000000"
        assert financials["total_debt"] == "110000000000"
        assert financials["free_cash_flow"] == "90000000000"
        assert financials["fiscal_period"] == "TTM through 2026-03-28"
        # Growth derived from the two annual rows: (400 - 380) / 380.
        assert financials["revenue_growth_yoy"] == "0.0526"
        assert len(financials["annual_trend"]) == 2
        valuation = result["valuation"]
        assert valuation["pe"] == "25.0"
        assert valuation["sector_pe"] == "50.0"
        assert valuation["industry_pe"] == "40.0"
        # 25 / 50 - 1 = -0.5; 25 / 40 - 1 = -0.375.
        assert valuation["pe_vs_sector"] == "-0.5"
        assert valuation["pe_vs_industry"] == "-0.375"
        assert valuation["pe_5y_low"] == "20.0"
        assert valuation["pe_5y_high"] == "30.0"
        earnings = result["earnings"]
        # Nearest upcoming estimate is 2099-06-28, not the farther 2099-09-28.
        assert earnings["next_period_end"] == "2099-06-28"
        assert earnings["revenue_estimate_avg"] == "100"
        assert earnings["num_analysts"] == 12
        assert earnings["quarterly"][0]["report_date"] == "2026-04-30"
        assert earnings["quarterly"][0]["eps_surprise_pct"] == "0.0308"
        assert earnings["quarterly"][0]["price_move_pct"] == "0.1"
        assert earnings["avg_post_earnings_move_pct"] == "0.075"
        assert earnings["events_measured"] == 2

    async def test_cache_hits_skip_provider(self):
        called = False

        def fmp_handler(request: httpx.Request) -> httpx.Response:
            nonlocal called
            called = True
            return httpx.Response(200, json=[])

        service, redis = _service(fmp_handler=fmp_handler)
        # Seed all three caches.
        redis.store["market:quote:AAPL"] = json.dumps({"symbol": "AAPL"})
        redis.store["market:fundamentals:AAPL"] = json.dumps(
            {
                "profile": {"name": "Apple"},
                "ratios": {"roe": "1.5"},
                "financials": {"revenue": "400000000000"},
                "valuation": {"pe": "25.0"},
                "earnings": {"events_measured": 2},
            }
        )
        redis.store["market:analyst:AAPL"] = json.dumps({"target_consensus": "200"})

        result = await service.get_stock_info("AAPL")

        assert called is False
        assert result == {
            "quote": {"symbol": "AAPL"},
            "profile": {"name": "Apple"},
            "ratios": {"roe": "1.5"},
            "financials": {"revenue": "400000000000"},
            "valuation": {"pe": "25.0"},
            "earnings": {"events_measured": 2},
            "analyst": {"target_consensus": "200"},
        }

    async def test_cache_hit_without_financials_backfills_empty_block(self):
        def fmp_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[])

        service, redis = _service(fmp_handler=fmp_handler)
        redis.store["market:quote:AAPL"] = json.dumps({"symbol": "AAPL"})
        # Pre-financials cache entry: no "financials" key.
        redis.store["market:fundamentals:AAPL"] = json.dumps(
            {"profile": {"name": "Apple"}, "ratios": {"roe": "1.5"}}
        )
        redis.store["market:analyst:AAPL"] = json.dumps({"target_consensus": "200"})

        result = await service.get_stock_info("AAPL")

        # Backfilled to valid, all-null blocks — never KeyError.
        assert result["financials"]["revenue"] is None
        assert result["financials"]["annual_trend"] == []
        assert result["valuation"]["pe"] is None
        assert result["valuation"]["valuation_history"] == []
        assert result["earnings"]["next_period_end"] is None
        assert result["earnings"]["quarterly"] == []

    async def test_one_failing_statement_degrades_only_its_fields(self):
        def fmp_handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path.endswith("/quote"):
                return httpx.Response(200, json=[{"symbol": "AAPL"}])
            if path.endswith("/profile"):
                return httpx.Response(
                    200, json=[{"companyName": "Apple", "exchangeShortName": "NASDAQ"}]
                )
            if path.endswith("/ratios-ttm"):
                return httpx.Response(200, json=[{}])
            if path.endswith("/price-target-consensus"):
                return httpx.Response(200, json=[{}])
            if path.endswith("/grades-consensus"):
                return httpx.Response(200, json=[{}])
            if path.endswith("/income-statement-ttm"):
                # Premium-gate / upstream failure for this one statement.
                return httpx.Response(402, text="Restricted Endpoint")
            if path.endswith("/balance-sheet-statement-ttm"):
                return httpx.Response(200, json=[{"totalDebt": 110000000000}])
            if path.endswith("/cash-flow-statement-ttm"):
                return httpx.Response(200, json=[{"freeCashFlow": 90000000000}])
            if path.endswith("/income-statement"):
                return httpx.Response(200, json=[])
            return httpx.Response(404)

        service, _ = _service(fmp_handler=fmp_handler)

        result = await service.get_stock_info("AAPL")

        financials = result["financials"]
        # Income statement failed → its fields null.
        assert financials["revenue"] is None
        # Other statements still populated.
        assert financials["total_debt"] == "110000000000"
        assert financials["free_cash_flow"] == "90000000000"

    async def test_reaction_bars_failure_degrades_only_reaction_fields(self):
        """Alpaca bars failing nulls the reaction summary; actuals survive."""

        def fmp_handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path.endswith("/quote"):
                return httpx.Response(200, json=[{"symbol": "AAPL"}])
            if path.endswith("/profile"):
                return httpx.Response(
                    200, json=[{"companyName": "Apple", "exchange": "NASDAQ"}]
                )
            if path.endswith("/earnings"):
                return httpx.Response(
                    200,
                    json=[
                        {"date": "2026-04-30", "epsActual": 2.01,
                         "epsEstimated": 1.95},
                    ],
                )
            return httpx.Response(200, json=[])

        def alpaca_handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/bars"):
                return httpx.Response(500, text="boom")
            return httpx.Response(200, json={})

        service, _ = _service(
            fmp_handler=fmp_handler, alpaca_handler=alpaca_handler
        )

        result = await service.get_stock_info("AAPL")

        earnings = result["earnings"]
        # Actuals still populate from FMP...
        assert earnings["quarterly"][0]["eps_surprise_pct"] == "0.0308"
        # ...but the bar-derived reaction degrades to null.
        assert earnings["quarterly"][0]["price_move_pct"] is None
        assert earnings["avg_post_earnings_move_pct"] is None
        assert earnings["events_measured"] is None

    async def test_unreported_quarter_excluded_from_reaction(self):
        """A row without actuals must not contribute a reaction even if bars
        straddle its date (FMP can return a past quarter before backfilling
        actuals)."""

        def fmp_handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path.endswith("/quote"):
                return httpx.Response(200, json=[{"symbol": "AAPL"}])
            if path.endswith("/profile"):
                return httpx.Response(
                    200, json=[{"companyName": "Apple", "exchange": "NASDAQ"}]
                )
            if path.endswith("/earnings"):
                return httpx.Response(
                    200,
                    json=[
                        {"date": "2026-04-30", "epsActual": None,
                         "epsEstimated": 1.95},  # reported-but-unpopulated
                        {"date": "2026-01-29", "epsActual": 2.85,
                         "epsEstimated": 2.67},
                    ],
                )
            return httpx.Response(200, json=[])

        def alpaca_handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/bars"):
                return httpx.Response(
                    200,
                    json={
                        "bars": [
                            {"t": "2026-01-28T05:00:00Z", "o": 100, "h": 100,
                             "l": 100, "c": 100, "v": 1},
                            {"t": "2026-01-29T05:00:00Z", "o": 105, "h": 105,
                             "l": 105, "c": 105, "v": 1},
                            {"t": "2026-04-29T05:00:00Z", "o": 200, "h": 200,
                             "l": 200, "c": 200, "v": 1},
                            {"t": "2026-04-30T05:00:00Z", "o": 220, "h": 220,
                             "l": 220, "c": 220, "v": 1},
                        ]
                    },
                )
            return httpx.Response(200, json={})

        service, _ = _service(
            fmp_handler=fmp_handler, alpaca_handler=alpaca_handler
        )

        result = await service.get_stock_info("AAPL")

        earnings = result["earnings"]
        # Only the reported 2026-01-29 quarter is measured — the unpopulated
        # 2026-04-30 row is skipped despite having bars on both sides.
        assert earnings["events_measured"] == 1
        assert [q["report_date"] for q in earnings["quarterly"]] == ["2026-01-29"]

    async def test_sector_benchmark_cached_per_exchange(self):
        """The sector/industry snapshot is cached by exchange, not by symbol."""
        snapshot_calls = 0

        def fmp_handler(request: httpx.Request) -> httpx.Response:
            nonlocal snapshot_calls
            path = request.url.path
            if path.endswith("/quote"):
                return httpx.Response(200, json=[{"symbol": "AAPL"}])
            if path.endswith("/profile"):
                return httpx.Response(
                    200,
                    json=[{"companyName": "Apple", "exchange": "NASDAQ",
                           "sector": "Technology"}],
                )
            if path.endswith("/sector-pe-snapshot"):
                snapshot_calls += 1
                return httpx.Response(
                    200,
                    json=[{"sector": "Technology", "exchange": "NASDAQ", "pe": 50.0}],
                )
            if path.endswith("/industry-pe-snapshot"):
                return httpx.Response(200, json=[])
            if path.endswith("/ratios-ttm"):
                return httpx.Response(200, json=[{"priceToEarningsRatioTTM": 25.0}])
            return httpx.Response(200, json=[])

        service, redis = _service(fmp_handler=fmp_handler)

        first = await service.get_stock_info("AAPL")
        # Second symbol on the same exchange reuses the cached snapshot.
        del redis.store["market:fundamentals:AAPL"]
        second = await service.get_stock_info("MSFT")

        assert first["valuation"]["sector_pe"] == "50.0"
        assert second["valuation"]["sector_pe"] == "50.0"
        assert snapshot_calls == 1
        assert "market:valuation_pe:NASDAQ" in redis.store

    async def test_sector_benchmark_walks_back_to_last_session(self):
        """Empty snapshot on the first date(s) walks back to a session with data."""
        dates_tried: list[str] = []

        def fmp_handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path.endswith("/quote"):
                return httpx.Response(200, json=[{"symbol": "AAPL"}])
            if path.endswith("/profile"):
                return httpx.Response(
                    200,
                    json=[{"companyName": "Apple", "exchange": "NASDAQ",
                           "sector": "Technology"}],
                )
            if path.endswith("/sector-pe-snapshot"):
                on_date = request.url.params["date"]
                dates_tried.append(on_date)
                # First date returns empty (e.g. weekend); next has data.
                if len(dates_tried) == 1:
                    return httpx.Response(200, json=[])
                return httpx.Response(
                    200,
                    json=[{"sector": "Technology", "exchange": "NASDAQ", "pe": 50.0}],
                )
            if path.endswith("/ratios-ttm"):
                return httpx.Response(200, json=[{"priceToEarningsRatioTTM": 25.0}])
            return httpx.Response(200, json=[])

        service, _ = _service(fmp_handler=fmp_handler)

        result = await service.get_stock_info("AAPL")

        assert result["valuation"]["sector_pe"] == "50.0"
        assert result["valuation"]["as_of_date"] == dates_tried[1]
        assert len(dates_tried) >= 2
        # The industry snapshot returned no rows in this handler, so its
        # benchmark degrades to null independently of the sector result.
        assert result["valuation"]["industry_pe"] is None

    async def test_benchmark_failure_degrades_only_sector_fields(self):
        """A failing snapshot leaves the company P/E and history intact."""

        def fmp_handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path.endswith("/quote"):
                return httpx.Response(200, json=[{"symbol": "AAPL"}])
            if path.endswith("/profile"):
                return httpx.Response(
                    200,
                    json=[{"companyName": "Apple", "exchange": "NASDAQ",
                           "sector": "Technology"}],
                )
            if path.endswith("/sector-pe-snapshot"):
                return httpx.Response(500, text="boom")
            if path.endswith("/industry-pe-snapshot"):
                return httpx.Response(500, text="boom")
            if path.endswith("/ratios-ttm"):
                return httpx.Response(200, json=[{"priceToEarningsRatioTTM": 25.0}])
            if path.endswith("/ratios"):
                return httpx.Response(
                    200, json=[{"fiscalYear": "2025", "priceToEarningsRatio": 30.0}]
                )
            return httpx.Response(200, json=[])

        service, _ = _service(fmp_handler=fmp_handler)

        result = await service.get_stock_info("AAPL")

        valuation = result["valuation"]
        # Benchmark failed → vs-sector fields null...
        assert valuation["sector_pe"] is None
        assert valuation["pe_vs_sector"] is None
        assert valuation["as_of_date"] is None
        # ...but the company P/E and own-history range still populate.
        assert valuation["pe"] == "25.0"
        assert valuation["pe_5y_low"] == "30.0"

    async def test_one_failing_snapshot_keeps_the_other(self):
        """Sector 5xx must not discard a successful industry snapshot."""

        def fmp_handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path.endswith("/quote"):
                return httpx.Response(200, json=[{"symbol": "AAPL"}])
            if path.endswith("/profile"):
                return httpx.Response(
                    200,
                    json=[{"companyName": "Apple", "exchange": "NASDAQ",
                           "sector": "Technology",
                           "industry": "Consumer Electronics"}],
                )
            if path.endswith("/sector-pe-snapshot"):
                return httpx.Response(500, text="boom")
            if path.endswith("/industry-pe-snapshot"):
                return httpx.Response(
                    200,
                    json=[{"industry": "Consumer Electronics",
                           "exchange": "NASDAQ", "pe": 40.0}],
                )
            if path.endswith("/ratios-ttm"):
                return httpx.Response(200, json=[{"priceToEarningsRatioTTM": 25.0}])
            return httpx.Response(200, json=[])

        service, redis = _service(fmp_handler=fmp_handler)

        result = await service.get_stock_info("AAPL")

        valuation = result["valuation"]
        assert valuation["sector_pe"] is None
        assert valuation["industry_pe"] == "40.0"
        # A partial-with-error result is not cached, so the next request retries.
        assert "market:valuation_pe:NASDAQ" not in redis.store

    async def test_missing_exchange_skips_benchmark_fetch(self):
        """No exchange on the profile → no snapshot call, sector fields null."""
        snapshot_called = False

        def fmp_handler(request: httpx.Request) -> httpx.Response:
            nonlocal snapshot_called
            path = request.url.path
            if path.endswith("/quote"):
                return httpx.Response(200, json=[{"symbol": "AAPL"}])
            if path.endswith("/profile"):
                return httpx.Response(200, json=[{"companyName": "Apple"}])
            if path.endswith("/sector-pe-snapshot"):
                snapshot_called = True
                return httpx.Response(200, json=[])
            if path.endswith("/ratios-ttm"):
                return httpx.Response(200, json=[{"priceToEarningsRatioTTM": 25.0}])
            return httpx.Response(200, json=[])

        service, _ = _service(fmp_handler=fmp_handler)

        result = await service.get_stock_info("AAPL")

        assert snapshot_called is False
        assert result["valuation"]["pe"] == "25.0"
        assert result["valuation"]["sector_pe"] is None


# ── get_batch_quotes ───────────────────────────────────────


class TestGetBatchQuotes:
    async def test_only_misses_hit_provider(self):
        captured: dict = {}

        def fmp_handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["params"] = dict(request.url.params)
            return httpx.Response(
                200,
                json=[{"symbol": "MSFT", "name": "Microsoft", "price": 410}],
            )

        service, redis = _service(fmp_handler=fmp_handler)
        redis.store["market:quote:AAPL"] = json.dumps(
            {"symbol": "AAPL", "name": "Apple", "price": "195.5"}
        )

        result = await service.get_batch_quotes(["AAPL", "MSFT"])

        # Only MSFT hit FMP.
        assert captured["path"].endswith("/batch-quote")
        assert captured["params"]["symbols"] == "MSFT"
        assert [q["symbol"] for q in result["quotes"]] == ["AAPL", "MSFT"]
        # Newly-fetched MSFT must be cached.
        assert any(c[0] == "market:quote:MSFT" for c in redis.set_calls)

    async def test_all_cached_skips_provider(self):
        called = False

        def fmp_handler(request: httpx.Request) -> httpx.Response:
            nonlocal called
            called = True
            return httpx.Response(200, json=[])

        service, redis = _service(fmp_handler=fmp_handler)
        redis.store["market:quote:AAPL"] = json.dumps({"symbol": "AAPL"})
        redis.store["market:quote:MSFT"] = json.dumps({"symbol": "MSFT"})

        result = await service.get_batch_quotes(["AAPL", "MSFT"])

        assert called is False
        assert [q["symbol"] for q in result["quotes"]] == ["AAPL", "MSFT"]

    async def test_uses_open_ttl_when_market_open(self):
        def fmp_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json=[{"symbol": "AAPL", "name": "Apple", "price": 195.5}]
            )

        service, redis = _service(fmp_handler=fmp_handler, is_market_open=True)

        await service.get_batch_quotes(["AAPL"])

        ttl = next(c[2] for c in redis.set_calls if c[0] == "market:quote:AAPL")
        assert ttl == 15

    async def test_uses_closed_ttl_when_market_closed(self):
        def fmp_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json=[{"symbol": "AAPL", "name": "Apple", "price": 195.5}]
            )

        service, redis = _service(fmp_handler=fmp_handler, is_market_open=False)

        await service.get_batch_quotes(["AAPL"])

        ttl = next(c[2] for c in redis.set_calls if c[0] == "market:quote:AAPL")
        assert ttl == 1800


# ── get_chart ──────────────────────────────────────────────


class TestGetChart:
    async def test_unsupported_timeframe_raises_invalid_input(self):
        service, _ = _service()

        with pytest.raises(MarketDataInvalidInputError) as info:
            await service.get_chart("AAPL", "10Y")

        assert info.value.symbol == "AAPL"

    async def test_cache_hit_skips_alpaca(self):
        called = False

        def alpaca_handler(request: httpx.Request) -> httpx.Response:
            nonlocal called
            called = True
            return httpx.Response(200, json={"bars": []})

        service, redis = _service(alpaca_handler=alpaca_handler)
        cached = {"symbol": "AAPL", "timeframe": "1M", "bars": []}
        redis.store["market:chart:AAPL:1M"] = json.dumps(cached)

        result = await service.get_chart("AAPL", "1M")

        assert called is False
        assert result == cached

    async def test_miss_calls_alpaca_and_projects_bars(self):
        captured: dict = {}

        def alpaca_handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["params"] = dict(request.url.params)
            captured["auth"] = request.headers.get("Authorization")
            return httpx.Response(
                200,
                json={
                    "bars": [
                        {
                            "t": "2026-05-07T15:00:00Z",
                            "o": 195.0,
                            "h": 196.5,
                            "l": 194.0,
                            "c": 195.5,
                            "v": 1000000,
                            "vw": 195.3,
                            "n": 5000,
                        }
                    ]
                },
            )

        service, redis = _service(alpaca_handler=alpaca_handler)

        result = await service.get_chart("AAPL", "1M")

        assert captured["path"] == "/v2/stocks/AAPL/bars"
        assert captured["params"]["timeframe"] == "1Hour"
        assert captured["params"]["limit"] == "10000"
        assert captured["params"]["adjustment"] == "split"
        assert captured["params"]["feed"] == "iex"
        assert captured["params"]["sort"] == "asc"
        assert captured["auth"] == "Bearer fake-token"
        assert result["bars"][0] == {
            "timestamp": "2026-05-07T15:00:00Z",
            "open": "195.0",
            "high": "196.5",
            "low": "194.0",
            "close": "195.5",
            "volume": 1000000,
            "vwap": "195.3",
            "trade_count": 5000,
        }
        # Result must be cached.
        assert any(c[0] == "market:chart:AAPL:1M" for c in redis.set_calls)

    async def test_get_stock_bars_passes_explicit_window(self):
        captured: dict = {}

        def alpaca_handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["params"] = dict(request.url.params)
            return httpx.Response(
                200,
                json={
                    "bars": [
                        {
                            "t": "2026-05-29T12:59:00Z",
                            "o": 100,
                            "h": 102,
                            "l": 99,
                            "c": 101,
                            "v": 123,
                        }
                    ]
                },
            )

        service, _ = _service(alpaca_handler=alpaca_handler)

        result = await service.get_stock_bars(
            " aapl ",
            timeframe="1Min",
            start=datetime(2026, 5, 28, 20, 0, tzinfo=timezone.utc),
            end=datetime(2026, 5, 29, 13, 0, tzinfo=timezone.utc),
            limit=50,
        )

        assert captured["path"] == "/v2/stocks/AAPL/bars"
        assert captured["params"]["timeframe"] == "1Min"
        assert captured["params"]["start"] == "2026-05-28T20:00:00+00:00"
        assert captured["params"]["end"] == "2026-05-29T13:00:00+00:00"
        assert captured["params"]["limit"] == "50"
        assert result[0]["timestamp"] == "2026-05-29T12:59:00Z"
        assert result[0]["close"] == "101"

    async def test_intraday_timeframe_uses_short_ttl(self):
        def alpaca_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"bars": []})

        service, redis = _service(alpaca_handler=alpaca_handler)

        await service.get_chart("AAPL", "1D")  # 5Min

        ttl = next(c[2] for c in redis.set_calls if c[0] == "market:chart:AAPL:1D")
        assert ttl == 60

    async def test_daily_timeframe_uses_long_ttl(self):
        def alpaca_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"bars": []})

        service, redis = _service(alpaca_handler=alpaca_handler)

        await service.get_chart("AAPL", "3M")  # 1Day

        ttl = next(c[2] for c in redis.set_calls if c[0] == "market:chart:AAPL:3M")
        assert ttl == 3600

    async def test_alpaca_network_error_raises_unavailable(self):
        def alpaca_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        service, _ = _service(alpaca_handler=alpaca_handler)

        with pytest.raises(MarketDataUnavailableError):
            await service.get_chart("AAPL", "1M")

    async def test_alpaca_non_200_raises_upstream(self):
        def alpaca_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="overloaded")

        service, _ = _service(alpaca_handler=alpaca_handler)

        with pytest.raises(MarketDataUpstreamError) as info:
            await service.get_chart("AAPL", "1M")

        assert info.value.status_code == 503


# ── get_market_status ──────────────────────────────────────


class TestGetMarketStatus:
    async def test_cache_hit_skips_alpaca(self):
        called = False

        def alpaca_handler(request: httpx.Request) -> httpx.Response:
            nonlocal called
            called = True
            return httpx.Response(200, json={"is_open": True})

        # The fixture seeds market:status; this verifies cache is used.
        service, _ = _service(alpaca_handler=alpaca_handler)

        result = await service.get_market_status()

        assert called is False
        assert result["is_open"] is True

    async def test_miss_calls_clock_and_projects(self):
        captured: dict = {}

        def alpaca_handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            return httpx.Response(
                200,
                json={
                    "is_open": False,
                    "next_open": "2026-05-08T13:30:00Z",
                    "next_close": "2026-05-08T20:00:00Z",
                    "timestamp": "2026-05-07T22:00:00Z",
                },
            )

        service, redis = _service(alpaca_handler=alpaca_handler)
        # Clear the seeded entry so the call falls through to Alpaca.
        del redis.store["market:status"]

        result = await service.get_market_status()

        assert captured["path"] == "/v1/clock"
        assert result == {
            "is_open": False,
            "next_open": "2026-05-08T13:30:00Z",
            "next_close": "2026-05-08T20:00:00Z",
            "timestamp": "2026-05-07T22:00:00Z",
        }
        assert any(
            c[0] == "market:status" and c[2] == 60 for c in redis.set_calls
        )


# ── _is_market_open real path ──────────────────────────────


class TestIsMarketOpenRealPath:
    """Exercise the real path: cache miss → clock call → status caches → quote uses it."""

    async def test_cache_miss_drives_alpaca_clock_then_quote_uses_open_ttl(self):
        clock_calls = 0

        def alpaca_handler(request: httpx.Request) -> httpx.Response:
            nonlocal clock_calls
            clock_calls += 1
            return httpx.Response(
                200,
                json={
                    "is_open": True,
                    "next_open": "2026-05-08T13:30:00Z",
                    "next_close": "2026-05-07T20:00:00Z",
                    "timestamp": "2026-05-07T15:00:00Z",
                },
            )

        def fmp_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json=[{"symbol": "AAPL", "name": "Apple", "price": 195.5}]
            )

        service, redis = _service(
            fmp_handler=fmp_handler,
            alpaca_handler=alpaca_handler,
            is_market_open=None,  # leave cache empty so real path runs
        )

        await service.get_batch_quotes(["AAPL"])

        # _is_market_open went through _alpaca_clock once.
        assert clock_calls == 1
        # Open-market TTL was used because the clock said is_open=True.
        ttl = next(c[2] for c in redis.set_calls if c[0] == "market:quote:AAPL")
        assert ttl == 15
        # Status was written to cache.
        assert any(c[0] == "market:status" for c in redis.set_calls)


# ── close ──────────────────────────────────────────────────


async def test_close_closes_both_clients():
    service, _ = _service()

    await service.close()

    assert service._fmp._client.is_closed
    assert service._alpaca_client.is_closed


# ── alpaca_broker token integration ────────────────────────


class TestAlpacaBrokerToken:
    async def test_broker_token_used_in_authorization_header(self):
        captured: dict = {}

        def alpaca_handler(request: httpx.Request) -> httpx.Response:
            captured["auth"] = request.headers.get("Authorization")
            return httpx.Response(200, json={"bars": []})

        broker = FakeAlpacaBroker(token="custom-bearer")
        service, _ = _service(alpaca_handler=alpaca_handler, alpaca_broker=broker)

        await service.get_chart("AAPL", "1M")

        assert captured["auth"] == "Bearer custom-bearer"
        assert broker.calls >= 1

    async def test_broker_unavailable_translates_to_market_data_unavailable(self):
        broker = FakeAlpacaBroker(
            raises=AlpacaBrokerUnavailableError("broker down")
        )
        service, _ = _service(alpaca_broker=broker)

        with pytest.raises(MarketDataUnavailableError):
            await service.get_chart("AAPL", "1M")

    async def test_broker_error_translates_to_market_data_unavailable(self):
        broker = FakeAlpacaBroker(
            raises=AlpacaBrokerError(401, "auth failed", None)
        )
        service, _ = _service(alpaca_broker=broker)

        with pytest.raises(MarketDataUnavailableError):
            await service.get_chart("AAPL", "1M")


# ── Clock-failure fallback ─────────────────────────────────


class TestQuoteTtlClockFallback:
    """When Alpaca's clock is unreachable, FMP quotes still flow through
    with a conservative (short) TTL rather than being dropped."""

    async def test_clock_unavailable_uses_short_ttl(self):
        def fmp_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json=[{"symbol": "AAPL", "name": "Apple", "price": 195.5}]
            )

        def alpaca_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("clock down")

        service, redis = _service(
            fmp_handler=fmp_handler,
            alpaca_handler=alpaca_handler,
            is_market_open=None,  # leave market:status cache empty
        )

        result = await service.get_batch_quotes(["AAPL"])

        # FMP data is returned despite clock failure.
        assert [q["symbol"] for q in result["quotes"]] == ["AAPL"]
        # And it was cached with the conservative open-market TTL.
        ttl = next(c[2] for c in redis.set_calls if c[0] == "market:quote:AAPL")
        assert ttl == 15

    async def test_clock_unavailable_quote_path_returns_data(self):
        def fmp_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json=[{"symbol": "AAPL", "name": "Apple", "price": 195.5}]
            )

        def alpaca_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("clock down")

        service, _ = _service(
            fmp_handler=fmp_handler,
            alpaca_handler=alpaca_handler,
            is_market_open=None,
        )

        result = await service._get_quote_cached("AAPL")

        assert result["symbol"] == "AAPL"


# ── get_market_data_service dependency ─────────────────────


class TestGetMarketDataServiceDependency:
    def test_returns_service_when_set(self):
        request = MagicMock(spec=Request)
        sentinel = object()
        request.app.state.market_data = sentinel

        result = get_market_data_service(request)

        assert result is sentinel

    def test_raises_503_exception_when_unset(self):
        request = MagicMock(spec=Request)
        request.app.state.market_data = None

        with pytest.raises(MarketDataUnavailableError):
            get_market_data_service(request)


# ── Bearer redaction ───────────────────────────────────────


class TestBearerRedaction:
    """Alpaca error envelopes occasionally echo the auth header — log line
    must not leak the bearer token."""

    async def test_bearer_in_alpaca_error_body_is_redacted(self, caplog):
        def alpaca_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                401,
                text='{"error": "invalid token Bearer abc123def.token-456"}',
            )

        service, _ = _service(alpaca_handler=alpaca_handler)

        with caplog.at_level("WARNING"):
            with pytest.raises(MarketDataUpstreamError):
                await service.get_chart("AAPL", "1M")

        combined = " ".join(r.getMessage() for r in caplog.records)
        assert "abc123def.token-456" not in combined
        assert "Bearer ***" in combined
