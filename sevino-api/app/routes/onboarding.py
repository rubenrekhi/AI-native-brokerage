import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.repositories.user_profile import UserProfileRepository
from app.schemas.onboarding import (
    OnboardingPatchRequest,
    OnboardingStatusResponse,
    OnboardingSubmitRequest,
    OnboardingSubmitResponse,
)
from app.services.alpaca_broker import AlpacaBrokerService
from app.services.onboarding import OnboardingService

logger = structlog.get_logger(__name__)

router = APIRouter()


def get_alpaca(request: Request) -> AlpacaBrokerService:
    return request.app.state.alpaca


@router.patch("")
async def save_onboarding_step(
    body: OnboardingPatchRequest,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    step = await OnboardingService.save_step(db, uuid.UUID(user_id), body)
    return {"step": step}


@router.post("/submit", response_model=OnboardingSubmitResponse)
async def submit_onboarding(
    body: OnboardingSubmitRequest,
    request: Request,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    alpaca: AlpacaBrokerService = Depends(get_alpaca),
) -> OnboardingSubmitResponse:
    """Submit KYC to Alpaca and create brokerage account.

    On success, opt the user into the AI Radar cadence: anchoring
    ``next_radar_refresh_at`` to now is the "radar enabled" signal the
    hourly cron filters on, and we enqueue the first batch immediately so
    the user sees picks without waiting up to an hour. The account is still
    ``SUBMITTED`` here (not ``ACTIVE``), so this first batch has no
    positions — only the diversification/event/notable buckets populate.
    """
    uid = uuid.UUID(user_id)
    result = await OnboardingService.submit_kyc(
        db,
        uid,
        tax_id=body.tax_id,
        tax_id_type=body.tax_id_type,
        alpaca=alpaca,
    )

    await UserProfileRepository.update_fields(
        db, uid, next_radar_refresh_at=datetime.now(timezone.utc)
    )
    # ARQ access lives in the route, not OnboardingService — keeps the
    # service free of queue knowledge (matches app/ai/transport/idempotency.py).
    # `_job_id` is deterministic per-user-per-day so a double-submit collapses
    # to one job.
    #
    # Best-effort: submit_kyc already created the account at Alpaca (a side
    # effect we can't roll back), so a Redis hiccup here must not fail the
    # request and strand that account. The anchor is committed regardless,
    # so the hourly refresh cron picks the user up once their account
    # activates — the first batch is just an optimization to skip that wait.
    try:
        await request.app.state.arq.enqueue_job(
            "generate_radar_batch",
            str(uid),
            _job_id=f"radar_batch:{uid}:{datetime.now(timezone.utc).date().isoformat()}",
        )
    except Exception:
        logger.exception("radar_first_batch_enqueue_failed", user_id=str(uid))

    return OnboardingSubmitResponse(**result)


@router.get("/status", response_model=OnboardingStatusResponse)
async def get_onboarding_status(
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OnboardingStatusResponse:
    """Return full onboarding state + saved data for resume."""
    return await OnboardingService.get_status(db, uuid.UUID(user_id))
