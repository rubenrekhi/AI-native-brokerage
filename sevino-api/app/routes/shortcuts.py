"""FastAPI router for `GET /v1/shortcuts`.

Serves the iOS home-screen chat suggestions: a time-bucket-aware mix of
onboarding and evergreen prompts. Auth-gated; rate-limited via the global
per-user default. Responses are cached per user for 30s.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.cache import cache_get_or_set
from app.database import get_db
from app.dependencies import get_redis
from app.schemas.shortcuts import ShortcutsResponse
from app.services.alpaca_broker import AlpacaBrokerService
from app.services.market_data import MarketDataService
from app.services.shortcuts.service import ShortcutsService
from app.services.shortcuts.time_buckets import ET, current_bucket

router = APIRouter()

_CACHE_TTL = 30


def _get_alpaca(request: Request) -> AlpacaBrokerService | None:
    # Read leniently: shortcuts must still serve (portfolio_state just stays
    # empty) if the broker/market-data singletons aren't wired.
    return getattr(request.app.state, "alpaca", None)


def _get_market_data(request: Request) -> MarketDataService | None:
    return getattr(request.app.state, "market_data", None)


def _shortcuts_service(
    db: AsyncSession = Depends(get_db),
    alpaca: AlpacaBrokerService | None = Depends(_get_alpaca),
    market_data: MarketDataService | None = Depends(_get_market_data),
) -> ShortcutsService:
    return ShortcutsService(db, alpaca, market_data)


@router.get("", response_model=ShortcutsResponse)
async def list_shortcuts(
    user_id: str = Depends(get_current_user),
    redis: aioredis.Redis = Depends(get_redis),
    service: ShortcutsService = Depends(_shortcuts_service),
) -> ShortcutsResponse:
    """Return the user's ranked chat-suggestion shortcuts."""
    now = datetime.now(timezone.utc)
    bucket = current_bucket(now)
    day = now.astimezone(ET).date()

    async def fetch() -> dict:
        response = await service.list_for_user(uuid.UUID(user_id), now=now)
        return response.model_dump(mode="json")

    # Key on (day, bucket) so feed content turns over exactly at bucket
    # boundaries instead of lingering for up to the 30s TTL.
    cache_key = f"shortcuts:{user_id}:{day.isoformat()}:{bucket.value}"
    cached = await cache_get_or_set(redis, cache_key, _CACHE_TTL, fetch)
    return ShortcutsResponse.model_validate(cached)
