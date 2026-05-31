from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from app.services.digest.generators.beginner_market import (
    BELLWETHER_SYMBOLS,
    BeginnerMarketGenerator,
)
from app.services.digest.moves import MoveData
from app.services.digest.types import DigestContext, MarketState
from app.services.fmp import StockNewsItem


def _ctx(*, holdings: list[dict] | None = None) -> DigestContext:
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
    prev = Decimal("100")
    pct = Decimal(change_pct)
    change = prev * pct
    return MoveData(
        prev_close=prev,
        current=prev + change,
        change_abs=change,
        change_pct=pct,
        has_premarket_activity=True,
    )


def _news_item(symbol: str, headline: str) -> StockNewsItem:
    return StockNewsItem.model_construct(
        symbol=symbol,
        headline=headline,
        source="Wire",
        url=f"https://example.com/{symbol}",
        published_at=datetime(2026, 5, 29, 12, 0, tzinfo=timezone.utc),
        summary="A factual update.",
        body=None,
        image_url=None,
    )


class _FmpStub:
    def __init__(self, items: list[StockNewsItem]) -> None:
        self.items = items
        self.calls: list[tuple[list[str], datetime, int]] = []

    async def get_stock_news(self, symbols, since, limit=50):
        self.calls.append((list(symbols), since, limit))
        return self.items


async def test_skips_when_user_has_holdings(monkeypatch):
    fmp = _FmpStub([])
    gen = BeginnerMarketGenerator(SimpleNamespace(), fmp=fmp)
    ctx = _ctx(holdings=[{"symbol": "AAPL", "market_value": "100"}])

    candidates = await gen.generate(ctx, AsyncMock(), AsyncMock())

    assert candidates == []
    assert fmp.calls == []


async def test_emits_moves_and_news_when_no_holdings(monkeypatch):
    fmp = _FmpStub([_news_item("AAPL", "Apple unveils something")])
    gen = BeginnerMarketGenerator(SimpleNamespace(), fmp=fmp)

    async def fake_detect(symbols, market_data, *, now=None):
        return {s: _move("0.02" if s == "AAPL" else "0.005") for s in symbols}

    monkeypatch.setattr(
        "app.services.digest.generators.beginner_market.detect_overnight_moves",
        fake_detect,
    )

    async def empty_watchlist(_db, _user_id):
        return []

    monkeypatch.setattr(
        "app.services.digest.generators.beginner_market.RadarItemRepository.list_favorited_for_user",
        empty_watchlist,
    )

    candidates = await gen.generate(_ctx(), AsyncMock(), AsyncMock())

    kinds = [candidate.card.kind for candidate in candidates]
    assert "big_move" in kinds
    assert "news" in kinds
    big_move = next(c for c in candidates if c.card.kind == "big_move")
    assert big_move.card.symbol == "AAPL"
    assert big_move.card.name == "Apple"


async def test_skips_symbols_already_in_watchlist(monkeypatch):
    fmp = _FmpStub([])
    gen = BeginnerMarketGenerator(SimpleNamespace(), fmp=fmp)

    captured_symbols: list[str] = []

    async def fake_detect(symbols, market_data, *, now=None):
        captured_symbols.extend(symbols)
        return {s: _move("0.0") for s in symbols}

    monkeypatch.setattr(
        "app.services.digest.generators.beginner_market.detect_overnight_moves",
        fake_detect,
    )

    async def watchlist_with_aapl(_db, _user_id):
        return [SimpleNamespace(symbol="AAPL")]

    monkeypatch.setattr(
        "app.services.digest.generators.beginner_market.RadarItemRepository.list_favorited_for_user",
        watchlist_with_aapl,
    )

    await gen.generate(_ctx(), AsyncMock(), AsyncMock())

    assert "AAPL" not in captured_symbols
    # Other bellwethers still in the set
    assert any(s in captured_symbols for s in BELLWETHER_SYMBOLS if s != "AAPL")


async def test_news_failure_does_not_crash_generation(monkeypatch):
    class FailingFmp:
        async def get_stock_news(self, *_args, **_kwargs):
            from app.exceptions import MarketDataUpstreamError

            raise MarketDataUpstreamError("boom")

    gen = BeginnerMarketGenerator(SimpleNamespace(), fmp=FailingFmp())

    async def fake_detect(symbols, market_data, *, now=None):
        return {s: _move("0.0") for s in symbols}

    monkeypatch.setattr(
        "app.services.digest.generators.beginner_market.detect_overnight_moves",
        fake_detect,
    )

    async def empty_watchlist(_db, _user_id):
        return []

    monkeypatch.setattr(
        "app.services.digest.generators.beginner_market.RadarItemRepository.list_favorited_for_user",
        empty_watchlist,
    )

    candidates = await gen.generate(_ctx(), AsyncMock(), AsyncMock())

    # Move candidates may still come back; news side returns []
    assert all(candidate.card.kind != "news" for candidate in candidates)
