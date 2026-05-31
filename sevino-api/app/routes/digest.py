"""FastAPI router for /v1/digest/*.

Backs the iOS Daily Digest card stack. Auth-gated; rate-limited via the
global per-user default. Does NOT require an active brokerage account —
the read/dismiss paths only touch the persisted snapshot, and a digest may
hold non-portfolio cards (market context, watchlist) for users who haven't
funded yet.

Generation is not a route concern in T1 (the morning cron lands in T12),
so the service is constructed without an Alpaca client.
"""

import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.schemas.digest import DigestTodayResponse
from app.services.digest.service import DigestService

router = APIRouter()


def _digest_service(db: AsyncSession = Depends(get_db)) -> DigestService:
    return DigestService(db)


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
    snapshot = await service.get_today(uuid.UUID(user_id))
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
