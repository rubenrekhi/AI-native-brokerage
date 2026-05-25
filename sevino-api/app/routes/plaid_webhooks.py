"""Plaid webhook receiver.

Public endpoint — authenticated by JWT signature in the `Plaid-Verification`
header (see `app.services.plaid_webhooks.verify_webhook`). Always returns 200
on payloads we accept, even when the referenced `item_id` is unknown locally,
so Plaid stops retrying. The middleware skiplist in `app/middleware/api_key.py`
exempts this path from the X-API-Key gate.
"""

import json

import structlog
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.exceptions import error_response
from app.rate_limit import get_remote_address, limiter
from app.repositories.plaid_item import PlaidItemRepository
from app.services.plaid import PlaidService, PlaidServiceError
from app.services.plaid_webhooks import verify_webhook

logger = structlog.get_logger(__name__)

router = APIRouter()


_REAUTH_WEBHOOK_CODES = frozenset(
    {"PENDING_EXPIRATION", "PENDING_DISCONNECT", "USER_PERMISSION_REVOKED"}
)
_REAUTH_ERROR_CODES = frozenset({"ITEM_LOGIN_REQUIRED"})


def get_plaid(request: Request) -> PlaidService:
    return request.app.state.plaid


@router.post("")
@limiter.limit("60/minute", key_func=get_remote_address)
async def plaid_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    plaid: PlaidService = Depends(get_plaid),
    plaid_verification: str | None = Header(default=None),
) -> Response:
    raw_body = await request.body()

    try:
        await verify_webhook(
            plaid, raw_body=raw_body, signature_header=plaid_verification
        )
    except PlaidServiceError as exc:
        return error_response(
            exc.status_code or 401, exc.message, exc.code
        )

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        # Signature verified a payload that doesn't parse as JSON — Plaid
        # wouldn't sign garbage, so this should be unreachable. Ack anyway so
        # Plaid stops retrying.
        logger.warning("plaid_webhook_unparseable_body")
        return Response(status_code=200)

    if payload.get("webhook_type") != "ITEM":
        return Response(status_code=200)

    item_id = payload.get("item_id")
    if not item_id:
        return Response(status_code=200)

    webhook_code = payload.get("webhook_code")
    updated = None

    if webhook_code == "ERROR":
        error_code = (payload.get("error") or {}).get("error_code")
        if error_code in _REAUTH_ERROR_CODES:
            updated = await PlaidItemRepository.mark_requires_reauth(db, item_id)
    elif webhook_code in _REAUTH_WEBHOOK_CODES:
        updated = await PlaidItemRepository.mark_requires_reauth(db, item_id)
    elif webhook_code == "LOGIN_REPAIRED":
        existing = await PlaidItemRepository.get_by_plaid_item_id(db, item_id)
        if existing is not None:
            await PlaidItemRepository.mark_active(db, existing.id)
            updated = existing

    if updated is not None:
        logger.info(
            "plaid_item_status_updated",
            plaid_item_id=item_id,
            user_id=str(updated.user_id),
            webhook_code=webhook_code,
            new_status=updated.status,
        )

    return Response(status_code=200)
