"""Holdings-aware stock news generator for Daily Digest."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import (
    MarketDataError,
    MarketDataUnavailableError,
    MarketDataUpstreamError,
)
from app.services.alpaca_broker import AlpacaBrokerService
from app.services.digest.cards import NewsCard
from app.services.digest.types import CardCandidate, DigestContext
from app.services.fmp import StockNewsItem

logger = structlog.get_logger(__name__)

_NEWS_LIMIT = 100
_CARD_LIMIT = 5
_RECENCY_WINDOW = timedelta(hours=24)
_DEDUPE_THRESHOLD = 0.6
_MIN_RECENCY_DECAY = Decimal("0.3")
_TOKEN_RE = re.compile(r"[a-z0-9]+")


class StockNewsProvider(Protocol):
    async def get_stock_news(
        self, symbols: list[str], since: datetime, limit: int = 50
    ) -> Sequence[StockNewsItem]:
        ...


class NewsGenerator:
    """Emit news cards for recent headlines that mention user holdings."""

    def __init__(
        self,
        *,
        fmp: StockNewsProvider,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._fmp = fmp
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def generate(
        self,
        ctx: DigestContext,
        _db: AsyncSession | None = None,
        _alpaca: AlpacaBrokerService | None = None,
    ) -> list[CardCandidate]:
        holding_symbols = _holding_symbols(ctx.holdings)
        if not holding_symbols:
            return []

        now = _as_utc(self._now())
        cutoff = now - _RECENCY_WINDOW
        try:
            items = await self._fmp.get_stock_news(
                holding_symbols, since=cutoff, limit=_NEWS_LIMIT
            )
        except (
            MarketDataError,
            MarketDataUnavailableError,
            MarketDataUpstreamError,
        ) as exc:
            logger.warning(
                "digest_news_fetch_failed",
                user_id=str(ctx.user_id),
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return []

        weights = _position_weights(ctx.holdings)
        relevant = [
            _NewsMatch(item=item, related_symbols=matches)
            for item in items
            if _is_recent(item, cutoff)
            if (matches := _symbols_in_headline(item.headline, holding_symbols))
        ]
        kept = _dedupe(relevant)
        kept.sort(key=lambda match: _as_utc(match.item.published_at), reverse=True)
        return [_candidate(match, weights, now) for match in kept[:_CARD_LIMIT]]


@dataclass(frozen=True)
class _NewsMatch:
    item: StockNewsItem
    related_symbols: list[str]


def _candidate(
    match: _NewsMatch, weights: dict[str, Decimal], now: datetime
) -> CardCandidate:
    item = match.item
    related_symbols = match.related_symbols
    primary_symbol = related_symbols[0] if related_symbols else None
    card = NewsCard(
        symbol=primary_symbol,
        headline=item.headline,
        source=item.source or "Unknown",
        url=item.url,
        published_at=item.published_at,
        summary=_summary(item),
        related_symbols=related_symbols,
        card_context={
            "symbol": primary_symbol,
            "headline": item.headline,
            "related_symbols": related_symbols,
            "source": item.source,
            "url": item.url,
            "published_at": item.published_at.isoformat(),
        },
    )
    return CardCandidate(
        card=card,
        event_type="news",
        magnitude_score=float(_magnitude(match, weights, now)),
        related_symbols=related_symbols,
        dedupe_key=f"news:{primary_symbol or ''}:{_normalized_title(item.headline)}",
    )


def _holding_symbols(holdings: list[dict]) -> list[str]:
    symbols: list[str] = []
    seen: set[str] = set()
    for holding in holdings:
        symbol = str(holding.get("symbol") or "").strip().upper()
        if symbol and symbol not in seen:
            seen.add(symbol)
            symbols.append(symbol)
    return symbols


def _position_weights(holdings: list[dict]) -> dict[str, Decimal]:
    explicit: dict[str, Decimal] = {}
    market_values: dict[str, Decimal] = {}
    symbols: list[str] = []
    seen: set[str] = set()

    for holding in holdings:
        symbol = str(holding.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        if symbol not in seen:
            seen.add(symbol)
            symbols.append(symbol)
        weight = _first_decimal(
            holding,
            ("weight", "portfolio_weight", "portfolioWeight", "allocation"),
        )
        if weight is not None:
            explicit[symbol] = weight
        market_value = _first_decimal(holding, ("market_value", "marketValue"))
        if market_value is not None:
            market_values[symbol] = market_value

    if explicit:
        return explicit

    total = sum(market_values.values(), Decimal("0"))
    if total <= 0:
        return {symbol: Decimal("0") for symbol in symbols}
    return {symbol: value / total for symbol, value in market_values.items()}


def _first_decimal(holding: dict, keys: tuple[str, ...]) -> Decimal | None:
    for key in keys:
        if key not in holding:
            continue
        value = _decimal_or_none(holding[key])
        if value is not None:
            return value
    return None


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        if isinstance(value, str):
            cleaned = value.strip().removesuffix("%")
            decimal = Decimal(cleaned)
            if value.strip().endswith("%"):
                return decimal / Decimal("100")
            return decimal
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _is_recent(item: StockNewsItem, cutoff: datetime) -> bool:
    return _as_utc(item.published_at) >= cutoff


def _symbols_in_headline(headline: str, symbols: list[str]) -> list[str]:
    lower = headline.lower()
    return [symbol for symbol in symbols if symbol.lower() in lower]


def _dedupe(matches: list[_NewsMatch]) -> list[_NewsMatch]:
    if len(matches) < 2:
        return matches

    parent = list(range(len(matches)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    token_sets = [_title_tokens(match.item.headline) for match in matches]
    for left in range(len(matches)):
        for right in range(left + 1, len(matches)):
            if _jaccard(token_sets[left], token_sets[right]) >= _DEDUPE_THRESHOLD:
                union(left, right)

    clusters: dict[int, _NewsMatch] = {}
    for index, match in enumerate(matches):
        root = find(index)
        current = clusters.get(root)
        if current is None or _as_utc(match.item.published_at) < _as_utc(
            current.item.published_at
        ):
            clusters[root] = match
    return list(clusters.values())


def _title_tokens(headline: str) -> set[str]:
    return set(_TOKEN_RE.findall(headline.lower()))


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _normalized_title(headline: str) -> str:
    return " ".join(sorted(_title_tokens(headline)))


def _summary(item: StockNewsItem) -> str:
    if item.summary:
        return item.summary
    return (item.body or "")[:200]


def _magnitude(
    match: _NewsMatch, weights: dict[str, Decimal], now: datetime
) -> Decimal:
    hours_old = Decimal(
        str(
            max(
                0.0,
                (now - _as_utc(match.item.published_at)).total_seconds() / 3600,
            )
        )
    )
    decay = max(_MIN_RECENCY_DECAY, Decimal("1.0") - (hours_old / Decimal("24")))
    weight = max(
        (weights.get(symbol, Decimal("0")) for symbol in match.related_symbols),
        default=Decimal("0"),
    )
    return weight * decay


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
