from datetime import datetime, timezone

import pytest

from app.services.portfolio import PortfolioRange, range_to_alpaca_params


class TestFixedRanges:
    def test_one_day(self):
        assert range_to_alpaca_params(PortfolioRange.ONE_DAY) == {
            "period": "1D",
            "timeframe": "5Min",
        }

    def test_one_week(self):
        assert range_to_alpaca_params(PortfolioRange.ONE_WEEK) == {
            "period": "1W",
            "timeframe": "30Min",
        }

    def test_one_month(self):
        assert range_to_alpaca_params(PortfolioRange.ONE_MONTH) == {
            "period": "1M",
            "timeframe": "1D",
        }

    def test_three_months(self):
        assert range_to_alpaca_params(PortfolioRange.THREE_MONTHS) == {
            "period": "3M",
            "timeframe": "1D",
        }

    def test_six_months(self):
        assert range_to_alpaca_params(PortfolioRange.SIX_MONTHS) == {
            "period": "6M",
            "timeframe": "1D",
        }

    def test_one_year_uses_alpaca_1a_alias(self):
        # Alpaca rejects "1Y" — requires "1A" for annual period.
        assert range_to_alpaca_params(PortfolioRange.ONE_YEAR) == {
            "period": "1A",
            "timeframe": "1D",
        }

    def test_all(self):
        assert range_to_alpaca_params(PortfolioRange.ALL) == {
            "period": "all",
            "timeframe": "1W",
        }


class TestYTD:
    def test_ytd_uses_jan_1_of_injected_year(self):
        now = datetime(2026, 4, 23, 12, 30, tzinfo=timezone.utc)
        assert range_to_alpaca_params(PortfolioRange.YTD, now=now) == {
            "timeframe": "1D",
            "start": "2026-01-01T00:00:00Z",
        }

    def test_ytd_on_jan_1_still_returns_same_year_jan_1(self):
        now = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        assert range_to_alpaca_params(PortfolioRange.YTD, now=now) == {
            "timeframe": "1D",
            "start": "2026-01-01T00:00:00Z",
        }

    def test_ytd_defaults_now_to_utc(self):
        # Without an injected now, YTD should still produce a valid start.
        params = range_to_alpaca_params(PortfolioRange.YTD)
        assert params["timeframe"] == "1D"
        assert params["start"].endswith("-01-01T00:00:00Z")


class TestEnumCoercion:
    def test_coerces_string(self):
        assert PortfolioRange("1D") is PortfolioRange.ONE_DAY
        assert PortfolioRange("YTD") is PortfolioRange.YTD

    def test_rejects_invalid_string(self):
        with pytest.raises(ValueError):
            PortfolioRange("invalid")

    def test_is_str_subclass(self):
        # StrEnum members double as strings for easy use in query params.
        assert PortfolioRange.ONE_DAY == "1D"
