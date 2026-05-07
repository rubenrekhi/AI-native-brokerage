"""Unit tests for app.services.fmp."""

import httpx
import pytest

from app.exceptions import (
    MarketDataError,
    MarketDataUnavailableError,
    MarketDataUpstreamError,
)
from app.services.fmp import (
    FmpClient,
    int_or_zero,
    none_if_blank,
    project_analyst,
    project_profile,
    project_quote,
    project_ratios,
    str_or_none,
)


def _make_client(handler) -> FmpClient:
    """Build an FmpClient whose AsyncClient uses MockTransport."""
    return FmpClient(
        api_key="test-api-key",
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler), timeout=30.0
        ),
    )


class TestConstructor:
    def test_empty_api_key_raises(self):
        with pytest.raises(RuntimeError, match="api_key"):
            FmpClient(api_key="")


class TestRequest:
    async def test_appends_apikey_query_param(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            return httpx.Response(200, json=[])

        client = _make_client(handler)
        await client._request("/v3/quote/AAPL")

        assert "apikey=test-api-key" in captured["url"]
        assert captured["url"].startswith(
            "https://financialmodelingprep.com/api/v3/quote/AAPL"
        )

    async def test_merges_extra_params_with_apikey(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json=[])

        client = _make_client(handler)
        await client._request("/v4/price-target-consensus", {"symbol": "AAPL"})

        assert captured["params"] == {"apikey": "test-api-key", "symbol": "AAPL"}

    async def test_network_error_raises_unavailable_with_generic_message(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        client = _make_client(handler)
        with pytest.raises(MarketDataUnavailableError) as info:
            await client._request("/v3/quote/AAPL")

        # Underlying error must not leak into the exception message.
        assert "connection refused" not in info.value.message
        assert info.value.message == "Market data service unavailable"

    async def test_non_200_raises_upstream_with_status_and_no_body_leak(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, text="rate limited")

        client = _make_client(handler)
        with pytest.raises(MarketDataUpstreamError) as info:
            await client._request("/v3/quote/AAPL")

        assert info.value.status_code == 429
        # Body must not leak into the exception message.
        assert "rate limited" not in info.value.message


class TestQuote:
    async def test_returns_first_element_when_array_non_empty(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[{"symbol": "AAPL", "price": 195.5}])

        client = _make_client(handler)
        result = await client.quote("AAPL")

        assert result == {"symbol": "AAPL", "price": 195.5}

    async def test_empty_array_raises_market_data_error_with_symbol(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[])

        client = _make_client(handler)
        with pytest.raises(MarketDataError) as info:
            await client.quote("AAPL")

        assert info.value.symbol == "AAPL"
        assert "AAPL" in info.value.message

    async def test_hits_quote_path(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            return httpx.Response(200, json=[{"symbol": "AAPL"}])

        client = _make_client(handler)
        await client.quote("AAPL")

        assert captured["path"] == "/api/v3/quote/AAPL"


class TestBatchQuote:
    async def test_joins_symbols_with_commas(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            return httpx.Response(200, json=[])

        client = _make_client(handler)
        await client.batch_quote(["AAPL", "MSFT", "GOOG"])

        assert captured["path"] == "/api/v3/quote/AAPL,MSFT,GOOG"

    async def test_returns_raw_dicts(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=[
                    {"symbol": "AAPL", "name": "Apple", "price": 195.5},
                    {"symbol": "MSFT", "name": "Microsoft", "price": 410.2},
                ],
            )

        client = _make_client(handler)
        result = await client.batch_quote(["AAPL", "MSFT"])

        # Endpoint methods return raw FMP shapes; project_quote is the
        # caller's responsibility.
        assert result == [
            {"symbol": "AAPL", "name": "Apple", "price": 195.5},
            {"symbol": "MSFT", "name": "Microsoft", "price": 410.2},
        ]

    async def test_empty_input_returns_empty_list_without_request(self):
        called = False

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal called
            called = True
            return httpx.Response(200, json=[])

        client = _make_client(handler)
        result = await client.batch_quote([])

        assert result == []
        assert called is False

    async def test_empty_response_returns_empty_list(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[])

        client = _make_client(handler)
        result = await client.batch_quote(["AAPL"])

        assert result == []

    async def test_chunks_oversized_request_into_max_sized_calls(self):
        paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            paths.append(request.url.path)
            return httpx.Response(200, json=[{"symbol": "X"}])

        client = _make_client(handler)
        symbols = [f"S{i}" for i in range(250)]
        result = await client.batch_quote(symbols)

        # 250 / 100 = 3 chunks (100 + 100 + 50).
        assert len(paths) == 3
        assert paths[0].count(",") == 99
        assert paths[1].count(",") == 99
        assert paths[2].count(",") == 49
        assert len(result) == 3


class TestProfile:
    async def test_returns_first_element_when_array_non_empty(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[{"companyName": "Apple Inc."}])

        client = _make_client(handler)
        result = await client.profile("AAPL")

        assert result == {"companyName": "Apple Inc."}

    async def test_empty_response_raises_market_data_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[])

        client = _make_client(handler)
        with pytest.raises(MarketDataError) as info:
            await client.profile("AAPL")

        assert info.value.symbol == "AAPL"


class TestRatiosTtm:
    async def test_returns_first_element(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[{"dividendYieldTTM": 0.005}])

        client = _make_client(handler)
        result = await client.ratios_ttm("AAPL")

        assert result == {"dividendYieldTTM": 0.005}

    async def test_empty_response_returns_empty_dict(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[])

        client = _make_client(handler)
        result = await client.ratios_ttm("AAPL")

        assert result == {}

    async def test_dict_response_returned_as_is(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"dividendYieldTTM": 0.005})

        client = _make_client(handler)
        result = await client.ratios_ttm("AAPL")

        assert result == {"dividendYieldTTM": 0.005}


class TestPriceTargetConsensus:
    async def test_passes_symbol_query_param(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["params"] = dict(request.url.params)
            captured["path"] = request.url.path
            return httpx.Response(200, json=[{"targetConsensus": 200}])

        client = _make_client(handler)
        result = await client.price_target_consensus("AAPL")

        assert captured["path"] == "/api/v4/price-target-consensus"
        assert captured["params"]["symbol"] == "AAPL"
        assert result == {"targetConsensus": 200}

    async def test_empty_response_returns_empty_dict(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[])

        client = _make_client(handler)
        result = await client.price_target_consensus("AAPL")

        assert result == {}


class TestUpgradesDowngradesConsensus:
    async def test_passes_symbol_query_param(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["params"] = dict(request.url.params)
            captured["path"] = request.url.path
            return httpx.Response(200, json=[{"strongBuy": 10}])

        client = _make_client(handler)
        result = await client.upgrades_downgrades_consensus("AAPL")

        assert captured["path"] == "/api/v4/upgrades-downgrades-consensus"
        assert captured["params"]["symbol"] == "AAPL"
        assert result == {"strongBuy": 10}

    async def test_empty_response_returns_empty_dict(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[])

        client = _make_client(handler)
        result = await client.upgrades_downgrades_consensus("AAPL")

        assert result == {}


class TestProjectQuote:
    def test_full_mapping(self):
        raw = {
            "symbol": "AAPL",
            "name": "Apple Inc.",
            "price": 195.5,
            "change": 2.3,
            "changesPercentage": 1.18,
            "open": 193.2,
            "dayHigh": 196.1,
            "dayLow": 192.8,
            "previousClose": 193.2,
            "volume": 50000000,
            "avgVolume": 60000000,
            "marketCap": 3000000000000,
            "pe": 32.5,
            "eps": 6.0,
            "yearHigh": 200.0,
            "yearLow": 150.0,
            "priceAvg50": 190.0,
            "priceAvg200": 180.0,
            "sharesOutstanding": 15000000000,
            "earningsAnnouncement": "2026-07-30T20:00:00.000+0000",
            "timestamp": 1730000000,
        }

        result = project_quote(raw)

        assert result == {
            "symbol": "AAPL",
            "name": "Apple Inc.",
            "price": "195.5",
            "change": "2.3",
            "change_percent": "1.18",
            "open": "193.2",
            "day_high": "196.1",
            "day_low": "192.8",
            "previous_close": "193.2",
            "volume": 50000000,
            "avg_volume": 60000000,
            "market_cap": 3000000000000,
            "pe_ratio": "32.5",
            "eps": "6.0",
            "year_high": "200.0",
            "year_low": "150.0",
            "price_avg_50": "190.0",
            "price_avg_200": "180.0",
            "shares_outstanding": 15000000000,
            "earnings_announcement": "2026-07-30T20:00:00.000+0000",
            "timestamp": 1730000000,
        }

    def test_missing_pe_and_eps_become_none(self):
        result = project_quote({"symbol": "BRK.A"})

        assert result["pe_ratio"] is None
        assert result["eps"] is None
        assert result["earnings_announcement"] is None

    def test_null_volume_coerced_to_zero(self):
        result = project_quote(
            {"symbol": "X", "volume": None, "avgVolume": None, "marketCap": None}
        )

        assert result["volume"] == 0
        assert result["avg_volume"] == 0
        assert result["market_cap"] == 0

    def test_real_zero_volume_preserved(self):
        result = project_quote({"symbol": "X", "volume": 0, "avgVolume": 0})

        assert result["volume"] == 0
        assert result["avg_volume"] == 0


class TestProjectProfile:
    def test_full_mapping(self):
        raw = {
            "companyName": "Apple Inc.",
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "description": "Designs and sells smartphones.",
            "ceo": "Tim Cook",
            "website": "https://apple.com",
            "fullTimeEmployees": 164000,
            "beta": 1.25,
            "ipoDate": "1980-12-12",
            "exchangeShortName": "NASDAQ",
            "image": "https://example.com/aapl.png",
        }

        result = project_profile(raw)

        assert result == {
            "name": "Apple Inc.",
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "description": "Designs and sells smartphones.",
            "ceo": "Tim Cook",
            "website": "https://apple.com",
            "employees": 164000,
            "beta": "1.25",
            "ipo_date": "1980-12-12",
            "exchange": "NASDAQ",
            "logo_url": "https://example.com/aapl.png",
        }

    def test_empty_strings_collapse_to_none(self):
        raw = {
            "companyName": "X",
            "sector": "",
            "industry": "",
            "description": "",
            "ceo": "",
            "website": "",
            "beta": None,
            "ipoDate": "",
            "exchangeShortName": "NYSE",
            "image": "",
        }

        result = project_profile(raw)

        assert result["sector"] is None
        assert result["industry"] is None
        assert result["description"] is None
        assert result["ceo"] is None
        assert result["website"] is None
        assert result["beta"] is None
        assert result["ipo_date"] is None
        assert result["logo_url"] is None
        assert result["exchange"] == "NYSE"

    def test_zero_employees_preserved(self):
        # An SPAC / holding company / ETF can legitimately have zero
        # full-time employees; the projection must not collapse 0 to None.
        result = project_profile({"companyName": "X", "fullTimeEmployees": 0})

        assert result["employees"] == 0


class TestProjectRatios:
    def test_full_mapping(self):
        raw = {
            "dividendYieldTTM": 0.005,
            "payoutRatioTTM": 0.16,
            "returnOnEquityTTM": 1.5,
            "returnOnAssetsTTM": 0.27,
            "netProfitMarginTTM": 0.25,
            "operatingProfitMarginTTM": 0.30,
            "grossProfitMarginTTM": 0.45,
            "debtEquityRatioTTM": 1.8,
            "currentRatioTTM": 0.95,
            "priceToBookRatioTTM": 45.0,
            "priceToSalesRatioTTM": 7.5,
            "enterpriseValueMultipleTTM": 22.0,
            "freeCashFlowYieldTTM": 0.04,
            "priceEarningsToGrowthRatioTTM": 2.5,
        }

        result = project_ratios(raw)

        assert result == {
            "dividend_yield": "0.005",
            "payout_ratio": "0.16",
            "roe": "1.5",
            "roa": "0.27",
            "profit_margin": "0.25",
            "operating_margin": "0.3",
            "gross_margin": "0.45",
            "debt_to_equity": "1.8",
            "current_ratio": "0.95",
            "price_to_book": "45.0",
            "price_to_sales": "7.5",
            "ev_to_ebitda": "22.0",
            "free_cash_flow_yield": "0.04",
            "peg_ratio": "2.5",
        }

    def test_empty_dict_yields_all_none(self):
        result = project_ratios({})

        assert all(v is None for v in result.values())


class TestProjectAnalyst:
    def test_full_mapping(self):
        targets = {
            "targetHigh": 240,
            "targetLow": 150,
            "targetConsensus": 200,
            "targetMedian": 195,
        }
        ratings = {
            "strongBuy": 12,
            "buy": 20,
            "hold": 8,
            "sell": 2,
            "strongSell": 1,
        }

        result = project_analyst(targets, ratings)

        assert result == {
            "target_high": "240",
            "target_low": "150",
            "target_consensus": "200",
            "target_median": "195",
            "strong_buy": 12,
            "buy": 20,
            "hold": 8,
            "sell": 2,
            "strong_sell": 1,
        }

    def test_empty_inputs_yield_none_targets_and_counts(self):
        result = project_analyst({}, {})

        assert result == {
            "target_high": None,
            "target_low": None,
            "target_consensus": None,
            "target_median": None,
            "strong_buy": None,
            "buy": None,
            "hold": None,
            "sell": None,
            "strong_sell": None,
        }


class TestStrOrNone:
    def test_none_passes_through(self):
        assert str_or_none(None) is None

    def test_zero_becomes_string_zero(self):
        assert str_or_none(0) == "0"

    def test_float_becomes_string(self):
        assert str_or_none(1.25) == "1.25"


class TestNoneIfBlank:
    def test_none_passes_through(self):
        assert none_if_blank(None) is None

    def test_empty_string_becomes_none(self):
        assert none_if_blank("") is None

    def test_whitespace_string_becomes_none(self):
        assert none_if_blank("   ") is None

    def test_zero_preserved(self):
        assert none_if_blank(0) == 0

    def test_false_preserved(self):
        assert none_if_blank(False) is False

    def test_non_blank_string_preserved(self):
        assert none_if_blank("hi") == "hi"


async def test_close_closes_underlying_client():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    client = _make_client(handler)
    await client.close()

    assert client._client.is_closed


async def test_close_is_idempotent():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    client = _make_client(handler)
    await client.close()
    # Second close must not raise.
    await client.close()

    assert client._client.is_closed


class TestIntOrZero:
    def test_none_becomes_zero(self):
        assert int_or_zero(None) == 0

    def test_real_zero_preserved(self):
        assert int_or_zero(0) == 0

    def test_int_passes_through(self):
        assert int_or_zero(42) == 42

    def test_float_truncates(self):
        assert int_or_zero(3.7) == 3


class TestSentryCapture:
    async def test_non_200_captures_message_with_tags(self, monkeypatch):
        captured: dict = {}

        def fake_capture_message(message, level=None):
            captured["message"] = message
            captured["level"] = level

        class _Scope:
            tags: dict[str, str] = {}
            contexts: dict[str, dict] = {}

            def set_tag(self, key, value):
                self.tags[key] = value

            def set_context(self, key, value):
                self.contexts[key] = value

        scope = _Scope()

        class _ScopeCtx:
            def __enter__(self):
                return scope

            def __exit__(self, *args):
                return False

        monkeypatch.setattr("app.services.fmp.sentry_sdk.new_scope", lambda: _ScopeCtx())
        monkeypatch.setattr(
            "app.services.fmp.sentry_sdk.capture_message", fake_capture_message
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, text="rate limited")

        client = _make_client(handler)
        with pytest.raises(MarketDataUpstreamError):
            await client._request("/v3/quote/AAPL")

        assert captured["message"] == "fmp_api_error"
        assert captured["level"] == "warning"
        assert scope.tags["fmp_path"] == "/v3/quote/AAPL"
        assert scope.tags["fmp_status"] == "429"
        assert scope.contexts["fmp_request"]["status_code"] == 429

    async def test_network_error_captures_exception_with_tags(self, monkeypatch):
        captured: dict = {}

        def fake_capture_exception(exc):
            captured["exc"] = exc

        class _Scope:
            tags: dict[str, str] = {}
            contexts: dict[str, dict] = {}

            def set_tag(self, key, value):
                self.tags[key] = value

            def set_context(self, key, value):
                self.contexts[key] = value

        scope = _Scope()

        class _ScopeCtx:
            def __enter__(self):
                return scope

            def __exit__(self, *args):
                return False

        monkeypatch.setattr("app.services.fmp.sentry_sdk.new_scope", lambda: _ScopeCtx())
        monkeypatch.setattr(
            "app.services.fmp.sentry_sdk.capture_exception", fake_capture_exception
        )

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        client = _make_client(handler)
        with pytest.raises(MarketDataUnavailableError):
            await client._request("/v3/quote/AAPL")

        assert isinstance(captured["exc"], httpx.HTTPError)
        assert scope.tags["fmp_path"] == "/v3/quote/AAPL"
        assert "fmp_request" in scope.contexts


class TestApiKeyRedaction:
    async def test_api_key_not_in_logged_body(self, monkeypatch):
        """The api key must never appear in logs even if FMP echoes it back."""
        api_key = "super-secret-key"
        logged: dict = {}

        def fake_warning(event, **kwargs):
            logged["event"] = event
            logged["kwargs"] = kwargs

        monkeypatch.setattr("app.services.fmp.logger.warning", fake_warning)

        def handler(request: httpx.Request) -> httpx.Response:
            # Simulate FMP echoing the api key in an error body.
            return httpx.Response(401, text=f'{{"error": "Invalid key {api_key}"}}')

        client = FmpClient(
            api_key=api_key,
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        with pytest.raises(MarketDataUpstreamError):
            await client._request("/v3/quote/AAPL")

        assert api_key not in logged["kwargs"]["body"]
        assert "***" in logged["kwargs"]["body"]
