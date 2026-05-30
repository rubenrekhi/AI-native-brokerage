"""Orchestrates the per-category rules behind `GET /v1/shortcuts`."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.repositories.user_profile import UserProfileRepository
from app.schemas.shortcuts import ShortcutsResponse
from app.services.alpaca_broker import AlpacaBrokerService
from app.services.market_data import MarketDataService
from app.services.shortcuts import ranker
from app.services.shortcuts.context import ShortcutContext
from app.services.shortcuts.rules import first_time, quiet_state
from app.services.shortcuts.time_buckets import ET, current_bucket

logger = structlog.get_logger(__name__)


class ShortcutsService:
    """Builds the shortcut feed: gather user context, run rules, then rank.

    ``alpaca`` and ``market_data`` are held for the portfolio- and
    market-aware rule categories; the current rules
    (``first_time`` / ``quiet_state``) read only the database and the clock.
    """

    def __init__(
        self,
        db: AsyncSession,
        alpaca: AlpacaBrokerService | None,
        market_data: MarketDataService | None,
    ) -> None:
        self._db = db
        self._alpaca = alpaca
        self._market_data = market_data

    async def list_for_user(
        self, user_id: uuid.UUID, *, now: datetime | None = None
    ) -> ShortcutsResponse:
        ctx = await self._build_context(
            user_id, now or datetime.now(timezone.utc)
        )
        rules = {
            "first_time": first_time.evaluate(ctx),
            "quiet_state": quiet_state.evaluate(ctx),
        }
        return ShortcutsResponse(items=ranker.rank(rules))

    async def _build_context(
        self, user_id: uuid.UUID, now_utc: datetime
    ) -> ShortcutContext:
        profile = await UserProfileRepository.get_by_id(self._db, user_id)
        if profile is None:
            # An authenticated user with no profile row is anomalous (the
            # signup trigger should always create one); fall back to new-user
            # treatment but surface it rather than silently masking it.
            logger.warning("shortcuts_profile_missing", user_id=str(user_id))
        account_age_days = (
            (now_utc - profile.created_at).days if profile else 0
        )
        stmt = (
            select(func.count())
            .select_from(Conversation)
            .where(
                Conversation.user_id == user_id,
                Conversation.is_deleted.is_(False),
            )
        )
        conversation_count = (await self._db.execute(stmt)).scalar_one()
        return ShortcutContext(
            user_id=user_id,
            bucket=current_bucket(now_utc),
            day=now_utc.astimezone(ET).date(),
            account_age_days=account_age_days,
            conversation_count=conversation_count,
        )
