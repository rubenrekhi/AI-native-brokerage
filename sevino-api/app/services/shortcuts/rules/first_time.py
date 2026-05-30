"""`first_time` rule: onboarding-oriented suggestions for new users."""

from __future__ import annotations

from app.schemas.shortcuts import Shortcut
from app.services.shortcuts.context import ShortcutContext
from app.services.shortcuts.rotation import rotate

ACCOUNT_AGE_GATE_DAYS = 7
CONVERSATION_GATE = 3

_TEMPLATES = [
    "How does Sevino work?",
    "What's on Radar?",
    "Explain what an ETF is",
    "Show me my portfolio",
    "What can you help me with?",
]


def evaluate(ctx: ShortcutContext) -> list[Shortcut]:
    """Emit onboarding shortcuts while the user is new; silent once settled.

    Fires when the account is under a week old OR the user has had fewer
    than three conversations.
    """
    if (
        ctx.account_age_days >= ACCOUNT_AGE_GATE_DAYS
        and ctx.conversation_count >= CONVERSATION_GATE
    ):
        return []
    texts = rotate(
        _TEMPLATES, user_id=ctx.user_id, day=ctx.day, bucket=ctx.bucket
    )
    return [Shortcut.create(text=t, category="first_time") for t in texts]
