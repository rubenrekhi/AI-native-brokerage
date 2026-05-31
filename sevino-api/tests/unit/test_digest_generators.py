from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from app.repositories.radar_item import RadarItemRepository
from app.services.digest.generators import (
    EARNINGS_GENERATORS,
    FMP_GENERATORS,
    KNOWN_GENERATORS,
    PRICE_MOVE_GENERATORS,
    create_known_generators,
)
from app.services.digest.generators.big_moves import BigMovesGenerator
from app.services.digest.generators.market_context import MarketContextGenerator
from app.services.digest.generators.watchlist import WatchlistMovesGenerator
from app.services.digest.moves import MoveData
from app.services.digest.types import DigestContext, MarketState


class _MarketData:
    pass


class _Fmp:
    pass


def _ctx(
    *,
    holdings: list[dict] | None = None,
) -> DigestContext:
    return DigestContext(
        user_id=uuid4(),
        portfolio_snapshot=None,
        holdings=holdings or [],
        financial_profile=None,
        market_state=MarketState(
            as_of=datetime(2026, 5, 29, 13, 0, tzinfo=timezone.utc),
            session="pre",
        ),
    )


def _move(change_pct: str) -> MoveData:
    prev_close = Decimal("100")
    pct = Decimal(change_pct)
    change_abs = prev_close * pct
    return MoveData(
        prev_close=prev_close,
        current=prev_close + change_abs,
        change_abs=change_abs,
        change_pct=pct,
        has_premarket_activity=True,
    )


async def test_big_moves_emit_nothing_below_threshold(monkeypatch):
    async def fake_detect(symbols, market_data, *, now=None):
        assert symbols == ["AAPL"]
        assert now == datetime(2026, 5, 29, 13, 0, tzinfo=timezone.utc)
        return {"AAPL": _move("0.019")}

    monkeypatch.setattr(
        "app.services.digest.generators.big_moves.detect_overnight_moves",
        fake_detect,
    )

    candidates = await BigMovesGenerator(_MarketData()).generate(
        _ctx(holdings=[{"symbol": "AAPL", "market_value": "1000"}]),
        object(),
        object(),
    )

    assert candidates == []


async def test_big_move_magnitude_is_threshold_relative_and_weighted(monkeypatch):
    async def fake_detect(symbols, market_data, *, now=None):
        assert symbols == ["AAPL", "MSFT"]
        return {"AAPL": _move("0.05"), "MSFT": _move("0.05")}

    monkeypatch.setattr(
        "app.services.digest.generators.big_moves.detect_overnight_moves",
        fake_detect,
    )

    candidates = await BigMovesGenerator(_MarketData()).generate(
        _ctx(
            holdings=[
                {"symbol": "AAPL", "name": "Apple Inc.", "market_value": "1000"},
                {"symbol": "MSFT", "name": "Microsoft", "market_value": "100"},
            ]
        ),
        object(),
        object(),
    )

    by_symbol = {candidate.card.symbol: candidate for candidate in candidates}
    assert by_symbol["AAPL"].magnitude_score == 2.5
    assert by_symbol["MSFT"].magnitude_score == 1.25
    assert by_symbol["AAPL"].card.reason is None


async def test_watchlist_moves_emit_nothing_below_threshold(monkeypatch):
    async def fake_favorites(db, user_id):
        return [SimpleNamespace(symbol="AMD", company_name="Advanced Micro Devices")]

    async def fake_detect(symbols, market_data, *, now=None):
        assert symbols == ["AMD"]
        assert now == datetime(2026, 5, 29, 13, 0, tzinfo=timezone.utc)
        return {"AMD": _move("0.029")}

    monkeypatch.setattr(
        RadarItemRepository,
        "list_favorited_for_user",
        fake_favorites,
    )
    monkeypatch.setattr(
        "app.services.digest.generators.watchlist.detect_overnight_moves",
        fake_detect,
    )

    candidates = await WatchlistMovesGenerator(_MarketData()).generate(
        _ctx(), object(), object()
    )

    assert candidates == []


async def test_watchlist_magnitude_ignores_position_size(monkeypatch):
    async def fake_favorites(db, user_id):
        return [
            SimpleNamespace(symbol="AMD", company_name="Advanced Micro Devices"),
            SimpleNamespace(symbol="SNOW", company_name="Snowflake"),
        ]

    async def fake_detect(symbols, market_data, *, now=None):
        assert symbols == ["AMD", "SNOW"]
        return {"AMD": _move("0.04"), "SNOW": _move("-0.04")}

    monkeypatch.setattr(
        RadarItemRepository,
        "list_favorited_for_user",
        fake_favorites,
    )
    monkeypatch.setattr(
        "app.services.digest.generators.watchlist.detect_overnight_moves",
        fake_detect,
    )

    candidates = await WatchlistMovesGenerator(_MarketData()).generate(
        _ctx(holdings=[{"symbol": "AMD", "market_value": "100000"}]),
        object(),
        object(),
    )

    assert [round(candidate.magnitude_score, 2) for candidate in candidates] == [
        1.33,
        1.33,
    ]
    assert [candidate.card.symbol for candidate in candidates] == ["AMD", "SNOW"]


async def test_market_context_always_emits_low_magnitude_on_quiet_day(monkeypatch):
    async def fake_detect(symbols, market_data, *, now=None):
        assert symbols == ["SPY", "QQQ"]
        assert now == datetime(2026, 5, 29, 13, 0, tzinfo=timezone.utc)
        return {"SPY": _move("0.001"), "QQQ": _move("-0.002")}

    monkeypatch.setattr(
        "app.services.digest.generators.market_context.detect_overnight_moves",
        fake_detect,
    )

    candidates = await MarketContextGenerator(_MarketData()).generate(
        _ctx(), object(), object()
    )

    assert len(candidates) == 1
    assert candidates[0].card.kind == "market_context"
    assert candidates[0].card.direction == "mixed"
    assert candidates[0].card.summary == "S&P 500 up 0.1%, Nasdaq down 0.2%"
    assert candidates[0].magnitude_score < 1


async def test_market_context_magnitude_rises_for_index_moves(monkeypatch):
    async def fake_detect(symbols, market_data, *, now=None):
        return {"SPY": _move("0.012"), "QQQ": _move("0.015")}

    monkeypatch.setattr(
        "app.services.digest.generators.market_context.detect_overnight_moves",
        fake_detect,
    )

    candidates = await MarketContextGenerator(_MarketData()).generate(
        _ctx(), object(), object()
    )

    assert candidates[0].card.direction == "up"
    assert candidates[0].magnitude_score == 2


def test_price_move_generators_are_registered():
    assert [generator.__name__ for generator in PRICE_MOVE_GENERATORS] == [
        "BigMovesGenerator",
        "WatchlistMovesGenerator",
        "MarketContextGenerator",
    ]


def test_known_generators_include_registered_generator_groups():
    assert [generator.__name__ for generator in KNOWN_GENERATORS] == [
        "DividendsGenerator",
        "PendingOrdersGenerator",
        "RadarRefreshGenerator",
        "BigMovesGenerator",
        "WatchlistMovesGenerator",
        "MarketContextGenerator",
        "EarningsResultsGenerator",
        "UpcomingEarningsGenerator",
        "NewsGenerator",
    ]


def test_earnings_generators_are_registered():
    assert [generator.__name__ for generator in EARNINGS_GENERATORS] == [
        "EarningsResultsGenerator",
        "UpcomingEarningsGenerator",
    ]


def test_fmp_generators_are_registered():
    assert [generator.__name__ for generator in FMP_GENERATORS] == [
        "EarningsResultsGenerator",
        "UpcomingEarningsGenerator",
        "NewsGenerator",
    ]


def test_create_known_generators_adds_price_moves_with_market_data():
    generators = create_known_generators(_MarketData())

    assert [generator.__class__.__name__ for generator in generators] == [
        "DividendsGenerator",
        "PendingOrdersGenerator",
        "RadarRefreshGenerator",
        "BigMovesGenerator",
        "WatchlistMovesGenerator",
        "MarketContextGenerator",
    ]


def test_create_known_generators_adds_fmp_generators_with_fmp():
    generators = create_known_generators(fmp=_Fmp())

    assert [generator.__class__.__name__ for generator in generators] == [
        "DividendsGenerator",
        "PendingOrdersGenerator",
        "RadarRefreshGenerator",
        "EarningsResultsGenerator",
        "UpcomingEarningsGenerator",
        "NewsGenerator",
    ]
