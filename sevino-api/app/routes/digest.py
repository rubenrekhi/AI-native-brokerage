"""FastAPI router for /v1/digest/*.

Backs the iOS Daily Digest card stack. Auth-gated; rate-limited via the
global per-user default. Does NOT require an active brokerage account —
the read/dismiss paths only touch the persisted snapshot, and a digest may
hold non-portfolio cards (market context, watchlist) for users who haven't
funded yet.

After 9am New York time, the read path has a lazy fallback so a user who
opens before the cron completed still gets today's digest.
"""

import asyncio
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, time, timezone

import structlog
from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.schemas.digest import DigestTodayResponse
from app.services.alpaca_broker import AlpacaBrokerService
from app.services.digest.context import ET
from app.services.digest.service import DigestService

router = APIRouter()
logger = structlog.get_logger(__name__)

LAZY_GENERATION_TIMEOUT_SECONDS = 30.0


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _after_digest_release(now: datetime) -> bool:
    return now.astimezone(ET).time() > time(hour=9)


async def _digest_service(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AsyncGenerator[DigestService, None]:
    alpaca = getattr(request.app.state, "alpaca", None)
    close_alpaca = False
    if alpaca is None:
        alpaca = AlpacaBrokerService()
        close_alpaca = True
    try:
        yield DigestService(
            db,
            alpaca=alpaca,
            market_data=getattr(request.app.state, "market_data", None),
            fmp=getattr(request.app.state, "fmp", None),
            anthropic=getattr(request.app.state, "anthropic", None),
        )
    finally:
        if close_alpaca:
            await alpaca.close()


@router.get(
    "/today",
    response_model=DigestTodayResponse,
    responses={204: {"description": "No digest for today"}},
)
async def get_today(
    user_id: str = Depends(get_current_user),
    service: DigestService = Depends(_digest_service),
) -> Response | DigestTodayResponse:
    """Today's digest, or 204 when none has been generated.

    Returns the snapshot whether or not it's been dismissed; `peek_visible`
    encodes which presentation iOS should use.
    """
    user_uuid = uuid.UUID(user_id)
    snapshot = await service.get_today(user_uuid)
    if snapshot is None and _after_digest_release(_now_utc()):
        logger.info("digest.lazy_fallback.hit", user_id=user_id)
        try:
            snapshot = await asyncio.wait_for(
                service.generate_for_user(user_uuid),
                timeout=LAZY_GENERATION_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            await service.rollback()
            logger.warning("digest_lazy_generation_timeout", user_id=user_id)
            return Response(status_code=status.HTTP_204_NO_CONTENT)
    if snapshot is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return DigestTodayResponse.from_snapshot(snapshot)


@router.post("/dismiss", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss(
    user_id: str = Depends(get_current_user),
    service: DigestService = Depends(_digest_service),
) -> Response:
    """Dismiss today's digest. 404 when there's nothing to dismiss."""
    await service.dismiss(uuid.UUID(user_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
