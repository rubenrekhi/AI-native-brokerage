"""Data access for `digest_snapshots` — one curated digest per user per
NY-local day.

`upsert` is the idempotency primitive: the morning cron and the
lazy-fallback read path both write through it keyed on
`(user_id, ny_local_date)`, so re-running generation for the same day
refreshes the cards in place instead of inserting a duplicate row. The
upsert deliberately leaves `dismissed_at` untouched, so a regeneration
never resurrects a digest the user already swiped away.
"""

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.digest import DigestSnapshot


class DigestRepository:

    @staticmethod
    async def get_by_user_and_date(
        db: AsyncSession, user_id: uuid.UUID, ny_local_date: date
    ) -> DigestSnapshot | None:
        result = await db.execute(
            select(DigestSnapshot).where(
                DigestSnapshot.user_id == user_id,
                DigestSnapshot.ny_local_date == ny_local_date,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def upsert(
        db: AsyncSession, snapshot: DigestSnapshot
    ) -> DigestSnapshot:
        """Insert the day's digest, or refresh its cards if one already exists.

        ON CONFLICT over `(user_id, ny_local_date)` makes concurrent
        generators (two cron ticks, cron racing the lazy fallback)
        converge on one row. `dismissed_at` is excluded from the update set
        so regeneration can't un-dismiss a digest the user already saw.
        """
        stmt = (
            pg_insert(DigestSnapshot)
            .values(
                id=uuid.uuid4(),
                user_id=snapshot.user_id,
                ny_local_date=snapshot.ny_local_date,
                cards=snapshot.cards,
                generated_at=snapshot.generated_at,
            )
            .on_conflict_do_update(
                constraint="uq_digest_snapshots_user_date",
                set_={
                    "cards": snapshot.cards,
                    "generated_at": snapshot.generated_at,
                },
            )
            .returning(DigestSnapshot)
        )
        result = await db.execute(stmt)
        snapshot = result.scalars().one()
        # On conflict the row maps to an instance already in the identity
        # map (e.g. a prior `first` from this session), so RETURNING values
        # don't overwrite its stale attributes — refresh to reflect the DB.
        await db.refresh(snapshot)
        return snapshot

    @staticmethod
    async def mark_dismissed(
        db: AsyncSession, snapshot_id: uuid.UUID
    ) -> DigestSnapshot | None:
        """Stamp `dismissed_at` once. Idempotent — re-dismissing keeps the
        original timestamp so the dismissal time stays truthful. Returns
        None if the id doesn't exist."""
        snapshot = await db.get(DigestSnapshot, snapshot_id)
        if snapshot is None:
            return None
        if snapshot.dismissed_at is None:
            snapshot.dismissed_at = datetime.now(timezone.utc)
            await db.flush()
        return snapshot

    @staticmethod
    async def delete_older_than(
        db: AsyncSession, cutoff_ny_local_date: date
    ) -> int:
        """Delete snapshots before the retained NY-local date window."""
        result = await db.execute(
            delete(DigestSnapshot).where(
                DigestSnapshot.ny_local_date < cutoff_ny_local_date
            )
        )
        return result.rowcount or 0
