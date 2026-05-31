"""FastAPI router for /v1/radar/*.

Backs the iOS Radar modal: the per-user list of AI-surfaced and
user-added stocks. Auth-gated; rate-limited via the global per-user
default. Works for any authenticated user — does NOT require an
active brokerage account (the radar is informational, not
trading-gated).
"""

import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.schemas.radar import (
    RadarItemCreate,
    RadarItemRead,
    RadarItemUpdate,
    RadarListResponse,
)
from app.services.market_data import MarketDataService, get_market_data_service
from app.services.radar import RadarService

router = APIRouter()


def _radar_service(
    market_data: MarketDataService = Depends(get_market_data_service),
    db: AsyncSession = Depends(get_db),
) -> RadarService:
    # `market_data` is eagerly wired for every endpoint, even those (POST,
    # PATCH, DELETE) that never call it. Splitting into two factories
    # would double the wiring with no benefit — the only failure mode is
    # `FMP_API_KEY` unset at startup, which is permanent and hard-fails
    # the whole feature, not a transient outage.
    return RadarService(market_data, db)


@router.get("", response_model=RadarListResponse)
async def list_radar(
    user_id: str = Depends(get_current_user),
    service: RadarService = Depends(_radar_service),
) -> RadarListResponse:
    """Return the user's radar items plus the next-refresh anchor."""
    return await service.list_for_user(uuid.UUID(user_id))


@router.post(
    "", response_model=RadarItemRead, status_code=status.HTTP_201_CREATED
)
async def add_radar_item(
    body: RadarItemCreate,
    user_id: str = Depends(get_current_user),
    service: RadarService = Depends(_radar_service),
) -> RadarItemRead:
    """Add a user-chosen ticker to the radar. Auto-favorited, no expiry."""
    return await service.add_user_item(uuid.UUID(user_id), body.symbol)


@router.patch(
    "/{item_id}",
    response_model=RadarItemRead,
    responses={
        204: {"description": "Row deleted (unfavorited user_added)"},
    },
)
async def patch_radar_item(
    item_id: uuid.UUID,
    body: RadarItemUpdate,
    user_id: str = Depends(get_current_user),
    service: RadarService = Depends(_radar_service),
) -> Response | RadarItemRead:
    """Toggle the favorite flag on a radar item the user owns.

    Returns 200 with the updated row in most cases. Returns 204 when
    the flip deletes the row (unfavoriting a `user_added` row — the
    star is the watchlist-membership signal).
    """
    result = await service.toggle_favorite(
        uuid.UUID(user_id), item_id, body.is_favorited
    )
    if result is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return result


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_radar_item(
    item_id: uuid.UUID,
    user_id: str = Depends(get_current_user),
    service: RadarService = Depends(_radar_service),
) -> Response:
    """Remove a radar item the user owns. Hard delete."""
    await service.remove(uuid.UUID(user_id), item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
