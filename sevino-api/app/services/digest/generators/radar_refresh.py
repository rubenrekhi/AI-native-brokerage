from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.radar_item import SOURCE_AI_GENERATED, RadarItemRepository
from app.repositories.user_profile import UserProfileRepository
from app.services.alpaca_broker import AlpacaBrokerService
from app.services.digest.cards import RadarRefreshCard
from app.services.digest.context import ET
from app.services.digest.types import CardCandidate, DigestContext

RADAR_REFRESH_MAGNITUDE = 5.0


class RadarRefreshGenerator:
    """Emits a fixed-weight card when new AI radar rows appear today."""

    async def generate(
        self,
        ctx: DigestContext,
        db: AsyncSession,
        _alpaca: AlpacaBrokerService,
    ) -> list[CardCandidate]:
        profile = await UserProfileRepository.get_by_id(db, ctx.user_id)
        if profile is None or profile.next_radar_refresh_at is None:
            return []

        items = await RadarItemRepository.list_for_user(db, ctx.user_id)
        today = ctx.market_state.as_of.astimezone(ET).date()
        new_ai_items = [
            item
            for item in items
            if item.source == SOURCE_AI_GENERATED
            and _ny_date(getattr(item, "created_at", None)) == today
        ]
        if not new_ai_items:
            return []

        refreshed_at = max(_aware_created_at(item) for item in new_ai_items)
        related_symbols = sorted({item.symbol.upper() for item in new_ai_items})

        card = RadarRefreshCard(
            refreshed_at=refreshed_at,
            new_count=len(new_ai_items),
            # TODO(SEV-631): persist the radar rotation delete count so this
            # can report prior AI rows removed instead of "unknown".
            removed_count=0,
            related_symbols=related_symbols,
            card_context={
                "refresh_date": today.isoformat(),
                "counts_source": "radar_items.created_at",
                "removed_count_source": "not_tracked",
            },
        )
        return [
            CardCandidate(
                card=card,
                event_type="radar_refresh",
                magnitude_score=RADAR_REFRESH_MAGNITUDE,
                related_symbols=related_symbols,
                dedupe_key=f"radar_refresh:{ctx.user_id}:{today.isoformat()}",
            )
        ]


def _ny_date(value: datetime | None) -> date | None:
    if value is None:
        return None
    return _aware(value).astimezone(ET).date()


def _aware_created_at(item) -> datetime:
    return _aware(item.created_at)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
