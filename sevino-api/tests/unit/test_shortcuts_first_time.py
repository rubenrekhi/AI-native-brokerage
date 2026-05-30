"""Unit tests for the `first_time` shortcut rule."""

import uuid
from datetime import date

from app.services.shortcuts.context import ShortcutContext
from app.services.shortcuts.rules import first_time
from app.services.shortcuts.time_buckets import TimeBucket

USER = uuid.UUID("11111111-1111-1111-1111-111111111111")


def _ctx(
    *,
    account_age_days: int,
    conversation_count: int,
    bucket: TimeBucket = TimeBucket.MORNING,
    day: date = date(2026, 5, 30),
) -> ShortcutContext:
    return ShortcutContext(
        user_id=USER,
        bucket=bucket,
        day=day,
        account_age_days=account_age_days,
        conversation_count=conversation_count,
    )


def test_fires_when_account_is_new():
    result = first_time.evaluate(_ctx(account_age_days=2, conversation_count=10))
    assert result
    assert all(s.category == "first_time" for s in result)


def test_fires_when_few_conversations():
    assert first_time.evaluate(_ctx(account_age_days=30, conversation_count=1))


def test_silent_when_both_gates_clear():
    assert first_time.evaluate(_ctx(account_age_days=7, conversation_count=3)) == []


def test_rotation_is_deterministic():
    ctx = _ctx(account_age_days=1, conversation_count=0)
    assert first_time.evaluate(ctx) == first_time.evaluate(ctx)


def test_rotation_preserves_full_template_set():
    result = first_time.evaluate(_ctx(account_age_days=1, conversation_count=0))
    assert {s.text for s in result} == set(first_time._TEMPLATES)


def test_rotation_changes_across_days():
    orderings = {
        tuple(
            s.text
            for s in first_time.evaluate(
                _ctx(account_age_days=1, conversation_count=0, day=date(2026, 5, d))
            )
        )
        for d in range(1, 13)
    }
    assert len(orderings) > 1
