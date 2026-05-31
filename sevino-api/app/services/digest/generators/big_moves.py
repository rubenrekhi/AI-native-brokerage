"""Digest generator for notable moves in the user's holdings."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.alpaca_broker import AlpacaBrokerService
from app.services.digest.cards import BigMoveCard
from app.services.digest.moves import (
    HOLDING_MOVE_PCT,
    StockBarsProvider,
    detect_overnight_moves,
    is_meaningful_move,
)
from app.services.digest.types import CardCandidate, DigestContext

_POSITION_WEIGHT_UNIT = Decimal("1000")
_MIN_POSITION_WEIGHT = Decimal("0.5")
_MAX_POSITION_WEIGHT = Decimal("3")


class BigMovesGenerator:
    def __init__(self, market_data: StockBarsProvider) -> None:
        self._market_data = market_data

    async def generate(
        self,
        ctx: DigestContext,
        _db: AsyncSession,
        _alpaca: AlpacaBrokerService,
    ) -> list[CardCandidate]:
        holdings_by_symbol = {
            symbol: holding
            for holding in ctx.holdings
            if (symbol := _holding_symbol(holding)) is not None
        }
        symbols = list(holdings_by_symbol)
        if not symbols:
            return []

        moves = await detect_overnight_moves(
            symbols, self._market_data, now=ctx.market_state.as_of
        )
        candidates: list[CardCandidate] = []
        for symbol in symbols:
            move = moves.get(symbol)
            if move is None or not is_meaningful_move(move, HOLDING_MOVE_PCT):
                continue

            holding = holdings_by_symbol[symbol]
            market_value = _holding_market_value(holding)
            card = BigMoveCard(
                symbol=symbol,
                name=_holding_name(holding, symbol),
                prev_close=move.prev_close,
                current=move.current,
                change_abs=move.change_abs,
                change_pct=move.change_pct,
                reason=None,
                related_symbols=[symbol],
                card_context={
                    "generator": "big_moves",
                    "position_market_value": str(market_value),
                },
            )
            candidates.append(
                CardCandidate(
                    card=card,
                    event_type="big_move",
                    magnitude_score=_magnitude_score(
                        move.change_pct, market_value
                    ),
                    related_symbols=[symbol],
                    dedupe_key=f"big_move:{symbol}",
                )
            )
        return candidates


def _holding_symbol(holding: dict[str, Any]) -> str | None:
    raw = holding.get("symbol")
    if raw is None:
        return None
    symbol = str(raw).strip().upper()
    return symbol or None


def _holding_name(holding: dict[str, Any], symbol: str) -> str:
    raw = holding.get("name") or holding.get("asset_name")
    if raw is None:
        return symbol
    name = str(raw).strip()
    return name or symbol


def _holding_market_value(holding: dict[str, Any]) -> Decimal:
    try:
        return Decimal(str(holding.get("market_value") or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _magnitude_score(change_pct: Decimal, market_value: Decimal) -> float:
    return float(
        (abs(change_pct) / HOLDING_MOVE_PCT) * _position_weight(market_value)
    )


def _position_weight(market_value: Decimal) -> Decimal:
    if market_value <= 0:
        return Decimal("1")
    weight = market_value / _POSITION_WEIGHT_UNIT
    return min(_MAX_POSITION_WEIGHT, max(_MIN_POSITION_WEIGHT, weight))
