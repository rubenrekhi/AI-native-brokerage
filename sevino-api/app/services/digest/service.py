"""Business logic for the Daily Digest.

`generate_for_user` runs the configured generator set, persists the result,
and is what the morning cron (T12) will call per user. `get_today` /
`dismiss` back the two `/v1/digest` endpoints. Generators are built up
across T7-T11; until the default service path is wired, callers inject
generators or market-data/FMP-backed generator factories explicitly.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from time import perf_counter

import sentry_sdk
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError
from app.models.digest import DigestSnapshot
from app.repositories.digest import DigestRepository
from app.services.alpaca_broker import AlpacaBrokerService
from app.services.digest.cards import BigMoveCard, EarningsResultCard, NewsCard
from app.services.digest.context import ET, build_context
from app.services.digest.generators import build_known_generators
from app.services.digest.moves import (
    MoveData,
    RunScopedStockBarsProvider,
    StockBarsProvider,
    detect_overnight_moves,
)
from app.services.digest.reranker import (
    SHORTLIST_LIMIT,
    AnthropicClient,
    DigestReranker,
    Reranker,
)
from app.services.digest.types import CardCandidate, DigestContext, Generator
from app.services.fmp import FmpClient

logger = structlog.get_logger(__name__)

_GATE_REASON_MAX_CHARS = 200
_GATE_REASON_LOG_CHARS = 80


class DigestService:
    """Generate, read, and dismiss a user's daily digest.

    `alpaca` is only needed by `generate_for_user` (via `build_context`);
    the read/dismiss paths run with `alpaca=None`, which is why the
    `/v1/digest` route constructs the service without it.
    """

    def __init__(
        self,
        db: AsyncSession,
        alpaca: AlpacaBrokerService | None = None,
        market_data: StockBarsProvider | None = None,
        fmp: FmpClient | None = None,
        generators: list[Generator] | None = None,
        anthropic: AnthropicClient | None = None,
        reranker: Reranker | None = None,
    ) -> None:
        self._db = db
        self._alpaca = alpaca
        self._market_data = market_data
        self._fmp = fmp
        self._anthropic = anthropic
        self._reranker = reranker
        if generators is not None:
            self._generators: list[Generator] | None = list(generators)
        else:
            self._generators = None

    async def generate_for_user(self, user_id: uuid.UUID) -> DigestSnapshot:
        """Build context, run generators, and upsert today's snapshot.

        Idempotent per `(user_id, ny_local_date)`: re-running refreshes the
        cards in place (see `DigestRepository.upsert`).
        """
        return await self._generate_snapshot(user_id, persist=True)

    async def preview_for_user(self, user_id: uuid.UUID) -> DigestSnapshot:
        """Run the full generation pipeline without writing a snapshot."""
        return await self._generate_snapshot(user_id, persist=False)

    async def _generate_snapshot(
        self, user_id: uuid.UUID, *, persist: bool
    ) -> DigestSnapshot:
        if self._alpaca is None:
            raise RuntimeError("generate_for_user requires an Alpaca client")

        started = perf_counter()
        now = datetime.now(timezone.utc)
        ctx = await build_context(user_id, self._db, self._alpaca)
        candidates = await self._gather_candidates(ctx)
        await self._enrich_candidates(ctx, candidates)
        heuristic_order = _heuristic_shortlist(ctx, candidates)
        reranker = self._reranker or DigestReranker(self._anthropic)
        rerank = await reranker.rank_with_metadata(
            heuristic_order, ctx, fallback_order=heuristic_order
        )
        by_id = {candidate.card.id: candidate.card for candidate in heuristic_order}
        cards = [by_id[card_id] for card_id in rerank.ordered_ids if card_id in by_id]
        for priority, card in enumerate(cards, start=1):
            card.priority = priority
            reason = rerank.reasons.get(card.id)
            if reason:
                card.card_context = {
                    **card.card_context,
                    "gate_reason": reason[:_GATE_REASON_MAX_CHARS],
                }

        snapshot = DigestSnapshot(
            user_id=user_id,
            ny_local_date=now.astimezone(ET).date(),
            cards=[card.model_dump(mode="json") for card in cards],
            generated_at=now,
        )
        result = (
            await DigestRepository.upsert(self._db, snapshot) if persist else snapshot
        )
        dropped_count = len(heuristic_order) - len(cards)
        logger.info(
            "digest.generation.completed",
            user_id=str(user_id),
            total_latency_ms=round((perf_counter() - started) * 1000, 1),
            final_card_count=len(cards),
            shortlist_count=len(heuristic_order),
            dropped_count=dropped_count,
            reranker_fallback=rerank.used_fallback,
            reranker_fallback_reason=rerank.fallback_reason,
            card_kinds=[card.kind for card in cards],
            kept_reasons=(
                ["<fallback>"] * len(cards)
                if rerank.used_fallback
                else [
                    rerank.reasons.get(card.id, "")[:_GATE_REASON_LOG_CHARS]
                    for card in cards
                ]
            ),
            ny_local_date=result.ny_local_date.isoformat(),
            persisted=persist,
        )
        return result

    async def rollback(self) -> None:
        """Rollback the underlying session after a cancelled generation."""
        await self._db.rollback()

    async def get_today(
        self, user_id: uuid.UUID
    ) -> DigestSnapshot | None:
        """Today's (NY-local) digest, dismissed or not. None when absent."""
        return await DigestRepository.get_by_user_and_date(
            self._db, user_id, _today()
        )

    async def dismiss(self, user_id: uuid.UUID) -> DigestSnapshot:
        """Mark today's digest dismissed. 404 if there's nothing to dismiss."""
        snapshot = await DigestRepository.get_by_user_and_date(
            self._db, user_id, _today()
        )
        if snapshot is None:
            raise NotFoundError("No digest to dismiss")
        dismissed = await DigestRepository.mark_dismissed(
            self._db, snapshot.id
        )
        if dismissed is None:
            raise NotFoundError("No digest to dismiss")
        return dismissed

    async def _gather_candidates(
        self, ctx: DigestContext
    ) -> list[CardCandidate]:
        if self._generators is not None:
            generators = self._generators
        else:
            if self._market_data is None or self._fmp is None:
                raise RuntimeError(
                    "generate_for_user requires market_data and fmp clients "
                    "to run the full digest generator set"
                )
            market_data = RunScopedStockBarsProvider(self._market_data)
            generators = build_known_generators(market_data, fmp=self._fmp)
        if not generators:
            return []
        if self._alpaca is None:
            raise RuntimeError("digest generators require an Alpaca client")
        results = await asyncio.gather(
            *(
                self._run_generator(generator, ctx)
                for generator in generators
            )
        )
        return [candidate for batch in results for candidate in batch]

    async def _run_generator(
        self, generator: Generator, ctx: DigestContext
    ) -> list[CardCandidate]:
        if self._alpaca is None:
            raise RuntimeError("digest generators require an Alpaca client")
        name = generator.__class__.__name__
        started = perf_counter()
        candidate_count = 0
        error: str | None = None
        try:
            candidates = await generator.generate(ctx, self._db, self._alpaca)
            candidate_count = len(candidates)
            return candidates
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "digest_generator_failed",
                user_id=str(ctx.user_id),
                generator=name,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("digest_component", "generator")
                scope.set_tag("digest_generator", name)
                scope.set_context(
                    "digest_generator",
                    {
                        "user_id": str(ctx.user_id),
                        "generator": name,
                    },
                )
                sentry_sdk.capture_exception(exc)
            return []
        finally:
            logger.info(
                "digest.generator.completed",
                user_id=str(ctx.user_id),
                name=name,
                latency_ms=round((perf_counter() - started) * 1000, 1),
                candidate_count=candidate_count,
                error=error,
            )

    async def _enrich_candidates(
        self, ctx: DigestContext, candidates: list[CardCandidate]
    ) -> None:
        _enrich_big_moves_with_news(ctx, candidates)
        await self._enrich_earnings_with_reactions(ctx, candidates)

    async def _enrich_earnings_with_reactions(
        self, ctx: DigestContext, candidates: list[CardCandidate]
    ) -> None:
        earnings = [
            candidate.card
            for candidate in candidates
            if isinstance(candidate.card, EarningsResultCard)
            and candidate.card.stock_reaction_pct is None
        ]
        if not earnings:
            return

        moves = _moves_from_big_move_cards(candidates)
        missing_symbols = [
            card.symbol
            for card in earnings
            if card.symbol.upper() not in moves
        ]
        if missing_symbols and self._market_data is not None:
            try:
                fresh = await detect_overnight_moves(
                    missing_symbols,
                    self._market_data,
                    now=ctx.market_state.as_of,
                )
            except Exception as exc:
                logger.warning(
                    "digest_earnings_reaction_enrichment_failed",
                    user_id=str(ctx.user_id),
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                with sentry_sdk.new_scope() as scope:
                    scope.set_tag("digest_component", "earnings_reaction")
                    scope.set_context(
                        "digest_earnings_reaction",
                        {
                            "user_id": str(ctx.user_id),
                            "symbols": missing_symbols,
                        },
                    )
                    sentry_sdk.capture_exception(exc)
            else:
                moves.update(fresh)

        for card in earnings:
            move = moves.get(card.symbol.upper())
            if move is not None and move.has_premarket_activity:
                card.stock_reaction_pct = move.change_pct


def _today():
    return datetime.now(timezone.utc).astimezone(ET).date()


def _enrich_big_moves_with_news(
    ctx: DigestContext, candidates: list[CardCandidate]
) -> None:
    news_by_symbol: dict[str, list[tuple[Decimal, datetime, NewsCard]]] = {}
    for candidate in candidates:
        card = candidate.card
        if not isinstance(card, NewsCard):
            continue
        if not _within_move_window(card.published_at, ctx.market_state.as_of):
            continue
        for symbol in card.related_symbols or ([card.symbol] if card.symbol else []):
            news_by_symbol.setdefault(symbol.upper(), []).append(
                (_weighted_impact(ctx, candidate), card.published_at, card)
            )

    for batch in news_by_symbol.values():
        batch.sort(key=lambda item: (item[0], item[1]), reverse=True)

    for candidate in candidates:
        card = candidate.card
        if not isinstance(card, BigMoveCard) or card.reason:
            continue
        matches = news_by_symbol.get(card.symbol.upper(), [])
        if matches:
            card.reason = matches[0][2].headline


def _moves_from_big_move_cards(
    candidates: list[CardCandidate],
) -> dict[str, MoveData]:
    moves: dict[str, MoveData] = {}
    for candidate in candidates:
        card = candidate.card
        if not isinstance(card, BigMoveCard):
            continue
        moves[card.symbol.upper()] = MoveData(
            prev_close=Decimal(str(card.prev_close)),
            current=Decimal(str(card.current)),
            change_abs=Decimal(str(card.change_abs)),
            change_pct=Decimal(str(card.change_pct)),
            has_premarket_activity=True,
        )
    return moves


def _heuristic_shortlist(
    ctx: DigestContext, candidates: list[CardCandidate]
) -> list[CardCandidate]:
    return sorted(
        candidates,
        key=lambda candidate: _weighted_impact(ctx, candidate),
        reverse=True,
    )[:SHORTLIST_LIMIT]


def _weighted_impact(ctx: DigestContext, candidate: CardCandidate) -> Decimal:
    return Decimal(str(candidate.magnitude_score)) * _candidate_position_weight(
        ctx, candidate
    )


def _candidate_position_weight(
    ctx: DigestContext, candidate: CardCandidate
) -> Decimal:
    weights = _holding_weights(ctx)
    applicable = [
        weights[symbol.upper()]
        for symbol in candidate.related_symbols
        if symbol.upper() in weights
    ]
    if not applicable:
        return Decimal("1")
    return max(applicable)


def _holding_weights(ctx: DigestContext) -> dict[str, Decimal]:
    weights: dict[str, Decimal] = {}
    market_values: dict[str, Decimal] = {}
    for holding in ctx.holdings:
        symbol = str(holding.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        explicit = _decimal_or_none(
            holding.get("portfolio_weight", holding.get("weight"))
        )
        if explicit is not None:
            weights[symbol] = max(explicit, Decimal("0"))
        market_value = _decimal_or_none(holding.get("market_value"))
        if market_value is not None:
            market_values[symbol] = max(market_value, Decimal("0"))

    if weights:
        return weights

    total = _decimal_or_none((ctx.portfolio_snapshot or {}).get("equity"))
    if total is None or total <= 0:
        total = sum(market_values.values(), Decimal("0"))
    if total <= 0:
        return {}
    return {symbol: value / total for symbol, value in market_values.items()}


def _decimal_or_none(value) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value).strip().removesuffix("%")) / (
            Decimal("100") if str(value).strip().endswith("%") else Decimal("1")
        )
    except (InvalidOperation, ValueError):
        return None


def _within_move_window(published_at: datetime, as_of: datetime) -> bool:
    published_et = _aware_utc(published_at).astimezone(ET)
    as_of_et = _aware_utc(as_of).astimezone(ET)
    return _prior_close(as_of_et) <= published_et <= as_of_et


def _prior_close(as_of_et: datetime) -> datetime:
    close = as_of_et.replace(hour=16, minute=0, second=0, microsecond=0)
    if as_of_et.weekday() < 5 and as_of_et >= close:
        return close

    day = as_of_et.date() - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return datetime.combine(day, time(16, 0), tzinfo=ET)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
