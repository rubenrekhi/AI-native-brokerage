"""
Integration tests for apply_account_status_change against real local Postgres.

Covers the SEV-327 contract: first-time ACTIVE transition flips the
user_profile.onboarding_completed flag atomically with the brokerage_account
status update, and replays are no-ops. Also covers SEV-529's sweep helper.

Also covers the SEV-655 contract: the same first-time ACTIVE transition marks
the sweep `PENDING_CHANGE` / stamps `sweep_enrolled_at` and enqueues the
background enrollment task — no inline Alpaca PATCH from the SSE handler.

Requires: Docker + `make infra` + `make migrate`.
Skipped automatically if Postgres is unavailable.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.account_status import (
    apply_account_status_change,
    apply_sweep_status_change,
)
from tests.integration.conftest import TEST_USER_ID, _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync,
    reason="Local Supabase Postgres not available (run `make infra`)",
)


async def _insert_brokerage_account(
    db: AsyncSession,
    user_id: uuid.UUID,
    alpaca_account_id: str,
    status: str = "SUBMITTED",
) -> None:
    await db.execute(
        text(
            """
            INSERT INTO brokerage_accounts (
                id, user_id, alpaca_account_id, account_status,
                kyc_submitted_at, created_at, updated_at
            ) VALUES (
                :id, :user_id, :alpaca_account_id, :status,
                now(), now(), now()
            )
            """
        ),
        {
            "id": uuid.uuid4(),
            "user_id": user_id,
            "alpaca_account_id": alpaca_account_id,
            "status": status,
        },
    )
    await db.flush()


class TestAccountStatusActiveFlipsOnboarding:
    """SEV-327: the SSE ACTIVE event is the authoritative onboarding-complete
    signal — it must flip user_profiles.onboarding_completed = True."""

    async def test_active_transition_flips_onboarding_completed(
        self, db_session: AsyncSession, test_user: uuid.UUID
    ):
        alpaca_id = f"acct-{uuid.uuid4()}"
        await _insert_brokerage_account(db_session, test_user, alpaca_id)

        # Sanity: profile starts with flag False.
        before = await db_session.execute(
            text(
                "SELECT onboarding_completed FROM user_profiles WHERE id = :id"
            ),
            {"id": test_user},
        )
        assert before.scalar_one() is False

        event_time = datetime(2026, 4, 22, 12, 0, 0, tzinfo=timezone.utc)
        await apply_account_status_change(
            db_session,
            alpaca_account_id=alpaca_id,
            new_status="ACTIVE",
            event_time=event_time,
        )

        profile_row = await db_session.execute(
            text(
                "SELECT onboarding_completed FROM user_profiles WHERE id = :id"
            ),
            {"id": test_user},
        )
        assert profile_row.scalar_one() is True

        account_row = await db_session.execute(
            text(
                "SELECT account_status, activated_at FROM brokerage_accounts "
                "WHERE alpaca_account_id = :aid"
            ),
            {"aid": alpaca_id},
        )
        result = account_row.one()
        assert result.account_status == "ACTIVE"
        assert result.activated_at == event_time

    async def test_replay_active_event_is_noop(
        self, db_session: AsyncSession, test_user: uuid.UUID
    ):
        alpaca_id = f"acct-{uuid.uuid4()}"
        await _insert_brokerage_account(db_session, test_user, alpaca_id)

        first_event = datetime(2026, 4, 22, 12, 0, 0, tzinfo=timezone.utc)
        await apply_account_status_change(
            db_session,
            alpaca_account_id=alpaca_id,
            new_status="ACTIVE",
            event_time=first_event,
        )

        # Replay the same event — profile flag and activated_at must be
        # unchanged (not re-stamped, not regressed).
        await apply_account_status_change(
            db_session,
            alpaca_account_id=alpaca_id,
            new_status="ACTIVE",
            event_time=datetime(2030, 1, 1, tzinfo=timezone.utc),
        )

        profile_row = await db_session.execute(
            text(
                "SELECT onboarding_completed FROM user_profiles WHERE id = :id"
            ),
            {"id": test_user},
        )
        assert profile_row.scalar_one() is True

        account_row = await db_session.execute(
            text(
                "SELECT activated_at FROM brokerage_accounts "
                "WHERE alpaca_account_id = :aid"
            ),
            {"aid": alpaca_id},
        )
        assert account_row.scalar_one() == first_event

    async def test_non_active_transition_does_not_flip_onboarding_completed(
        self, db_session: AsyncSession, test_user: uuid.UUID
    ):
        alpaca_id = f"acct-{uuid.uuid4()}"
        await _insert_brokerage_account(db_session, test_user, alpaca_id)

        await apply_account_status_change(
            db_session,
            alpaca_account_id=alpaca_id,
            new_status="REJECTED",
            kyc_results={"reject": ["OFAC hit"]},
        )

        profile_row = await db_session.execute(
            text(
                "SELECT onboarding_completed FROM user_profiles WHERE id = :id"
            ),
            {"id": test_user},
        )
        assert profile_row.scalar_one() is False


class TestSweepEnrollmentPersistence:
    """SEV-655: first-time ACTIVE transition marks the sweep ``PENDING_CHANGE``
    / stamps ``sweep_enrolled_at`` and enqueues the background enrollment task
    in the same transaction. Tests use a mocked ARQ pool (no live broker call)
    but a real DB so the ``update_status(**fields)`` -> column write path is
    exercised end-to-end."""

    async def test_active_transition_persists_pending_and_enqueues(
        self,
        db_session: AsyncSession,
        test_user: uuid.UUID,
        monkeypatch,
    ):
        monkeypatch.setattr(
            "app.services.account_status.settings.alpaca_apr_tier_name",
            "standard",
        )
        alpaca_id = f"acct-{uuid.uuid4()}"
        await _insert_brokerage_account(db_session, test_user, alpaca_id)
        arq = AsyncMock()
        event_time = datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)

        await apply_account_status_change(
            db_session,
            alpaca_account_id=alpaca_id,
            new_status="ACTIVE",
            event_time=event_time,
            arq=arq,
        )

        row = await db_session.execute(
            text(
                "SELECT id, sweep_status, sweep_enrolled_at "
                "FROM brokerage_accounts WHERE alpaca_account_id = :aid"
            ),
            {"aid": alpaca_id},
        )
        result = row.one()
        assert result.sweep_status == "PENDING_CHANGE"
        assert result.sweep_enrolled_at == event_time
        arq.enqueue_job.assert_awaited_once_with(
            "enroll_cash_interest", str(result.id)
        )

    async def test_unconfigured_tier_skips_sweep_columns(
        self,
        db_session: AsyncSession,
        test_user: uuid.UUID,
        monkeypatch,
    ):
        monkeypatch.setattr(
            "app.services.account_status.settings.alpaca_apr_tier_name", ""
        )
        alpaca_id = f"acct-{uuid.uuid4()}"
        await _insert_brokerage_account(db_session, test_user, alpaca_id)
        arq = AsyncMock()

        await apply_account_status_change(
            db_session,
            alpaca_account_id=alpaca_id,
            new_status="ACTIVE",
            arq=arq,
        )

        arq.enqueue_job.assert_not_awaited()
        row = await db_session.execute(
            text(
                "SELECT sweep_status, sweep_enrolled_at "
                "FROM brokerage_accounts WHERE alpaca_account_id = :aid"
            ),
            {"aid": alpaca_id},
        )
        result = row.one()
        assert result.sweep_status is None
        assert result.sweep_enrolled_at is None


class TestApplySweepStatusChange:
    """SEV-529: cash_interest SSE events update ``sweep_status`` in isolation
    from ``account_status``. Mirrors the sibling helper's coverage against
    real DB writes — protects against silent column renames (the repo's
    ``hasattr``-filter would otherwise mask them) and verifies the documented
    no-write-to-account_status invariant."""

    async def test_active_transition_writes_sweep_status_only(
        self, db_session: AsyncSession, test_user: uuid.UUID
    ):
        alpaca_id = f"acct-{uuid.uuid4()}"
        await _insert_brokerage_account(
            db_session, test_user, alpaca_id, status="ACTIVE"
        )

        await apply_sweep_status_change(
            db_session, alpaca_account_id=alpaca_id, new_status="ACTIVE"
        )

        row = await db_session.execute(
            text(
                "SELECT account_status, sweep_status, sweep_enrolled_at "
                "FROM brokerage_accounts WHERE alpaca_account_id = :aid"
            ),
            {"aid": alpaca_id},
        )
        result = row.one()
        assert result.account_status == "ACTIVE"
        assert result.sweep_status == "ACTIVE"
        # ``event_time`` is documented as not yet persisted — the enrollment
        # request flow owns ``sweep_enrolled_at``, not the listener.
        assert result.sweep_enrolled_at is None

    async def test_replay_same_sweep_status_is_noop(
        self, db_session: AsyncSession, test_user: uuid.UUID
    ):
        alpaca_id = f"acct-{uuid.uuid4()}"
        await _insert_brokerage_account(
            db_session, test_user, alpaca_id, status="ACTIVE"
        )
        await apply_sweep_status_change(
            db_session, alpaca_account_id=alpaca_id, new_status="ACTIVE"
        )

        # Replaying the same event shouldn't error or flip anything.
        await apply_sweep_status_change(
            db_session, alpaca_account_id=alpaca_id, new_status="ACTIVE"
        )

        row = await db_session.execute(
            text(
                "SELECT sweep_status FROM brokerage_accounts "
                "WHERE alpaca_account_id = :aid"
            ),
            {"aid": alpaca_id},
        )
        assert row.scalar_one() == "ACTIVE"

    async def test_sweep_does_not_overwrite_account_status(
        self, db_session: AsyncSession, test_user: uuid.UUID
    ):
        """Cash_interest events arrive against accounts in any lifecycle
        state. The sweep helper must not regress ``account_status`` — pin
        it against an end-state value the listener should never write."""
        alpaca_id = f"acct-{uuid.uuid4()}"
        await _insert_brokerage_account(
            db_session, test_user, alpaca_id, status="ACTIVE"
        )

        await apply_sweep_status_change(
            db_session, alpaca_account_id=alpaca_id, new_status="INACTIVE"
        )

        row = await db_session.execute(
            text(
                "SELECT account_status, sweep_status FROM brokerage_accounts "
                "WHERE alpaca_account_id = :aid"
            ),
            {"aid": alpaca_id},
        )
        result = row.one()
        assert result.account_status == "ACTIVE"
        assert result.sweep_status == "INACTIVE"

    async def test_unknown_account_is_noop(self, db_session: AsyncSession):
        """Alpaca multiplexes every account on the API key, including ones
        that don't belong to any Sevino user. Unknown ``account_id`` must
        log + skip, not error."""
        await apply_sweep_status_change(
            db_session,
            alpaca_account_id=f"acct-unknown-{uuid.uuid4()}",
            new_status="ACTIVE",
        )
