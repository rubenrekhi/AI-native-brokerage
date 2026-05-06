"""
Integration tests for apply_account_status_change against real local Postgres.

Covers the SEV-327 contract: first-time ACTIVE transition flips the
user_profile.onboarding_completed flag atomically with the brokerage_account
status update, and replays are no-ops.

Also covers the SEV-528 contract: the same first-time ACTIVE transition
PATCHes Alpaca to enroll the account in the configured FDIC sweep tier,
recording `sweep_status` / `sweep_enrolled_at` on the row.

Requires: Docker + `make infra` + `make migrate`.
Skipped automatically if Postgres is unavailable.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.account_status import apply_account_status_change
from app.services.alpaca_broker import AlpacaBrokerError
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
    """SEV-528: first-time ACTIVE transition writes ``sweep_status`` and
    ``sweep_enrolled_at`` to the row in the same transaction. Tests use a
    mocked Alpaca client (no live broker call) but a real DB so the
    ``update_status(**fields)`` -> column write path is exercised end-to-end."""

    async def test_active_transition_persists_sweep_columns(
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
        alpaca = AsyncMock()
        alpaca.update_account = AsyncMock(return_value={})
        event_time = datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)

        await apply_account_status_change(
            db_session,
            alpaca_account_id=alpaca_id,
            new_status="ACTIVE",
            event_time=event_time,
            alpaca=alpaca,
        )

        alpaca.update_account.assert_awaited_once_with(
            alpaca_id,
            {"cash_interest": {"USD": {"apr_tier_name": "standard"}}},
        )
        row = await db_session.execute(
            text(
                "SELECT sweep_status, sweep_enrolled_at "
                "FROM brokerage_accounts WHERE alpaca_account_id = :aid"
            ),
            {"aid": alpaca_id},
        )
        result = row.one()
        assert result.sweep_status == "PENDING_CHANGE"
        assert result.sweep_enrolled_at == event_time

    async def test_alpaca_error_persists_inactive_but_still_activates(
        self,
        db_session: AsyncSession,
        test_user: uuid.UUID,
        monkeypatch,
    ):
        """Enrollment failure must NOT roll back account activation —
        ``account_status`` still goes ACTIVE, ``activated_at`` is stamped,
        ``sweep_status`` records the failure as INACTIVE."""
        monkeypatch.setattr(
            "app.services.account_status.settings.alpaca_apr_tier_name",
            "standard",
        )
        alpaca_id = f"acct-{uuid.uuid4()}"
        await _insert_brokerage_account(db_session, test_user, alpaca_id)
        alpaca = AsyncMock()
        alpaca.update_account = AsyncMock(
            side_effect=AlpacaBrokerError(503, "upstream down")
        )

        await apply_account_status_change(
            db_session,
            alpaca_account_id=alpaca_id,
            new_status="ACTIVE",
            alpaca=alpaca,
        )

        row = await db_session.execute(
            text(
                "SELECT account_status, activated_at, sweep_status, "
                "sweep_enrolled_at FROM brokerage_accounts "
                "WHERE alpaca_account_id = :aid"
            ),
            {"aid": alpaca_id},
        )
        result = row.one()
        assert result.account_status == "ACTIVE"
        assert result.activated_at is not None
        assert result.sweep_status == "INACTIVE"
        assert result.sweep_enrolled_at is None

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
        alpaca = AsyncMock()
        alpaca.update_account = AsyncMock()

        await apply_account_status_change(
            db_session,
            alpaca_account_id=alpaca_id,
            new_status="ACTIVE",
            alpaca=alpaca,
        )

        alpaca.update_account.assert_not_awaited()
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
