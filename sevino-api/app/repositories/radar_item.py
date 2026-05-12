"""Data access for `radar_items` — the per-user radar / watchlist of
AI-surfaced and user-added stocks.

The read-time expiry filter in `list_for_user` hides rows past their
`expires_at`, so users never see a stale row even if the sweep cron is
lagging. Favorited rows always have `expires_at = NULL` by invariant
(set on the write path), so they're never filtered out here.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.functions import func

from app.models.radar_item import RadarItem

SOURCE_USER_ADDED = "user_added"
SOURCE_AI_GENERATED = "ai_generated"

# AI-generated rows expire 7 days after creation unless the user favorites
# them, at which point `expires_at` is nulled on the write path.
AI_ITEM_TTL = timedelta(days=7)


class RadarItemRepository:

    @staticmethod
    async def list_for_user(
        db: AsyncSession, user_id: uuid.UUID
    ) -> list[RadarItem]:
        """Return the user's visible radar rows.

        Sort: favorited first (watchlist surfaces on top), then by AI
        relevance descending nulls last (so user-added rows with no score
        don't outrank scored AI items), then by recency.
        """
        stmt = (
            select(RadarItem)
            .where(
                RadarItem.user_id == user_id,
                or_(
                    RadarItem.expires_at.is_(None),
                    RadarItem.expires_at > func.now(),
                ),
            )
            .order_by(
                RadarItem.is_favorited.desc(),
                RadarItem.relevance_score.desc().nulls_last(),
                RadarItem.created_at.desc(),
            )
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_by_id_for_user(
        db: AsyncSession, item_id: uuid.UUID, user_id: uuid.UUID
    ) -> RadarItem | None:
        """Ownership-guarded lookup — returns None if the item belongs to a
        different user, so callers don't need a separate authorization check."""
        result = await db.execute(
            select(RadarItem).where(
                RadarItem.id == item_id,
                RadarItem.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create_user_added(
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        symbol: str,
        company_name: str | None,
    ) -> RadarItem:
        """Create a user-added radar row. Auto-favorited, no expiry."""
        item = RadarItem(
            user_id=user_id,
            symbol=symbol,
            company_name=company_name,
            source=SOURCE_USER_ADDED,
            is_favorited=True,
            expires_at=None,
        )
        db.add(item)
        await db.flush()
        return item

    @staticmethod
    async def create_ai_item(
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        symbol: str,
        company_name: str | None,
        context_blurb: str | None = None,
        relevance_score: float | None = None,
    ) -> RadarItem:
        """Create an AI-generated radar row. Unfavorited, expires in 7 days."""
        item = RadarItem(
            user_id=user_id,
            symbol=symbol,
            company_name=company_name,
            source=SOURCE_AI_GENERATED,
            is_favorited=False,
            context_blurb=context_blurb,
            relevance_score=relevance_score,
            expires_at=datetime.now(timezone.utc) + AI_ITEM_TTL,
        )
        db.add(item)
        await db.flush()
        return item
