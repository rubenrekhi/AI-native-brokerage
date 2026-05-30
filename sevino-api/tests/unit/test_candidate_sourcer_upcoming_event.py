"""upcoming_event bucket: gated names with earnings/dividends in the window."""

from datetime import date
from unittest.mock import AsyncMock

from app.services.radar_job.candidate_sourcer import (
    BUCKET_UPCOMING_EVENT,
    UPCOMING_EVENT_CAP,
    _upcoming_event_bucket,
)


async def test_only_gated_event_symbols_enter_pool_with_dates(
    radar_asset, run_build_pool
):
    gated = [
        radar_asset("TBIG1", sector="Technology", market_cap=1000),
        radar_asset("TBIG2", sector="Technology", market_cap=900),
        radar_asset("AAPL", sector="Technology", market_cap=100),
        radar_asset("FBIG1", sector="Financials", market_cap=1000),
        radar_asset("FBIG2", sector="Financials", market_cap=900),
        radar_asset("JPM", sector="Financials", market_cap=50),
    ]

    result = await run_build_pool(
        gated,
        earnings=[
            {"symbol": "AAPL", "date": "2026-06-12"},
            {"symbol": "ZZZZ", "date": "2026-06-10"},  # not in gated universe
        ],
        dividends=[{"symbol": "JPM", "date": "2026-06-09"}],
    )

    events = {c.symbol: c for c in result.pool if c.bucket == BUCKET_UPCOMING_EVENT}

    assert set(events) == {"AAPL", "JPM"}
    assert "ZZZZ" not in {c.symbol for c in result.pool}
    assert events["AAPL"].next_earnings_date == date(2026, 6, 12)
    assert events["JPM"].next_dividend_date == date(2026, 6, 9)


async def test_keeps_earliest_event_per_symbol_and_caps_total(radar_asset):
    gated = [
        radar_asset(f"E{i}", sector="Technology", market_cap=1000 - i)
        for i in range(UPCOMING_EVENT_CAP + 5)
    ]
    events = AsyncMock()
    events.upcoming_earnings = AsyncMock(
        return_value=(
            [{"symbol": f"E{i}", "date": "2026-07-01"} for i in range(15)]
            # A second, earlier earnings row for E0 must win.
            + [{"symbol": "E0", "date": "2026-06-15"}]
        )
    )
    events.upcoming_dividends = AsyncMock(return_value=[])

    out = await _upcoming_event_bucket(gated, exclude=set(), events=events)

    assert len(out) == UPCOMING_EVENT_CAP
    e0 = next(c for c in out if c.symbol == "E0")
    assert e0.next_earnings_date == date(2026, 6, 15)
