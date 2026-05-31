"""`capability` rule: rotating feature-discovery prompts.

Always a candidate. Surfaces a couple of "things you can ask" that turn
over across the day by rotating the pool on ``(user, day, bucket)`` via
the shared deterministic rotation, so the 30s cache and client agree on
what to show.
"""

from __future__ import annotations

from app.schemas.shortcuts import Shortcut
from app.services.shortcuts.context import ShortcutContext
from app.services.shortcuts.rotation import rotate

_TEMPLATES = [
    "Compare AAPL and MSFT",
    "How can I auto-invest?",
    "Explain my portfolio's risk profile",
    "Show me my biggest movers this week",
    "What's the best ETF for beginners?",
]

_PICKS = 2


def evaluate(ctx: ShortcutContext) -> list[Shortcut]:
    """Emit two rotating capability prompts."""
    texts = rotate(
        _TEMPLATES, user_id=ctx.user_id, day=ctx.day, bucket=ctx.bucket
    )[:_PICKS]
    return [Shortcut.create(text=t, category="capability") for t in texts]
