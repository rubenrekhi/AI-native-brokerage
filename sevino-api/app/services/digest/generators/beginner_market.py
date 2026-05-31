"""Digest generator for users with no positions yet.

Activates when ``ctx.holdings`` is empty. Pulls moves and news on a curated
mega-cap bellwether list so new users still get a useful digest instead of
nothing. Skips symbols already in the user's watchlist so this generator
doesn't double up with `WatchlistMovesGenerator`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import (
    MarketDataError,
    MarketDataUnavailableError,
    MarketDataUpstreamError,
)
from app.repositories.radar_item import RadarItemRepository
from app.services.alpaca_broker import AlpacaBrokerService
from app.services.digest.cards import BigMoveCard, NewsCard
from app.services.digest.generators.news import NEWS_RECENCY_WINDOW
from app.services.digest.moves import (
    BEGINNER_MOVE_PCT,
    StockBarsProvider,
    detect_overnight_moves,
    is_meaningful_move,
)
from app.services.digest.types import CardCandidate, DigestContext
from app.services.fmp import StockNewsItem

logger = structlog.get_logger(__name__)

BELLWETHER_SYMBOLS: tuple[str, ...] = (
    "AAPL",
    "MSFT",
    "NVDA",
    "GOOGL",
    "AMZN",
    "META",
    "TSLA",
)

BELLWETHER_NAMES: dict[str, str] = {
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "NVDA": "Nvidia",
    "GOOGL": "Alphabet",
    "AMZN": "Amazon",
    "META": "Meta Platforms",
    "TSLA": "Tesla",
}

_NEWS_LIMIT = 30
_CARD_NEWS_LIMIT = 3


class StockNewsProvider(Protocol):
    async def get_stock_news(
        self, symbols: list[str], since: datetime, limit: int = 50
    ) -> Sequence[StockNewsItem]: ...


@dataclass(frozen=True)
class _BeginnerSources:
    market_data: StockBarsProvider
    fmp: StockNewsProvider


class BeginnerMarketGenerator:
    def __init__(
        self,
        market_data: StockBarsProvider,
        *,
        fmp: StockNewsProvider,
        symbols: Sequence[str] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._sources = _BeginnerSources(market_data=market_data, fmp=fmp)
        self._symbols = tuple(symbols) if symbols is not None else BELLWETHER_SYMBOLS
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def generate(
        self,
        ctx: DigestContext,
        db: AsyncSession,
        _alpaca: AlpacaBrokerService,
    ) -> list[CardCandidate]:
        if ctx.holdings:
            return []

        watchlist_symbols = await _watchlist_symbols(db, ctx.user_id)
        eligible = [s for s in self._symbols if s not in watchlist_symbols]
        if not eligible:
            return []

        candidates: list[CardCandidate] = []
        candidates.extend(await self._move_candidates(ctx, eligible))
        candidates.extend(await self._news_candidates(ctx, eligible))
        return candidates

    async def _move_candidates(
        self, ctx: DigestContext, symbols: list[str]
    ) -> list[CardCandidate]:
        moves = await detect_overnight_moves(
            symbols, self._sources.market_data, now=ctx.market_state.as_of
        )
        candidates: list[CardCandidate] = []
        for symbol in symbols:
            move = moves.get(symbol)
            if move is None or not is_meaningful_move(move, BEGINNER_MOVE_PCT):
                continue
            card = BigMoveCard(
                symbol=symbol,
                name=BELLWETHER_NAMES.get(symbol, symbol),
                prev_close=move.prev_close,
                current=move.current,
                change_abs=move.change_abs,
                change_pct=move.change_pct,
                reason=None,
                related_symbols=[symbol],
                card_context={"generator": "beginner_market"},
            )
            candidates.append(
                CardCandidate(
                    card=card,
                    event_type="big_move",
                    magnitude_score=float(
                        abs(move.change_pct) / BEGINNER_MOVE_PCT
                    ),
                    related_symbols=[symbol],
                    dedupe_key=f"big_move:{symbol}",
                )
            )
        return candidates

    async def _news_candidates(
        self, ctx: DigestContext, symbols: list[str]
    ) -> list[CardCandidate]:
        now = self._now()
        cutoff = now - NEWS_RECENCY_WINDOW
        try:
            items = await self._sources.fmp.get_stock_news(
                list(symbols), since=cutoff, limit=_NEWS_LIMIT
            )
        except (
            MarketDataError,
            MarketDataUnavailableError,
            MarketDataUpstreamError,
        ) as exc:
            logger.warning(
                "digest_beginner_news_fetch_failed",
                user_id=str(ctx.user_id),
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return []

        kept = _dedupe_by_symbol(items)
        candidates: list[CardCandidate] = []
        for item in kept[:_CARD_NEWS_LIMIT]:
            symbol = item.symbol.strip().upper() if item.symbol else None
            card = NewsCard(
                symbol=symbol,
                headline=item.headline,
                source=item.source or "Unknown",
                url=item.url,
                published_at=item.published_at,
                summary=_summary(item),
                related_symbols=[symbol] if symbol else [],
                card_context={
                    "generator": "beginner_market",
                    "symbol": symbol,
                    "headline": item.headline,
                    "source": item.source,
                    "url": item.url,
                    "published_at": item.published_at.isoformat(),
                },
            )
            candidates.append(
                CardCandidate(
                    card=card,
                    event_type="news",
                    magnitude_score=1.0,
                    related_symbols=[symbol] if symbol else [],
                    dedupe_key=f"news:{symbol or ''}:{item.headline.strip().lower()}",
                )
            )
        return candidates


async def _watchlist_symbols(db: AsyncSession, user_id: uuid.UUID) -> set[str]:
    rows = await RadarItemRepository.list_favorited_for_user(db, user_id)
    return {row.symbol.strip().upper() for row in rows if row.symbol}


def _dedupe_by_symbol(items: Sequence[StockNewsItem]) -> list[StockNewsItem]:
    seen: set[str] = set()
    kept: list[StockNewsItem] = []
    for item in sorted(items, key=lambda i: i.published_at, reverse=True):
        key = (item.symbol or "").strip().upper()
        if key in seen:
            continue
        seen.add(key)
        kept.append(item)
    return kept


def _summary(item: StockNewsItem) -> str:
    if item.summary:
        return item.summary
    body = (item.body or "").strip()
    if body:
        return body[:200]
    return item.headline
