"""Data access for `radar_items` — the per-user radar / watchlist of
AI-surfaced and user-added stocks.

The read-time expiry filter in `list_for_user` hides rows past their
`expires_at`, so users never see a stale row even if the sweep cron is
lagging. Favorited rows always have `expires_at = NULL` by invariant
(set on the write path), so they're never filtered out here.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete as sa_delete
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
    async def list_favorited_for_user(
        db: AsyncSession, user_id: uuid.UUID
    ) -> list[RadarItem]:
        """Return the user's favorited radar rows in stable symbol order."""
        result = await db.execute(
            select(RadarItem)
            .where(
                RadarItem.user_id == user_id,
                RadarItem.is_favorited.is_(True),
            )
            .order_by(RadarItem.symbol)
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_all_symbols(
        db: AsyncSession, user_id: uuid.UUID
    ) -> set[str]:
        """Every symbol on the user's radar, ignoring expiry.

        Unlike `list_for_user`, this includes expired-but-not-yet-swept rows.
        The candidate sourcer excludes these from the pool so a new batch can
        never re-pick a symbol that still has a row under the
        `(user_id, symbol)` unique constraint.
        """
        result = await db.execute(
            select(RadarItem.symbol).where(RadarItem.user_id == user_id)
        )
        return set(result.scalars().all())

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
        bucket: str | None = None,
        expires_at: datetime | None = None,
    ) -> RadarItem:
        """Create an AI-generated radar row. Unfavorited.

        `expires_at` defaults to 7 days from now (sweep-cron compatibility);
        the orchestrator overrides it with the user's next refresh anchor so
        a row's lifetime matches the cadence rather than its insertion time.
        """
        item = RadarItem(
            user_id=user_id,
            symbol=symbol,
            company_name=company_name,
            source=SOURCE_AI_GENERATED,
            is_favorited=False,
            context_blurb=context_blurb,
            relevance_score=relevance_score,
            bucket=bucket,
            expires_at=expires_at
            if expires_at is not None
            else datetime.now(timezone.utc) + AI_ITEM_TTL,
        )
        db.add(item)
        await db.flush()
        return item

    @staticmethod
    async def delete_unfavorited_ai(
        db: AsyncSession, user_id: uuid.UUID
    ) -> int:
        """Drop the user's prior AI picks they didn't keep — the atomic
        rotation primitive the orchestrator calls just before inserting the
        new batch.

        Source + favorited filters guarantee user-added rows and favorited
        AI items survive even if a future caller drifts from the invariant.
        """
        stmt = sa_delete(RadarItem).where(
            RadarItem.user_id == user_id,
            RadarItem.source == SOURCE_AI_GENERATED,
            RadarItem.is_favorited.is_(False),
        )
        result = await db.execute(stmt)
        return result.rowcount or 0

    @staticmethod
    async def delete(db: AsyncSession, item: RadarItem) -> None:
        """Hard-delete a radar row."""
        await db.delete(item)
        await db.flush()

    @staticmethod
    async def delete_expired_ai_items(db: AsyncSession) -> int:
        """Bulk-delete expired non-favorited AI rows. Returns row count.

        Used by the daily sweep cron. The defense-in-depth `source` filter
        guarantees `user_added` rows are never touched even if the
        favorited-vs-expiry invariant ever drifts elsewhere.
        """
        stmt = sa_delete(RadarItem).where(
            RadarItem.source == SOURCE_AI_GENERATED,
            RadarItem.is_favorited.is_(False),
            RadarItem.expires_at < func.now(),
        )
        result = await db.execute(stmt)
        return result.rowcount or 0
