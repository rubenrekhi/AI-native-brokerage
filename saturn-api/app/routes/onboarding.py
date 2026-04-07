import uuid

import httpx
import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.exceptions import error_response
from app.schemas.onboarding import (
    OnboardingPatchRequest,
    OnboardingStatusResponse,
    OnboardingSubmitRequest,
    OnboardingSubmitResponse,
)
from app.services.alpaca_broker import AlpacaBrokerError, AlpacaBrokerService
from app.services.onboarding import OnboardingService

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.patch("")
async def save_onboarding_step(
    body: OnboardingPatchRequest,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Incremental save — called after every onboarding screen."""
    step = await OnboardingService.save_step(db, uuid.UUID(user_id), body)
    return {"step": step}


@router.post("/submit", response_model=OnboardingSubmitResponse)
async def submit_onboarding(
    body: OnboardingSubmitRequest,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OnboardingSubmitResponse:
    """Submit KYC to Alpaca and create brokerage account."""
    alpaca = AlpacaBrokerService()
    try:
        result = await OnboardingService.submit_kyc(
            db,
            uuid.UUID(user_id),
            tax_id=body.tax_id,
            tax_id_type=body.tax_id_type,
            alpaca=alpaca,
        )
    except AlpacaBrokerError as exc:
        logger.error(
            "alpaca_kyc_submission_failed",
            user_id=user_id,
            status_code=exc.status_code,
            message=exc.message,
        )
        return error_response(
            422, f"KYC submission failed: {exc.message}", "ALPACA_ERROR", detail=exc.detail
        )
    except httpx.HTTPError as exc:
        logger.error("alpaca_connection_failed", user_id=user_id, error=str(exc))
        return error_response(
            503, "Brokerage service unavailable, please try again", "ALPACA_UNAVAILABLE"
        )
    return OnboardingSubmitResponse(**result)


@router.get("/status", response_model=OnboardingStatusResponse)
async def get_onboarding_status(
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OnboardingStatusResponse:
    """Return full onboarding state + saved data for resume."""
    return await OnboardingService.get_status(db, uuid.UUID(user_id))
