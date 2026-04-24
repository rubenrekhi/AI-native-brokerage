"""FastAPI router for /v1/settings/*."""

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.schemas.settings import AccountValueResponse, SettingsProfileResponse
from app.services.alpaca_broker import AlpacaBrokerService
from app.services.settings import SettingsService

router = APIRouter()


def get_alpaca(request: Request) -> AlpacaBrokerService:
    return request.app.state.alpaca


@router.get("/profile", response_model=SettingsProfileResponse)
async def get_settings_profile(
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SettingsProfileResponse:
    """Aggregate profile view for settings screens."""
    return await SettingsService.get_profile(db, uuid.UUID(user_id))


@router.get("/account-value", response_model=AccountValueResponse)
async def get_account_value(
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    alpaca: AlpacaBrokerService = Depends(get_alpaca),
) -> AccountValueResponse:
    return await SettingsService.get_account_value(
        db, alpaca=alpaca, user_id=uuid.UUID(user_id)
    )
