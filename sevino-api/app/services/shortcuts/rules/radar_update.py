"""`radar_update` rule: nudges users toward unseen AI radar picks.

Fires when the user has at least one unstarred, unexpired AI-generated
radar item — something still sitting in their radar "New" tab. The
``radar_items`` query is inline (the ``RadarItem`` model only, never
``RadarItemRepository``) so this module stays clear of the repository
edits the AI Radar project makes in parallel.
"""

from __future__ import annotations

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.radar_item import RadarItem
from app.schemas.shortcuts import Shortcut
from app.services.shortcuts.context import ShortcutContext

_AI_SOURCE = "ai_generated"


async def evaluate(ctx: ShortcutContext, db: AsyncSession) -> list[Shortcut]:
    """Emit a single radar nudge when unseen AI picks await the user."""
    stmt = select(
        exists().where(
            RadarItem.user_id == ctx.user_id,
            RadarItem.source == _AI_SOURCE,
            RadarItem.is_favorited.is_(False),
            or_(
                RadarItem.expires_at.is_(None),
                RadarItem.expires_at > func.now(),
            ),
        )
    )
    has_unseen = (await db.execute(stmt)).scalar_one()
    if not has_unseen:
        return []
    return [
        Shortcut.create(text="What's on Radar today?", category="radar_update")
    ]
