"""Unit tests for app.schemas.market_data."""

from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from app.schemas.market_data import (
    BatchQuoteResponse,
    ChartResponse,
    ChartTimeframe,
    MarketStatusResponse,
    PriceBar,
    StockAnalyst,
    StockInfoResponse,
    StockProfile,
    StockQuote,
    StockRatios,
)


def _assert_missing_field(
    model: type[BaseModel],
    data: dict[str, Any],
    loc: str | tuple[str | int, ...],
) -> None:
    """Validate `data` against `model` and assert a missing-field error at
    `loc`. Asserts `errors()` structurally rather than string-matching,
    since Pydantic's error rendering includes the input dict and would
    false-positive on any field whose name appears as a substring
    elsewhere (e.g. `volume` in `avg_volume`).
    """
    expected_loc = (loc,) if isinstance(loc, str) else loc
    with pytest.raises(ValidationError) as exc_info:
        model.model_validate(data)
    matching = [
        err
        for err in exc_info.value.errors()
        if err["type"] == "missing" and err["loc"] == expected_loc
    ]
    assert matching, (
        f"expected a 'missing' error at {expected_loc!r}, "
        f"got {exc_info.value.errors()}"
    )


def _quote(**overrides) -> dict:
    base = {
        "symbol": "AAPL",
        "name": "Apple Inc.",
        "price": "189.84",
        "change": "2.31",
        "change_percent": "1.23",
        "open": "188.5",
        "day_high": "191.0",
        "day_low": "188.0",
        "previous_close": "187.53",
        "volume": 54321000,
        "avg_volume": 60000000,
        "market_cap": 2900000000000,
        "pe_ratio": "31.2",
        "eps": "6.08",
        "year_high": "199.62",
        "year_low": "164.08",
        "price_avg_50": "185.0",
        "price_avg_200": "180.0",
        "shares_outstanding": 15300000000,
        "earnings_announcement": "2026-07-24T00:00:00.000+0000",
        "timestamp": 1715100000,
    }
    return {**base, **overrides}


def _price_bar(**overrides) -> dict:
    base = {
        "timestamp": "2026-05-07T15:00:00Z",
        "open": "195.0",
        "high": "196.5",
        "low": "194.0",
        "close": "195.5",
        "volume": 1000000,
        "vwap": "195.3",
        "trade_count": 5000,
    }
    return {**base, **overrides}


class TestChartTimeframe:
    def test_invalid_string_raises(self):
        with pytest.raises(ValueError):
            ChartTimeframe("10Y")


class TestStockQuote:
    def test_well_formed_dict_validates(self):
        result = StockQuote.model_validate(_quote())

        assert result.symbol == "AAPL"
        assert result.price == "189.84"
        assert result.change_percent == "1.23"
        assert result.market_cap == 2900000000000

    @pytest.mark.parametrize(
        "field",
        [
            "symbol",
            "name",
            "price",
            "change",
            "change_percent",
            "open",
            "day_high",
            "day_low",
            "previous_close",
            "volume",
            "avg_volume",
            "market_cap",
            "year_high",
            "year_low",
            "price_avg_50",
            "price_avg_200",
            "shares_outstanding",
            "timestamp",
        ],
    )
    def test_missing_required_field_raises(self, field):
        data = _quote()
        del data[field]
        _assert_missing_field(StockQuote, data, field)

    @pytest.mark.parametrize(
        "field", ["pe_ratio", "eps", "earnings_announcement"]
    )
    def test_optional_field_accepts_none(self, field):
        result = StockQuote.model_validate(_quote(**{field: None}))

        assert getattr(result, field) is None


class TestStockProfile:
    def test_minimal_required_fields(self):
        result = StockProfile.model_validate(
            {"name": "Apple Inc.", "exchange": "NASDAQ"}
        )

        assert result.name == "Apple Inc."
        assert result.exchange == "NASDAQ"

    @pytest.mark.parametrize("field", ["name", "exchange"])
    def test_missing_required_field_raises(self, field):
        data = {"name": "Apple Inc.", "exchange": "NASDAQ"}
        del data[field]
        _assert_missing_field(StockProfile, data, field)


class TestStockRatios:
    def test_partial_fields_validate(self):
        result = StockRatios.model_validate(
            {"dividend_yield": "0.005", "roe": "1.45"}
        )

        assert result.dividend_yield == "0.005"
        assert result.roe == "1.45"


class TestStockAnalyst:
    def test_partial_fields_validate(self):
        result = StockAnalyst.model_validate(
            {"target_consensus": "198", "strong_buy": 12, "sell": 2}
        )

        assert result.target_consensus == "198"
        assert result.strong_buy == 12
        assert result.sell == 2


class TestStockInfoResponse:
    def test_well_formed_dict_validates(self):
        data = {
            "quote": _quote(),
            "profile": {"name": "Apple Inc.", "exchange": "NASDAQ"},
            "ratios": {},
            "analyst": {},
        }

        result = StockInfoResponse.model_validate(data)

        assert result.quote.symbol == "AAPL"
        assert result.profile.name == "Apple Inc."

    @pytest.mark.parametrize(
        "field", ["quote", "profile", "ratios", "analyst"]
    )
    def test_missing_required_field_raises(self, field):
        data = {
            "quote": _quote(),
            "profile": {"name": "Apple Inc.", "exchange": "NASDAQ"},
            "ratios": {},
            "analyst": {},
        }
        del data[field]
        _assert_missing_field(StockInfoResponse, data, field)

    def test_invalid_nested_quote_raises_at_nested_loc(self):
        data = {
            "quote": {"name": "Apple Inc."},
            "profile": {"name": "Apple Inc.", "exchange": "NASDAQ"},
            "ratios": {},
            "analyst": {},
        }
        _assert_missing_field(StockInfoResponse, data, ("quote", "symbol"))


class TestBatchQuoteResponse:
    def test_empty_list_validates(self):
        result = BatchQuoteResponse.model_validate({"quotes": []})

        assert result.quotes == []

    def test_list_of_quotes_validates(self):
        result = BatchQuoteResponse.model_validate(
            {"quotes": [_quote(), _quote(symbol="MSFT", name="Microsoft Corp.")]}
        )

        assert [q.symbol for q in result.quotes] == ["AAPL", "MSFT"]


class TestPriceBar:
    def test_well_formed_dict_validates(self):
        result = PriceBar.model_validate(_price_bar())

        assert result.timestamp == "2026-05-07T15:00:00Z"
        assert result.volume == 1000000
        assert result.trade_count == 5000

    @pytest.mark.parametrize(
        "field",
        [
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "vwap",
            "trade_count",
        ],
    )
    def test_missing_required_field_raises(self, field):
        data = _price_bar()
        del data[field]
        _assert_missing_field(PriceBar, data, field)


class TestChartResponse:
    @pytest.mark.parametrize(
        "wire,member",
        [
            ("1D", ChartTimeframe.ONE_DAY),
            ("1W", ChartTimeframe.ONE_WEEK),
            ("1M", ChartTimeframe.ONE_MONTH),
            ("3M", ChartTimeframe.THREE_MONTHS),
            ("6M", ChartTimeframe.SIX_MONTHS),
            ("1Y", ChartTimeframe.ONE_YEAR),
            ("5Y", ChartTimeframe.FIVE_YEARS),
        ],
    )
    def test_timeframe_wire_value_parses(self, wire, member):
        result = ChartResponse.model_validate(
            {"symbol": "AAPL", "timeframe": wire, "bars": []}
        )

        assert result.symbol == "AAPL"
        assert result.timeframe is member
        assert result.bars == []

    def test_invalid_timeframe_raises(self):
        with pytest.raises(ValidationError):
            ChartResponse.model_validate(
                {"symbol": "AAPL", "timeframe": "10Y", "bars": []}
            )

    def test_validates_non_empty_bars_list(self):
        result = ChartResponse.model_validate(
            {"symbol": "AAPL", "timeframe": "1M", "bars": [_price_bar()]}
        )

        assert len(result.bars) == 1
        assert result.bars[0].close == "195.5"

    def test_invalid_bar_raises_at_nested_loc(self):
        data = {
            "symbol": "AAPL",
            "timeframe": "1M",
            "bars": [_price_bar(), {"open": "1"}],
        }
        _assert_missing_field(ChartResponse, data, ("bars", 1, "timestamp"))


class TestMarketStatusResponse:
    def test_well_formed_dict_validates(self):
        result = MarketStatusResponse.model_validate(
            {
                "is_open": True,
                "next_open": "2026-05-08T13:30:00Z",
                "next_close": "2026-05-07T20:00:00Z",
                "timestamp": "2026-05-07T15:00:00Z",
            }
        )

        assert result.is_open is True
        assert result.next_open == "2026-05-08T13:30:00Z"

    @pytest.mark.parametrize(
        "field", ["is_open", "next_open", "next_close", "timestamp"]
    )
    def test_missing_required_field_raises(self, field):
        data = {
            "is_open": True,
            "next_open": "2026-05-08T13:30:00Z",
            "next_close": "2026-05-07T20:00:00Z",
            "timestamp": "2026-05-07T15:00:00Z",
        }
        del data[field]
        _assert_missing_field(MarketStatusResponse, data, field)
