"""Anchor advancement for the radar refresh cadence.

`bump_next_refresh` walks the per-user anchor forward by 7 days from the
prior value, not from `now()`. That preserves the user's signup
day-of-week across many runs — the property this file exercises by
bumping repeatedly off a fixed starting anchor and watching `weekday()`
stay put. A separate test covers the re-anchor escape hatch (anchor
behind by more than two weeks → restart from now()), and a third the
first-batch initialization (anchor null → now + 7d).
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.repositories.user_profile import (
    RADAR_CADENCE,
    RADAR_STALE_REANCHOR,
    UserProfileRepository,
)
from tests.integration.conftest import _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync, reason="Local Postgres not running"
)


async def _set_anchor(db_session, user_id, value):
    await db_session.execute(
        text(
            "UPDATE user_profiles SET next_radar_refresh_at = :v WHERE id = :id"
        ),
        {"v": value, "id": user_id},
    )
    await db_session.flush()


async def test_first_bump_anchors_off_now_when_column_is_null(
    db_session, test_user
):
    before = datetime.now(timezone.utc)
    new_anchor = await UserProfileRepository.bump_next_refresh(
        db_session, test_user
    )
    after = datetime.now(timezone.utc)

    # No prior anchor → base = now(), so the new anchor lands in
    # [before + 7d, after + 7d].
    assert before + RADAR_CADENCE <= new_anchor <= after + RADAR_CADENCE


async def test_repeated_bumps_preserve_weekday_off_a_fixed_anchor(
    db_session, test_user
):
    # Tuesday 2026-06-02 14:00 UTC — keep the same hour-of-day too so a
    # regression that snaps to midnight or 00:00 would be obvious.
    start = datetime(2026, 6, 2, 14, 0, tzinfo=timezone.utc)
    assert start.weekday() == 1  # 0=Mon
    await _set_anchor(db_session, test_user, start)

    anchors = []
    for _ in range(5):
        anchors.append(
            await UserProfileRepository.bump_next_refresh(db_session, test_user)
        )

    # Anchors land on Tuesday each time, exactly +7d from the prior step.
    assert all(a.weekday() == 1 for a in anchors)
    expected = [start + RADAR_CADENCE * (i + 1) for i in range(5)]
    assert anchors == expected


async def test_bump_reanchors_from_now_when_prior_anchor_is_far_behind(
    db_session, test_user
):
    # Stale by more than RADAR_STALE_REANCHOR → cadence has drifted off the
    # signup day-of-week anyway, so stacking back-weeks would just produce
    # a future-dated anchor that's *also* in the past. Re-anchor instead.
    stale = datetime.now(timezone.utc) - RADAR_STALE_REANCHOR - timedelta(days=1)
    await _set_anchor(db_session, test_user, stale)

    before = datetime.now(timezone.utc)
    new_anchor = await UserProfileRepository.bump_next_refresh(
        db_session, test_user
    )
    after = datetime.now(timezone.utc)

    assert before + RADAR_CADENCE <= new_anchor <= after + RADAR_CADENCE
    # Critically NOT `stale + 7d`, which would still be far in the past.
    assert new_anchor > stale + RADAR_CADENCE


async def test_bump_off_a_recent_past_anchor_still_advances_from_it(
    db_session, test_user
):
    # 3 days late but still within the stale window → walk forward from
    # the existing anchor (4d ahead of now), preserving cadence.
    recent_past = datetime.now(timezone.utc) - timedelta(days=3)
    await _set_anchor(db_session, test_user, recent_past)

    new_anchor = await UserProfileRepository.bump_next_refresh(
        db_session, test_user
    )
    assert new_anchor == recent_past + RADAR_CADENCE


async def test_try_claim_radar_slot_bumps_when_anchor_is_null_or_past(
    db_session, test_user
):
    # Null anchor → due.
    anchor = await UserProfileRepository.try_claim_radar_slot(
        db_session, test_user
    )
    assert anchor is not None

    # Reset to a past anchor → still due.
    past = datetime.now(timezone.utc) - timedelta(days=1)
    await _set_anchor(db_session, test_user, past)
    anchor = await UserProfileRepository.try_claim_radar_slot(
        db_session, test_user
    )
    assert anchor == past + RADAR_CADENCE


async def test_try_claim_radar_slot_returns_none_when_anchor_is_in_future(
    db_session, test_user
):
    future = datetime.now(timezone.utc) + timedelta(days=3)
    await _set_anchor(db_session, test_user, future)

    result = await UserProfileRepository.try_claim_radar_slot(
        db_session, test_user
    )
    assert result is None

    # Critically: the anchor stays put. No silent advance on the "skip" path.
    from sqlalchemy import select

    from app.models.user_profile import UserProfile

    persisted = (
        await db_session.execute(
            select(UserProfile.next_radar_refresh_at).where(
                UserProfile.id == test_user
            )
        )
    ).scalar_one()
    assert persisted == future
