import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.schemas.fmp import EarningsCalendarItem, HistoricalEarningsItem
from app.services.digest.generators._common import held_positions, position_weight
from app.services.digest.generators.earnings_results import (
    EarningsResultsGenerator,
    grade_earnings,
)
from app.services.digest.generators.upcoming_earnings import (
    UpcomingEarningsGenerator,
    relative_label,
)
from app.services.digest.types import DigestContext, MarketState


def _ctx(
    *,
    as_of: datetime = datetime(2026, 5, 1, 13, 30, tzinfo=timezone.utc),
    holdings: list[dict] | None = None,
    portfolio_snapshot: dict | None = None,
) -> DigestContext:
    return DigestContext(
        user_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        portfolio_snapshot=portfolio_snapshot or {"equity": "1000.00"},
        holdings=holdings
        if holdings is not None
        else [
            {
                "symbol": "AAPL",
                "name": "Apple Inc.",
                "market_value": "250.00",
            }
        ],
        financial_profile=None,
        market_state=MarketState(as_of=as_of, session="pre"),
    )


def _historical(
    *,
    eps_actual: str,
    eps_estimate: str = "100",
    revenue_actual: str,
    revenue_estimate: str = "100",
    reported_date: date = date(2026, 4, 30),
    report_time: str = "amc",
) -> HistoricalEarningsItem:
    return HistoricalEarningsItem(
        symbol="AAPL",
        reported_date=reported_date,
        time=report_time,
        eps_actual=Decimal(eps_actual),
        eps_estimate=Decimal(eps_estimate),
        revenue_actual=Decimal(revenue_actual),
        revenue_estimate=Decimal(revenue_estimate),
    )


@pytest.mark.parametrize(
    ("eps_actual", "revenue_actual", "expected_grade"),
    [
        ("106", "107", "A+"),
        ("103", "104", "A"),
        ("101", "101.5", "A-"),
        ("103", "100.2", "B"),
        ("100.2", "99.8", "C"),
        ("99", "100.2", "D"),
        ("99", "98", "F"),
    ],
)
def test_grade_earnings_covers_all_grades(
    eps_actual, revenue_actual, expected_grade
):
    result = grade_earnings(
        _historical(eps_actual=eps_actual, revenue_actual=revenue_actual)
    )

    assert result is not None
    assert result.grade == expected_grade
    assert len(result.highlights) == 2


async def test_earnings_results_emits_recent_report_for_holding():
    fmp = AsyncMock()
    fmp.get_historical_earnings.return_value = [
        _historical(eps_actual="106", revenue_actual="107")
    ]
    generator = EarningsResultsGenerator(fmp=fmp)

    candidates = await generator.generate(_ctx())

    assert len(candidates) == 1
    fmp.get_historical_earnings.assert_awaited_once_with("AAPL", limit=1)
    card = candidates[0].card
    assert card.kind == "earnings_result"
    assert card.symbol == "AAPL"
    assert card.name == "Apple Inc."
    assert card.grade == "A+"
    assert card.stock_reaction_pct is None
    assert candidates[0].magnitude_score == pytest.approx(0.0125)


async def test_earnings_results_ignores_reports_before_prior_close():
    fmp = AsyncMock()
    fmp.get_historical_earnings.return_value = [
        _historical(
            eps_actual="106",
            revenue_actual="107",
            reported_date=date(2026, 4, 29),
        )
    ]
    generator = EarningsResultsGenerator(fmp=fmp)

    assert await generator.generate(_ctx()) == []


async def test_earnings_results_noops_without_holdings():
    fmp = AsyncMock()
    generator = EarningsResultsGenerator(fmp=fmp)

    assert await generator.generate(_ctx(holdings=[])) == []
    fmp.get_historical_earnings.assert_not_called()


def test_position_weight_fallback_uses_deduped_holdings():
    ctx = _ctx(
        portfolio_snapshot={"equity": "0"},
        holdings=[
            {"symbol": "AAPL", "market_value": "250.00"},
            {"symbol": "aapl", "market_value": "250.00"},
            {"symbol": "MSFT", "market_value": "750.00"},
        ],
    )

    assert position_weight(ctx, held_positions(ctx)[0]) == Decimal("0.25")


def _calendar(symbol: str, reported_date: date) -> EarningsCalendarItem:
    return EarningsCalendarItem(
        symbol=symbol,
        reported_date=reported_date,
        time="bmo",
        eps_estimate=Decimal("1.00"),
        revenue_estimate=Decimal("1000000000"),
    )


async def test_upcoming_earnings_emits_one_card_per_held_upcoming_report():
    today = date(2026, 7, 27)
    as_of = datetime(2026, 7, 27, 13, 0, tzinfo=timezone.utc)
    fmp = AsyncMock()
    fmp.get_earnings_calendar.return_value = [
        _calendar("AAPL", today),
        _calendar("MSFT", today + timedelta(days=1)),
        _calendar("NVDA", today + timedelta(days=2)),
    ]
    generator = UpcomingEarningsGenerator(fmp=fmp)

    candidates = await generator.generate(
        _ctx(
            as_of=as_of,
            holdings=[
                {
                    "symbol": "AAPL",
                    "name": "Apple Inc.",
                    "market_value": "250.00",
                },
                {
                    "symbol": "MSFT",
                    "name": "Microsoft Corporation",
                    "market_value": "100.00",
                },
            ],
        )
    )

    assert [candidate.card.symbol for candidate in candidates] == [
        "AAPL",
        "MSFT",
    ]
    assert [candidate.card.relative_label for candidate in candidates] == [
        "Today",
        "Tomorrow",
    ]
    fmp.get_earnings_calendar.assert_awaited_once_with(
        today, today + timedelta(days=7)
    )


async def test_upcoming_earnings_noops_when_no_held_symbols_report():
    today = date(2026, 7, 27)
    fmp = AsyncMock()
    fmp.get_earnings_calendar.return_value = [
        _calendar("MSFT", today + timedelta(days=1))
    ]
    generator = UpcomingEarningsGenerator(fmp=fmp)

    assert await generator.generate(_ctx()) == []


def test_relative_label_for_all_supported_offsets():
    today = date(2026, 7, 27)

    assert relative_label(0, today=today) == "Today"
    assert relative_label(1, today=today) == "Tomorrow"
    assert relative_label(2, today=today) == "Wednesday"
    assert relative_label(6, today=today) == "Sunday"
    assert relative_label(7, today=today) == "in 7 days"
