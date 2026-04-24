"""FastAPI router for /v1/settings/*."""

import uuid

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.schemas.settings import (
    AccountValueResponse,
    DeleteAccountRequest,
    SettingsProfileResponse,
    UserSettingsPatchRequest,
    UserSettingsResponse,
)
from app.services.alpaca_broker import AlpacaBrokerService
from app.services.settings import SettingsService
from app.services.supabase_admin import SupabaseAdminService

router = APIRouter()


def get_alpaca(request: Request) -> AlpacaBrokerService:
    return request.app.state.alpaca


def get_supabase_admin(request: Request) -> SupabaseAdminService:
    return request.app.state.supabase_admin


@router.get("", response_model=UserSettingsResponse)
async def get_settings(
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserSettingsResponse:
    settings = await SettingsService.get_settings(db, uuid.UUID(user_id))
    return UserSettingsResponse.model_validate(settings)


@router.patch("", response_model=UserSettingsResponse)
async def update_settings(
    body: UserSettingsPatchRequest,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserSettingsResponse:
    settings = await SettingsService.update_settings(db, uuid.UUID(user_id), body)
    return UserSettingsResponse.model_validate(settings)


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


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    _body: DeleteAccountRequest,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    alpaca: AlpacaBrokerService = Depends(get_alpaca),
    supabase_admin: SupabaseAdminService = Depends(get_supabase_admin),
) -> Response:
    """Fully delete the authenticated user's account: close Alpaca, purge DB, remove auth user."""
    await SettingsService.delete_account(
        db, uuid.UUID(user_id), alpaca, supabase_admin
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
