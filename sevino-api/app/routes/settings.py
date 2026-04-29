import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.schemas.settings import (
    AccountValueResponse,
    DeleteAccountRequest,
    DocumentListResponse,
    ProfileUpdateRequest,
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


@router.patch("/profile", response_model=SettingsProfileResponse)
async def update_settings_profile(
    body: ProfileUpdateRequest,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    alpaca: AlpacaBrokerService = Depends(get_alpaca),
) -> SettingsProfileResponse:
    """Update profile fields, syncing to Alpaca when the brokerage is ACTIVE."""
    return await SettingsService.update_profile(
        db, uuid.UUID(user_id), body, alpaca
    )


@router.get("/account-value", response_model=AccountValueResponse)
async def get_account_value(
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    alpaca: AlpacaBrokerService = Depends(get_alpaca),
) -> AccountValueResponse:
    return await SettingsService.get_account_value(
        db, alpaca=alpaca, user_id=uuid.UUID(user_id)
    )


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(
    document_type: str | None = Query(
        None, alias="type", pattern=r"^[a-z][a-z0-9_]{0,63}$"
    ),
    start: date | None = None,
    end: date | None = None,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    alpaca: AlpacaBrokerService = Depends(get_alpaca),
) -> DocumentListResponse:
    return await SettingsService.list_documents(
        db,
        alpaca=alpaca,
        user_id=uuid.UUID(user_id),
        document_type=document_type,
        start=start,
        end=end,
    )


@router.get("/documents/{document_id}/download")
async def download_document(
    document_id: uuid.UUID,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    alpaca: AlpacaBrokerService = Depends(get_alpaca),
) -> StreamingResponse:
    stream = await SettingsService.download_document(
        db,
        alpaca=alpaca,
        user_id=uuid.UUID(user_id),
        document_id=str(document_id),
    )
    return StreamingResponse(
        stream,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{document_id}.pdf"'
        },
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


@router.delete("/brokerage-account", status_code=status.HTTP_204_NO_CONTENT)
async def close_brokerage_account(
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    alpaca: AlpacaBrokerService = Depends(get_alpaca),
) -> Response:
    """Close the Alpaca brokerage account while keeping the Sevino profile."""
    await SettingsService.close_brokerage_account(db, uuid.UUID(user_id), alpaca)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
