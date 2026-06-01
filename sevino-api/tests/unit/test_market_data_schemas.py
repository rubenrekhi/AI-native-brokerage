"""Unit tests for app.schemas.market_data."""

from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from app.schemas.market_data import (
    BatchQuoteResponse,
    ChartResponse,
    ChartTimeframe,
    FinancialTrendPoint,
    MarketStatusResponse,
    PeerComparison,
    PriceBar,
    QuarterlyEarning,
    StockAnalyst,
    StockEarnings,
    StockFinancials,
    StockInfoResponse,
    StockProfile,
    StockQuote,
    StockRatios,
    StockSectorContext,
    StockValuation,
    ValuationHistoryPoint,
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


class TestStockFinancials:
    def test_empty_dict_yields_all_none_and_empty_trend(self):
        result = StockFinancials.model_validate({})

        assert result.revenue is None
        assert result.net_debt is None
        assert result.revenue_growth_yoy is None
        assert result.annual_trend == []

    def test_partial_fields_validate(self):
        result = StockFinancials.model_validate(
            {
                "revenue": "400000000000",
                "total_debt": "110000000000",
                "fiscal_period": "TTM through 2026-03-28",
            }
        )

        assert result.revenue == "400000000000"
        assert result.total_debt == "110000000000"
        assert result.fiscal_period == "TTM through 2026-03-28"

    def test_annual_trend_points_validate(self):
        result = StockFinancials.model_validate(
            {
                "annual_trend": [
                    {"fiscal_year": "2025", "revenue": "400000000000"},
                    {"fiscal_year": "2024", "revenue": "380000000000"},
                ]
            }
        )

        assert len(result.annual_trend) == 2
        assert isinstance(result.annual_trend[0], FinancialTrendPoint)
        assert result.annual_trend[0].fiscal_year == "2025"


class TestStockValuation:
    def test_empty_dict_yields_all_none_and_empty_history(self):
        result = StockValuation.model_validate({})

        assert result.pe is None
        assert result.sector_pe is None
        assert result.pe_vs_sector is None
        assert result.pe_5y_median is None
        assert result.valuation_history == []

    def test_partial_fields_validate(self):
        result = StockValuation.model_validate(
            {
                "pe": "25.0",
                "sector_pe": "50.0",
                "pe_vs_sector": "-0.5",
                "as_of_date": "2026-05-29",
            }
        )

        assert result.pe == "25.0"
        assert result.sector_pe == "50.0"
        assert result.pe_vs_sector == "-0.5"
        assert result.as_of_date == "2026-05-29"

    def test_history_points_validate(self):
        result = StockValuation.model_validate(
            {
                "valuation_history": [
                    {"fiscal_year": "2025", "pe": "30.0", "ps": "9.0", "pb": "50.0"},
                    {"fiscal_year": "2024", "pe": "20.0"},
                ]
            }
        )

        assert len(result.valuation_history) == 2
        assert isinstance(result.valuation_history[0], ValuationHistoryPoint)
        assert result.valuation_history[0].pb == "50.0"


class TestStockEarnings:
    def test_empty_dict_yields_all_none_and_empty_quarterly(self):
        result = StockEarnings.model_validate({})

        assert result.next_period_end is None
        assert result.eps_estimate_avg is None
        assert result.num_analysts is None
        assert result.avg_post_earnings_move_pct is None
        assert result.events_measured is None
        assert result.quarterly == []

    def test_partial_fields_validate(self):
        result = StockEarnings.model_validate(
            {
                "next_period_end": "2026-09-28",
                "eps_estimate_avg": "1.5",
                "num_analysts": 12,
                "events_measured": 8,
            }
        )

        assert result.next_period_end == "2026-09-28"
        assert result.eps_estimate_avg == "1.5"
        assert result.num_analysts == 12
        assert result.events_measured == 8

    def test_quarterly_points_validate(self):
        result = StockEarnings.model_validate(
            {
                "quarterly": [
                    {"report_date": "2026-04-30", "eps_actual": "2.01",
                     "eps_surprise_pct": "0.0308", "price_move_pct": "0.05"},
                    {"report_date": "2026-01-29"},
                ]
            }
        )

        assert len(result.quarterly) == 2
        assert isinstance(result.quarterly[0], QuarterlyEarning)
        assert result.quarterly[0].eps_surprise_pct == "0.0308"
        assert result.quarterly[1].eps_actual is None


class TestStockSectorContext:
    def test_empty_dict_yields_all_none_and_empty_peers(self):
        result = StockSectorContext.model_validate({})

        assert result.sector is None
        assert result.sector_vs_market_pct is None
        assert result.peers == []
        assert result.peer_count is None
        assert result.rank_by_change is None

    def test_partial_fields_validate(self):
        result = StockSectorContext.model_validate(
            {
                "sector": "Technology",
                "sector_change_pct": "0.74",
                "market_change_pct": "-0.32",
                "sector_vs_market_pct": "1.06",
            }
        )

        assert result.sector == "Technology"
        assert result.sector_vs_market_pct == "1.06"

    def test_peer_points_validate(self):
        result = StockSectorContext.model_validate(
            {
                "peers": [
                    {
                        "symbol": "MSFT",
                        "company_name": "Microsoft Corporation",
                        "price": "450.24",
                        "change_pct": "0.85",
                        "market_cap": 3344576323200,
                    }
                ],
                "peer_count": 1,
                "rank_by_change": 2,
                "rank_by_market_cap": 1,
            }
        )

        assert isinstance(result.peers[0], PeerComparison)
        assert result.peers[0].symbol == "MSFT"
        assert result.peers[0].market_cap == 3344576323200
        assert result.rank_by_change == 2


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

    def test_financials_defaults_to_empty_block_when_omitted(self):
        data = {
            "quote": _quote(),
            "profile": {"name": "Apple Inc.", "exchange": "NASDAQ"},
            "ratios": {},
            "analyst": {},
        }

        result = StockInfoResponse.model_validate(data)

        assert isinstance(result.financials, StockFinancials)
        assert result.financials.revenue is None

    def test_financials_block_validates_when_present(self):
        data = {
            "quote": _quote(),
            "profile": {"name": "Apple Inc.", "exchange": "NASDAQ"},
            "ratios": {},
            "financials": {"revenue": "400000000000"},
            "analyst": {},
        }

        result = StockInfoResponse.model_validate(data)

        assert result.financials.revenue == "400000000000"

    def test_valuation_defaults_to_empty_block_when_omitted(self):
        data = {
            "quote": _quote(),
            "profile": {"name": "Apple Inc.", "exchange": "NASDAQ"},
            "ratios": {},
            "analyst": {},
        }

        result = StockInfoResponse.model_validate(data)

        assert isinstance(result.valuation, StockValuation)
        assert result.valuation.pe is None

    def test_valuation_block_validates_when_present(self):
        data = {
            "quote": _quote(),
            "profile": {"name": "Apple Inc.", "exchange": "NASDAQ"},
            "ratios": {},
            "valuation": {"pe": "25.0", "sector_pe": "50.0"},
            "analyst": {},
        }

        result = StockInfoResponse.model_validate(data)

        assert result.valuation.pe == "25.0"
        assert result.valuation.sector_pe == "50.0"

    def test_earnings_defaults_to_empty_block_when_omitted(self):
        data = {
            "quote": _quote(),
            "profile": {"name": "Apple Inc.", "exchange": "NASDAQ"},
            "ratios": {},
            "analyst": {},
        }

        result = StockInfoResponse.model_validate(data)

        assert isinstance(result.earnings, StockEarnings)
        assert result.earnings.next_period_end is None

    def test_earnings_block_validates_when_present(self):
        data = {
            "quote": _quote(),
            "profile": {"name": "Apple Inc.", "exchange": "NASDAQ"},
            "ratios": {},
            "earnings": {"next_period_end": "2026-09-28", "num_analysts": 12},
            "analyst": {},
        }

        result = StockInfoResponse.model_validate(data)

        assert result.earnings.next_period_end == "2026-09-28"
        assert result.earnings.num_analysts == 12

    def test_sector_context_defaults_to_empty_block_when_omitted(self):
        data = {
            "quote": _quote(),
            "profile": {"name": "Apple Inc.", "exchange": "NASDAQ"},
            "ratios": {},
            "analyst": {},
        }

        result = StockInfoResponse.model_validate(data)

        assert isinstance(result.sector_context, StockSectorContext)
        assert result.sector_context.peers == []
        assert result.sector_context.sector_vs_market_pct is None

    def test_sector_context_block_validates_when_present(self):
        data = {
            "quote": _quote(),
            "profile": {"name": "Apple Inc.", "exchange": "NASDAQ"},
            "ratios": {},
            "sector_context": {
                "sector": "Technology",
                "sector_vs_market_pct": "1.06",
                "peers": [{"symbol": "MSFT", "change_pct": "0.85"}],
                "peer_count": 1,
            },
            "analyst": {},
        }

        result = StockInfoResponse.model_validate(data)

        assert result.sector_context.sector_vs_market_pct == "1.06"
        assert result.sector_context.peers[0].symbol == "MSFT"

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
