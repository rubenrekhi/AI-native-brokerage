"""Digest generator for broad-market context."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.alpaca_broker import AlpacaBrokerService
from app.services.digest.cards import MarketContextCard
from app.services.digest.moves import (
    INDEX_MOVE_PCT,
    MoveData,
    StockBarsProvider,
    detect_overnight_moves,
)
from app.services.digest.types import CardCandidate, DigestContext

_SPY = "SPY"
_QQQ = "QQQ"
_ZERO_MOVE = MoveData(
    prev_close=Decimal("0"),
    current=Decimal("0"),
    change_abs=Decimal("0"),
    change_pct=Decimal("0"),
    has_premarket_activity=False,
)


class MarketContextGenerator:
    def __init__(self, market_data: StockBarsProvider) -> None:
        self._market_data = market_data

    async def generate(
        self,
        ctx: DigestContext,
        _db: AsyncSession,
        _alpaca: AlpacaBrokerService,
    ) -> list[CardCandidate]:
        moves = await detect_overnight_moves(
            [_SPY, _QQQ], self._market_data, now=ctx.market_state.as_of
        )
        spy = moves.get(_SPY, _ZERO_MOVE)
        qqq = moves.get(_QQQ, _ZERO_MOVE)
        if max(abs(spy.change_pct), abs(qqq.change_pct)) < INDEX_MOVE_PCT:
            return []
        direction = _direction(spy.change_pct, qqq.change_pct)
        card = MarketContextCard(
            direction=direction,
            sp500_change_pct=spy.change_pct,
            nasdaq_change_pct=qqq.change_pct,
            summary=(
                f"S&P 500 {_percent_phrase(spy.change_pct)}, "
                f"Nasdaq {_percent_phrase(qqq.change_pct)}"
            ),
            related_symbols=[_SPY, _QQQ],
            card_context={"generator": "market_context"},
        )
        return [
            CardCandidate(
                card=card,
                event_type="market_context",
                magnitude_score=_magnitude(spy.change_pct, qqq.change_pct),
                related_symbols=[_SPY, _QQQ],
                dedupe_key="market_context:SPY:QQQ",
            )
        ]


def _direction(sp500_change_pct: Decimal, nasdaq_change_pct: Decimal) -> str:
    if sp500_change_pct > 0 and nasdaq_change_pct > 0:
        return "up"
    if sp500_change_pct < 0 and nasdaq_change_pct < 0:
        return "down"
    return "mixed"


def _magnitude(sp500_change_pct: Decimal, nasdaq_change_pct: Decimal) -> float:
    max_abs = max(abs(sp500_change_pct), abs(nasdaq_change_pct))
    return float(max_abs / INDEX_MOVE_PCT)


def _percent_phrase(change_pct: Decimal) -> str:
    percent = abs(change_pct * Decimal("100")).quantize(Decimal("0.1"))
    if change_pct > 0:
        return f"up {percent}%"
    if change_pct < 0:
        return f"down {percent}%"
    return "flat 0.0%"
