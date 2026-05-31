"""`quiet_state` rule: always-on, time-bucket-aware default suggestions."""

from __future__ import annotations

from app.schemas.shortcuts import Shortcut
from app.services.shortcuts.context import ShortcutContext
from app.services.shortcuts.rotation import rotate
from app.services.shortcuts.time_buckets import TimeBucket

_BUCKET_TEMPLATES: dict[TimeBucket, list[str]] = {
    TimeBucket.MORNING: [
        "What should I watch this week?",
        "How do I read a stock chart?",
    ],
    TimeBucket.MARKET_HOURS: [
        "How do I research a stock?",
        "What are limit orders?",
    ],
    TimeBucket.AFTER_MARKET: [
        "How did the market close today?",
        "What were today's biggest movers?",
    ],
    TimeBucket.NIGHT: [
        "Explain dollar-cost averaging",
        "How do dividends work?",
        "What's a P/E ratio?",
    ],
}

_CROSS_BUCKET = [
    "What's diversification?",
    "How does compound interest work?",
]


def evaluate(ctx: ShortcutContext) -> list[Shortcut]:
    """Always emit a non-empty, bucket-appropriate set of suggestions."""
    texts = rotate(
        _BUCKET_TEMPLATES[ctx.bucket] + _CROSS_BUCKET,
        user_id=ctx.user_id,
        day=ctx.day,
        bucket=ctx.bucket,
    )
    return [Shortcut.create(text=t, category="quiet_state") for t in texts]
