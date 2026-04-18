import uuid

import structlog
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
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
    """Incremental save — called after every onboarding screen."""
    step = await OnboardingService.save_step(db, uuid.UUID(user_id), body)
    return {"step": step}


@router.post("/submit", response_model=OnboardingSubmitResponse)
async def submit_onboarding(
    body: OnboardingSubmitRequest,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    alpaca: AlpacaBrokerService = Depends(get_alpaca),
) -> OnboardingSubmitResponse:
    """Submit KYC to Alpaca and create brokerage account."""
    result = await OnboardingService.submit_kyc(
        db,
        uuid.UUID(user_id),
        tax_id=body.tax_id,
        tax_id_type=body.tax_id_type,
        alpaca=alpaca,
    )
    return OnboardingSubmitResponse(**result)


@router.get("/status", response_model=OnboardingStatusResponse)
async def get_onboarding_status(
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OnboardingStatusResponse:
    """Return full onboarding state + saved data for resume."""
    return await OnboardingService.get_status(db, uuid.UUID(user_id))
