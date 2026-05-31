import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError
from app.models.digest import DigestSnapshot
from app.models.user_profile import UserProfile

RADAR_CADENCE = timedelta(days=7)
# Beyond this gap the prior anchor is too far in the past to preserve the
# user's signup day-of-week — re-anchor from now() instead of stacking weeks.
RADAR_STALE_REANCHOR = timedelta(days=14)


class UserProfileRepository:

    @staticmethod
    async def get_by_id(db: AsyncSession, user_id: uuid.UUID) -> UserProfile | None:
        result = await db.execute(
            select(UserProfile).where(UserProfile.id == user_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def update_fields(
        db: AsyncSession, user_id: uuid.UUID, **fields
    ) -> UserProfile:
        profile = await UserProfileRepository.get_by_id(db, user_id)
        if profile is None:
            raise NotFoundError(
                "User profile not found",
                resource="user_profile",
            )
        for key, value in fields.items():
            if hasattr(profile, key):
                setattr(profile, key, value)
        await db.flush()
        return profile

    @staticmethod
    async def bump_next_refresh(
        db: AsyncSession, user_id: uuid.UUID
    ) -> datetime:
        """Advance ``next_radar_refresh_at`` by 7d from the prior anchor.

        Anchoring off the prior value (not ``now()``) preserves the user's
        signup day-of-week across weeks — a Tuesday signup keeps getting
        Tuesday batches even if a run lands a few hours late. If retries
        exhaust and the anchor falls more than ``RADAR_STALE_REANCHOR``
        behind, the user has drifted off their original cadence anyway, so
        we re-anchor from ``now()`` rather than catch up with stacked weeks.

        Pure advance primitive — no due-ness check, no row lock. The
        orchestrator's ``try_claim_radar_slot`` takes the lock + skips
        already-rotated users; direct callers (T6 onboarding hook, tests)
        bump unconditionally.
        """
        profile = await UserProfileRepository.get_by_id(db, user_id)
        if profile is None:
            raise NotFoundError(
                "User profile not found",
                resource="user_profile",
            )
        now = datetime.now(timezone.utc)
        base = profile.next_radar_refresh_at or now
        if base < now - RADAR_STALE_REANCHOR:
            base = now
        new_anchor = base + RADAR_CADENCE
        profile.next_radar_refresh_at = new_anchor
        await db.flush()
        return new_anchor

    @staticmethod
    async def list_users_due_for_refresh(
        db: AsyncSession, now: datetime
    ) -> list[uuid.UUID]:
        """User IDs whose radar batch is due — the hourly cron's enqueue set.

        A user is due when their anchor is non-null and at or before ``now``
        and they've completed onboarding. The first batch is enqueued
        directly by the onboarding hook (which sets the anchor before the
        account is ``ACTIVE``); the ``onboarding_completed`` gate keeps the
        cron from re-firing for users who abandoned KYC before activation.
        """
        result = await db.execute(
            select(UserProfile.id).where(
                UserProfile.next_radar_refresh_at.is_not(None),
                UserProfile.next_radar_refresh_at <= now,
                UserProfile.onboarding_completed.is_(True),
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_active_users_without_digest(
        db: AsyncSession,
        *,
        active_since: datetime,
        ny_local_date: date,
    ) -> list[uuid.UUID]:
        """Recently active users missing a digest for the given NY-local day."""
        result = await db.execute(
            select(UserProfile.id)
            .outerjoin(
                DigestSnapshot,
                and_(
                    DigestSnapshot.user_id == UserProfile.id,
                    DigestSnapshot.ny_local_date == ny_local_date,
                ),
            )
            .where(
                UserProfile.last_active_at.is_not(None),
                UserProfile.last_active_at >= active_since,
                DigestSnapshot.id.is_(None),
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def try_claim_radar_slot(
        db: AsyncSession, user_id: uuid.UUID
    ) -> datetime | None:
        """Race-safe combination of "is this user due?" + bump anchor.

        Takes a ``FOR UPDATE`` row lock on user_profiles so two concurrent
        orchestrator runs serialize. The second waits, observes the anchor
        the first committed, finds it in the future, and gets ``None`` — no
        double-batch, no reliance on the radar_items unique constraint as
        the de-facto guard. Returns the new anchor on success, ``None`` if
        a concurrent worker already rotated this user.

        Caller must remain in the same transaction to hold the lock through
        subsequent writes — releasing the TX releases the lock.
        """
        result = await db.execute(
            select(UserProfile)
            .where(UserProfile.id == user_id)
            .with_for_update()
        )
        profile = result.scalar_one_or_none()
        if profile is None:
            raise NotFoundError(
                "User profile not found",
                resource="user_profile",
            )
        now = datetime.now(timezone.utc)
        if (
            profile.next_radar_refresh_at is not None
            and profile.next_radar_refresh_at > now
        ):
            return None
        base = profile.next_radar_refresh_at or now
        if base < now - RADAR_STALE_REANCHOR:
            base = now
        new_anchor = base + RADAR_CADENCE
        profile.next_radar_refresh_at = new_anchor
        await db.flush()
        return new_anchor
