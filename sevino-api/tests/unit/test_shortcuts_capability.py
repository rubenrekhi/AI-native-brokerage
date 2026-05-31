"""Unit tests for the `capability` shortcut rule."""

import uuid
from datetime import date

import pytest

from app.services.shortcuts.context import ShortcutContext
from app.services.shortcuts.rules import capability
from app.services.shortcuts.time_buckets import TimeBucket

USER = uuid.UUID("55555555-5555-5555-5555-555555555555")


def _ctx(
    bucket: TimeBucket,
    *,
    day: date = date(2026, 5, 30),
    user: uuid.UUID = USER,
) -> ShortcutContext:
    return ShortcutContext(
        user_id=user,
        bucket=bucket,
        day=day,
        account_age_days=100,
        conversation_count=100,
    )


def _texts(ctx: ShortcutContext) -> list[str]:
    return [s.text for s in capability.evaluate(ctx)]


def test_picks_two_capability_shortcuts():
    out = capability.evaluate(_ctx(TimeBucket.MARKET_HOURS))
    assert len(out) == 2
    assert all(s.category == "capability" for s in out)
    assert all(s.text in capability._TEMPLATES for s in out)
    assert out[0].text != out[1].text


def test_rotation_is_deterministic():
    ctx = _ctx(TimeBucket.MARKET_HOURS)
    assert capability.evaluate(ctx) == capability.evaluate(ctx)


# 2026-05-31 is chosen because the rotation offsets for these two buckets
# diverge that day (with only five templates, not every day separates them).
def test_different_buckets_same_day_differ():
    day = date(2026, 5, 31)
    assert _texts(_ctx(TimeBucket.MORNING, day=day)) != _texts(
        _ctx(TimeBucket.MARKET_HOURS, day=day)
    )


# Likewise these two days separate the NIGHT rotation for this user.
def test_different_days_differ():
    assert _texts(_ctx(TimeBucket.NIGHT, day=date(2026, 5, 31))) != _texts(
        _ctx(TimeBucket.NIGHT, day=date(2026, 6, 1))
    )


@pytest.mark.parametrize("bucket", list(TimeBucket))
def test_always_emits_two_for_every_bucket(bucket):
    assert len(capability.evaluate(_ctx(bucket))) == 2
