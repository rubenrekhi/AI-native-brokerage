"""Unit tests for app.services.market_data.MarketDataService."""

import json
from collections.abc import Callable
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
            if "/quote/" in path:
                return httpx.Response(
                    200,
                    json=[{"symbol": "AAPL", "name": "Apple", "price": 195.5}],
                )
            if "/profile/" in path:
                return httpx.Response(
                    200,
                    json=[{"companyName": "Apple Inc.", "exchangeShortName": "NASDAQ"}],
                )
            if "/ratios-ttm/" in path:
                return httpx.Response(200, json=[{"dividendYieldTTM": 0.005}])
            if "price-target-consensus" in path:
                return httpx.Response(200, json=[{"targetConsensus": 200}])
            if "upgrades-downgrades-consensus" in path:
                return httpx.Response(200, json=[{"strongBuy": 12}])
            return httpx.Response(404)

        service, _ = _service(fmp_handler=fmp_handler)

        result = await service.get_stock_info("AAPL")

        assert set(result.keys()) == {"quote", "profile", "ratios", "analyst"}
        assert result["quote"]["symbol"] == "AAPL"
        assert result["profile"]["name"] == "Apple Inc."
        assert result["ratios"]["dividend_yield"] == "0.005"
        assert result["analyst"]["target_consensus"] == "200"
        assert result["analyst"]["strong_buy"] == 12

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
            {"profile": {"name": "Apple"}, "ratios": {"roe": "1.5"}}
        )
        redis.store["market:analyst:AAPL"] = json.dumps({"target_consensus": "200"})

        result = await service.get_stock_info("AAPL")

        assert called is False
        assert result == {
            "quote": {"symbol": "AAPL"},
            "profile": {"name": "Apple"},
            "ratios": {"roe": "1.5"},
            "analyst": {"target_consensus": "200"},
        }


# ── get_batch_quotes ───────────────────────────────────────


class TestGetBatchQuotes:
    async def test_only_misses_hit_provider(self):
        captured: dict = {}

        def fmp_handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
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
        assert captured["path"].endswith("/quote/MSFT")
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
