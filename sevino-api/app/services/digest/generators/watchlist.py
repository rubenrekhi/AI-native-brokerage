"""Digest generator for notable moves in favorited radar items."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.radar_item import RadarItem
from app.repositories.radar_item import RadarItemRepository
from app.services.alpaca_broker import AlpacaBrokerService
from app.services.digest.cards import WatchlistMoveCard
from app.services.digest.moves import (
    WATCHLIST_MOVE_PCT,
    StockBarsProvider,
    detect_overnight_moves,
    is_meaningful_move,
)
from app.services.digest.types import CardCandidate, DigestContext


class WatchlistMovesGenerator:
    def __init__(self, market_data: StockBarsProvider) -> None:
        self._market_data = market_data

    async def generate(
        self,
        ctx: DigestContext,
        db: AsyncSession,
        _alpaca: AlpacaBrokerService,
    ) -> list[CardCandidate]:
        rows = await RadarItemRepository.list_favorited_for_user(db, ctx.user_id)
        items_by_symbol = {
            symbol: item
            for item in rows
            if (symbol := _item_symbol(item)) is not None
        }
        symbols = list(items_by_symbol)
        if not symbols:
            return []

        moves = await detect_overnight_moves(
            symbols, self._market_data, now=ctx.market_state.as_of
        )
        candidates: list[CardCandidate] = []
        for symbol in symbols:
            move = moves.get(symbol)
            if move is None or not is_meaningful_move(move, WATCHLIST_MOVE_PCT):
                continue

            item = items_by_symbol[symbol]
            card = WatchlistMoveCard(
                symbol=symbol,
                name=_item_name(item, symbol),
                prev_close=move.prev_close,
                current=move.current,
                change_abs=move.change_abs,
                change_pct=move.change_pct,
                reason=None,
                related_symbols=[symbol],
                card_context={"generator": "watchlist_moves"},
            )
            candidates.append(
                CardCandidate(
                    card=card,
                    event_type="watchlist_move",
                    magnitude_score=float(abs(move.change_pct) / WATCHLIST_MOVE_PCT),
                    related_symbols=[symbol],
                    dedupe_key=f"watchlist_move:{symbol}",
                )
            )
        return candidates


def _item_symbol(item: RadarItem) -> str | None:
    symbol = item.symbol.strip().upper()
    return symbol or None


def _item_name(item: RadarItem, symbol: str) -> str:
    if item.company_name is None:
        return symbol
    name = item.company_name.strip()
    return name or symbol
