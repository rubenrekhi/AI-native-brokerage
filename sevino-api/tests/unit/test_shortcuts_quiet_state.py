"""Unit tests for the `quiet_state` shortcut rule."""

import uuid
from datetime import date

import pytest

from app.services.shortcuts.context import ShortcutContext
from app.services.shortcuts.rules import quiet_state
from app.services.shortcuts.time_buckets import TimeBucket

USER = uuid.UUID("22222222-2222-2222-2222-222222222222")

_CROSS = {"What's diversification?", "How does compound interest work?"}

_EXPECTED_BY_BUCKET = {
    TimeBucket.MORNING: {
        "What should I watch this week?",
        "How do I read a stock chart?",
    },
    TimeBucket.MARKET_HOURS: {
        "How do I find a stock to buy?",
        "What are limit orders?",
    },
    TimeBucket.AFTER_MARKET: {
        "How did the market close today?",
        "What were today's biggest movers?",
    },
    TimeBucket.NIGHT: {
        "Explain dollar-cost averaging",
        "How do dividends work?",
        "What's a P/E ratio?",
    },
}


def _ctx(bucket: TimeBucket, day: date = date(2026, 5, 30)) -> ShortcutContext:
    return ShortcutContext(
        user_id=USER,
        bucket=bucket,
        day=day,
        account_age_days=100,
        conversation_count=100,
    )


@pytest.mark.parametrize("bucket", list(TimeBucket))
def test_bucket_returns_its_templates_plus_cross(bucket):
    texts = {s.text for s in quiet_state.evaluate(_ctx(bucket))}
    assert texts == _EXPECTED_BY_BUCKET[bucket] | _CROSS


@pytest.mark.parametrize("bucket", list(TimeBucket))
def test_never_empty(bucket):
    result = quiet_state.evaluate(_ctx(bucket))
    assert result
    assert all(s.category == "quiet_state" for s in result)


def test_rotation_is_deterministic():
    ctx = _ctx(TimeBucket.NIGHT)
    assert quiet_state.evaluate(ctx) == quiet_state.evaluate(ctx)
