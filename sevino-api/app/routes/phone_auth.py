import uuid
from datetime import datetime, timezone

import sentry_sdk
import structlog
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_access_token, get_current_user
from app.database import get_db
from app.rate_limit import get_remote_address, limiter
from app.repositories.user_profile import UserProfileRepository
from app.schemas.phone_auth import (
    ConfirmVerificationRequest,
    ConfirmVerificationResponse,
    SendVerificationRequest,
    SendVerificationResponse,
)
from app.services.phone_verification import PhoneVerificationService

logger = structlog.get_logger(__name__)

router = APIRouter()


def get_phone_verification(request: Request) -> PhoneVerificationService:
    return request.app.state.phone_verification


@router.post("/phone/send-verification", response_model=SendVerificationResponse)
@limiter.limit("5/hour")
@limiter.limit("20/hour", key_func=get_remote_address)
async def send_verification(
    request: Request,
    body: SendVerificationRequest,
    user_id: str = Depends(get_current_user),
    access_token: str = Depends(get_access_token),
    phone_verification: PhoneVerificationService = Depends(get_phone_verification),
) -> SendVerificationResponse:
    """Send a 6-digit SMS OTP to the given phone number via Supabase GoTrue."""
    await phone_verification.send(
        user_jwt=access_token, phone_number=body.phone_number
    )
    logger.info("phone_verification_sent", user_id=user_id)
    return SendVerificationResponse()


@router.post("/phone/confirm", response_model=ConfirmVerificationResponse)
@limiter.limit("5/minute")
@limiter.limit("30/minute", key_func=get_remote_address)
async def confirm_verification(
    request: Request,
    body: ConfirmVerificationRequest,
    user_id: str = Depends(get_current_user),
    access_token: str = Depends(get_access_token),
    db: AsyncSession = Depends(get_db),
    phone_verification: PhoneVerificationService = Depends(get_phone_verification),
) -> ConfirmVerificationResponse:
    """Confirm the OTP; on success mark phone_verified_at on the user profile."""
    result = await phone_verification.confirm(
        user_jwt=access_token,
        phone_number=body.phone_number,
        token=body.code,
    )
    # GoTrue returns the authoritative, normalized phone on its user object —
    # trust that over the request body so we persist what Supabase has actually
    # bound to the auth.users row.
    confirmed_phone = (
        (result or {}).get("user", {}).get("phone") or body.phone_number
    )
    verified_at = datetime.now(timezone.utc)
    try:
        await UserProfileRepository.update_fields(
            db,
            uuid.UUID(user_id),
            phone_number=confirmed_phone,
            phone_verified_at=verified_at,
        )
    except Exception as exc:
        # GoTrue already flipped the phone on auth.users but we failed to mirror
        # it onto user_profiles — the two stores are now out of sync. Surface
        # loudly so the drift can be reconciled.
        with sentry_sdk.new_scope() as scope:
            scope.set_tag("operation", "phone_confirm_db_write")
            scope.set_context(
                "phone_confirm",
                {"user_id": user_id, "phone": confirmed_phone},
            )
            sentry_sdk.capture_message(
                f"phone_confirm_db_write_failed: {exc!r}",
                level="error",
            )
        raise
    logger.info("phone_verification_confirmed", user_id=user_id)
    return ConfirmVerificationResponse(phone_verified_at=verified_at)
