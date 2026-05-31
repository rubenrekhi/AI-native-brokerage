"""Top-level entrypoint for the AI Radar batch pipeline.

Wires together the four stages built in T1–T4 — static gate, candidate
sourcer, LLM pick + label, atomic rotate-and-insert — into one async
function the ARQ task wrapper calls per user.

The single-transaction rotation is the load-bearing piece: the prior
unfavorited AI rows are deleted, the user's refresh anchor advances by 7
days, and the new batch is inserted inside one ``db.begin()`` block. If
any step throws — repo error, lost connection, race against another
worker — the whole block rolls back and the user keeps last week's
batch + anchor instead of landing in a half-rotated state.
"""

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

import structlog
from anthropic import AsyncAnthropic
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.radar_item import RadarItem
from app.repositories.asset import AssetRepository
from app.repositories.brokerage_account import (
    STATUS_ACTIVE,
    BrokerageAccountRepository,
)
from app.repositories.financial_profile import FinancialProfileRepository
from app.repositories.radar_item import RadarItemRepository
from app.repositories.user_profile import UserProfileRepository
from app.services.alpaca_broker import (
    AlpacaBrokerService,
    AlpacaBrokerUnavailableError,
)
from app.services.fmp import FmpClient
from app.services.radar_job import RadarJobError
from app.services.radar_job.candidate_sourcer import build_pool
from app.services.radar_job.events_client import EventsClient
from app.services.radar_job.llm import OwnedPosition, RadarLLM, UserContext
from app.services.radar_job.quality_gate import StaticQualityGate

logger = structlog.get_logger(__name__)

# A pool with fewer names than this gives the LLM too little to span four
# buckets meaningfully — better to skip the run and let ARQ retry than to
# emit a degenerate batch from three options.
MIN_POOL_SIZE = 10


@dataclass(frozen=True)
class RadarBatchResult:
    picks_count: int
    next_refresh_at: datetime


async def generate_radar_batch(
    user_id: UUID,
    db: AsyncSession,
    *,
    alpaca: AlpacaBrokerService,
    fmp: FmpClient,
    redis: Redis,
    anthropic: AsyncAnthropic,
) -> RadarBatchResult:
    """Generate one weekly radar batch for ``user_id``.

    Stages:
      1. Static gate over the enriched asset universe (T2)
      2. Bucket-tagged candidate pool for this user (T3)
      3. LLM picks 5–7 with descriptive labels (T4)
      4. Atomic rotation: drop prior unfavorited AI rows, bump the user's
         next refresh anchor by 7d, insert the new batch

    Raises ``RadarJobError`` if any stage can't proceed (pool too small,
    LLM validation failed, etc.) so the ARQ wrapper has one failure type
    to catch and let retry policy handle.
    """
    universe = await AssetRepository.list_eligible_for_radar(db)
    gated = StaticQualityGate.filter(universe)

    events = EventsClient(fmp=fmp, redis=redis)
    pool = await build_pool(user_id, gated, db, alpaca, events)
    if len(pool) < MIN_POOL_SIZE:
        logger.warning(
            "radar_orchestrator_pool_too_small",
            user_id=str(user_id),
            pool_size=len(pool),
        )
        raise RadarJobError("pool_too_small")

    user_ctx = await _gather_user_context(user_id, db, alpaca)
    llm = RadarLLM(anthropic)
    picks = await llm.pick(pool, user_ctx)

    name_by_symbol = {c.symbol.upper(): c.name for c in pool}

    # Claim the slot FIRST: takes FOR UPDATE on user_profiles, returns
    # None if a concurrent worker already rotated, and only then bumps
    # the anchor. The lock is held through the inserts below because the
    # session's auto-begun transaction stays open until the ARQ wrapper
    # commits — no explicit `db.begin()` block (it would clash with the
    # autobegun TX from the preceding reads).
    next_anchor = await UserProfileRepository.try_claim_radar_slot(db, user_id)
    if next_anchor is None:
        logger.info(
            "radar_orchestrator_already_rotated", user_id=str(user_id)
        )
        raise RadarJobError("already_rotated")

    deleted = await RadarItemRepository.delete_unfavorited_ai(db, user_id)
    for pick in picks:
        await RadarItemRepository.create_ai_item(
            db,
            user_id=user_id,
            symbol=pick.symbol,
            company_name=name_by_symbol.get(pick.symbol.upper()),
            context_blurb=pick.label,
            relevance_score=pick.relevance,
            bucket=pick.bucket,
            expires_at=next_anchor,
        )

    logger.info(
        "radar_orchestrator_batch_complete",
        user_id=str(user_id),
        picks_count=len(picks),
        deleted_prior=deleted,
        next_refresh_at=next_anchor.isoformat(),
    )
    return RadarBatchResult(picks_count=len(picks), next_refresh_at=next_anchor)


async def _gather_user_context(
    user_id: UUID,
    db: AsyncSession,
    alpaca: AlpacaBrokerService,
) -> UserContext:
    """Read the per-user inputs the LLM step needs.

    Positions and sectors come from Alpaca (live) + the local catalog
    (sector tags); risk/goals from the financial profile; favorited
    symbols from the radar table. Alpaca being unavailable degrades to
    empty positions — matches the candidate sourcer's policy so the two
    stages see a consistent view of the user.
    """
    profile = await UserProfileRepository.get_by_id(db, user_id)
    financial = await FinancialProfileRepository.get_by_user_id(db, user_id)
    brokerage = await BrokerageAccountRepository.get_by_user_id(db, user_id)

    positions: list[OwnedPosition] = []
    if brokerage and brokerage.account_status == STATUS_ACTIVE:
        try:
            raw = await alpaca.list_positions(brokerage.alpaca_account_id)
        except AlpacaBrokerUnavailableError:
            logger.warning(
                "radar_orchestrator_positions_unavailable",
                user_id=str(user_id),
            )
            raw = []
        symbols = {p["symbol"].upper() for p in raw if p.get("symbol")}
        sectors = await _sectors_by_symbol(db, symbols)
        positions = [
            OwnedPosition(symbol=symbol, sector=sectors.get(symbol))
            for symbol in sorted(symbols)
        ]

    favorited = await _favorited_symbols(db, user_id)

    return UserContext(
        risk_tolerance=financial.risk_tolerance if financial else None,
        age=_age(financial, profile),
        goals=list(financial.investment_goals or []) if financial else [],
        positions=positions,
        favorited_symbols=favorited,
    )


async def _sectors_by_symbol(
    db: AsyncSession, symbols: set[str]
) -> dict[str, str]:
    """Map each owned symbol to its catalog sector (missing where unknown).

    `AssetRepository.sectors_for_symbols` returns the distinct set; we need
    per-symbol so each ``OwnedPosition`` can carry its own tag.
    """
    if not symbols:
        return {}
    result = await db.execute(
        select(Asset.symbol, Asset.sector).where(
            Asset.symbol.in_(symbols), Asset.sector.is_not(None)
        )
    )
    return {row.symbol: row.sector for row in result.all()}


async def _favorited_symbols(db: AsyncSession, user_id: UUID) -> list[str]:
    result = await db.execute(
        select(RadarItem.symbol)
        .where(RadarItem.user_id == user_id, RadarItem.is_favorited.is_(True))
        .order_by(RadarItem.symbol)
    )
    return list(result.scalars().all())


def _age(financial, profile) -> int | None:
    """Compute age from the first non-null DOB we find (financial → profile).

    Either profile may carry it depending on which onboarding step the user
    last touched; both store ISO dates and we just need a single int for the
    LLM prompt.
    """
    dob: date | None = None
    if financial and financial.date_of_birth:
        dob = financial.date_of_birth
    elif profile and profile.date_of_birth:
        dob = profile.date_of_birth
    if dob is None:
        return None
    today = date.today()
    years = today.year - dob.year
    if (today.month, today.day) < (dob.month, dob.day):
        years -= 1
    return years
