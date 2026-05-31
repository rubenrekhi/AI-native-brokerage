"""Repository tests for `UserProfileRepository.list_users_due_for_refresh`.

The cron's enqueue set: onboarded users whose anchor is non-null and at
or before now. Future anchors, null anchors, and not-yet-onboarded users
are all excluded.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.repositories.user_profile import UserProfileRepository
from tests.integration.conftest import _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync, reason="Local Postgres not running"
)


async def _set_radar_state(
    db_session,
    user_id: uuid.UUID,
    *,
    anchor: datetime | None,
    onboarding_completed: bool,
) -> None:
    await db_session.execute(
        text(
            "UPDATE user_profiles SET next_radar_refresh_at = :anchor, "
            "onboarding_completed = :done WHERE id = :id"
        ),
        {"anchor": anchor, "done": onboarding_completed, "id": user_id},
    )
    await db_session.flush()


async def test_returns_only_past_due_onboarded_users(
    db_session, test_user, make_extra_user
):
    now = datetime.now(timezone.utc)

    # test_user: due (past anchor, onboarded) → included.
    await _set_radar_state(
        db_session, test_user, anchor=now - timedelta(hours=1),
        onboarding_completed=True,
    )

    future = await make_extra_user()
    await _set_radar_state(
        db_session, future, anchor=now + timedelta(days=3),
        onboarding_completed=True,
    )

    null_anchor = await make_extra_user()
    await _set_radar_state(
        db_session, null_anchor, anchor=None, onboarding_completed=True,
    )

    not_onboarded = await make_extra_user()
    await _set_radar_state(
        db_session, not_onboarded, anchor=now - timedelta(hours=1),
        onboarding_completed=False,
    )

    due = await UserProfileRepository.list_users_due_for_refresh(db_session, now)

    assert test_user in due
    assert future not in due
    assert null_anchor not in due
    assert not_onboarded not in due


async def test_anchor_exactly_now_is_due(db_session, test_user):
    """The predicate is ``<= now`` — an anchor landing exactly on the cron
    tick must be picked up, not skipped."""
    now = datetime.now(timezone.utc)
    await _set_radar_state(
        db_session, test_user, anchor=now, onboarding_completed=True
    )

    due = await UserProfileRepository.list_users_due_for_refresh(db_session, now)

    assert test_user in due


async def test_returns_empty_when_no_users_due(
    db_session, test_user, make_extra_user
):
    now = datetime.now(timezone.utc)
    await _set_radar_state(
        db_session, test_user, anchor=now + timedelta(days=1),
        onboarding_completed=True,
    )
    other = await make_extra_user()
    await _set_radar_state(
        db_session, other, anchor=None, onboarding_completed=True
    )

    due = await UserProfileRepository.list_users_due_for_refresh(db_session, now)

    assert test_user not in due
    assert other not in due
