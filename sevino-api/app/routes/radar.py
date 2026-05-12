"""FastAPI router for /v1/radar/*.

Backs the iOS Radar modal: the per-user list of AI-surfaced and
user-added stocks. Auth-gated; rate-limited via the global per-user
default. Works for any authenticated user — does NOT require an
active brokerage account (the radar is informational, not
trading-gated).
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.schemas.radar import RadarItemRead
from app.services.radar import RadarService

router = APIRouter()


def _radar_service(db: AsyncSession = Depends(get_db)) -> RadarService:
    return RadarService(db)


@router.get("", response_model=list[RadarItemRead])
async def list_radar(
    user_id: str = Depends(get_current_user),
    service: RadarService = Depends(_radar_service),
) -> list[RadarItemRead]:
    """Return the user's radar items."""
    return await service.list_for_user(uuid.UUID(user_id))
