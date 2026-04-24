"""Settings service: user preferences CRUD + read-only views over brokerage state."""

import uuid
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal, InvalidOperation

import sentry_sdk
import structlog
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, NotFoundError
from app.models.user_settings import UserSettings
from app.repositories.ach_relationship import AchRelationshipRepository
from app.repositories.brokerage_account import (
    STATUS_ACCOUNT_CLOSED,
    STATUS_ACTIVE,
    BrokerageAccountRepository,
)
from app.repositories.financial_profile import FinancialProfileRepository
from app.repositories.user_profile import UserProfileRepository
from app.repositories.user_settings import UserSettingsRepository
from app.schemas.onboarding import FinancialProfileData, ProfileData
from app.schemas.settings import (
    AccountValueResponse,
    BrokerageAccountSummary,
    DocumentListResponse,
    DocumentResponse,
    LinkedAccountSummary,
    ProfileUpdateRequest,
    SettingsProfileResponse,
    UserSettingsPatchRequest,
)
from app.services.alpaca_broker import (
    PENDING_TRANSFER_STATUSES,
    AlpacaBrokerError,
    AlpacaBrokerService,
)
from app.services.supabase_admin import (
    SupabaseAdminError,
    SupabaseAdminService,
    SupabaseAdminUnavailableError,
)

logger = structlog.get_logger(__name__)

_ACCOUNT_VALUE_FIELDS = ("equity", "cash", "buying_power", "portfolio_value")
# Alpaca account states where no live account exists to close. Everything else
# (ONBOARDING, SUBMITTED, APPROVED, ACTIVE, ACTION_REQUIRED, etc.) represents an
# account that must be closed to honor a delete request.
_BROKERAGE_TERMINAL_STATUSES = frozenset({STATUS_ACCOUNT_CLOSED, "REJECTED"})


class SettingsService:
    @staticmethod
    async def get_settings(
        db: AsyncSession, user_id: uuid.UUID
    ) -> UserSettings:
        settings = await UserSettingsRepository.get_by_user_id(db, user_id)
        if settings is not None:
            return settings
        return UserSettings(
            user_id=user_id,
            theme="system",
            text_size="standard",
            notifications_enabled=True,
            ai_internet_access=True,
        )

    @staticmethod
    async def update_settings(
        db: AsyncSession,
        user_id: uuid.UUID,
        data: UserSettingsPatchRequest,
    ) -> UserSettings:
        fields = data.model_dump(exclude_none=True)
        return await UserSettingsRepository.upsert(db, user_id, **fields)

    @staticmethod
    async def update_profile(
        db: AsyncSession,
        user_id: uuid.UUID,
        data: ProfileUpdateRequest,
        alpaca: AlpacaBrokerService,
    ) -> SettingsProfileResponse:
        """Update the user's profile, syncing Alpaca-tracked fields when the
        brokerage account is ACTIVE.

        Alpaca is the source of truth for regulated contact/identity fields on
        an open account, so we PATCH it whenever one of those fields changes.
        `preferred_name` is Sevino-only and never flows to Alpaca.
        """
        fields = data.model_dump(exclude_none=True)
        await UserProfileRepository.update_fields(db, user_id, **fields)

        alpaca_payload = _build_alpaca_profile_update_payload(fields)
        if alpaca_payload:
            brokerage = await BrokerageAccountRepository.get_by_user_id(db, user_id)
            if brokerage is not None and brokerage.account_status == STATUS_ACTIVE:
                logger.info(
                    "profile_update_syncing_alpaca",
                    user_id=str(user_id),
                    alpaca_account_id=brokerage.alpaca_account_id,
                    sections=sorted(alpaca_payload.keys()),
                )
                await alpaca.update_account(
                    brokerage.alpaca_account_id, alpaca_payload
                )

        return await SettingsService.get_profile(db, user_id)

    @staticmethod
    async def get_profile(
        db: AsyncSession, user_id: uuid.UUID
    ) -> SettingsProfileResponse:
        profile = await UserProfileRepository.get_by_id(db, user_id)
        if profile is None:
            raise NotFoundError("User profile not found", resource="user_profile")

        financial = await FinancialProfileRepository.get_by_user_id(db, user_id)
        brokerage = await BrokerageAccountRepository.get_by_user_id(db, user_id)
        linked = await AchRelationshipRepository.list_active_for_user(db, user_id)

        return SettingsProfileResponse(
            profile=ProfileData.model_validate(profile),
            financial_profile=(
                FinancialProfileData.model_validate(financial) if financial else None
            ),
            brokerage=(
                BrokerageAccountSummary.model_validate(brokerage) if brokerage else None
            ),
            linked_accounts=[
                LinkedAccountSummary.model_validate(rel) for rel in linked
            ],
            member_since=profile.created_at,
        )

    @staticmethod
    async def get_account_value(
        db: AsyncSession,
        *,
        alpaca: AlpacaBrokerService,
        user_id: uuid.UUID,
    ) -> AccountValueResponse:
        brokerage = await BrokerageAccountRepository.get_by_user_id(db, user_id)
        if brokerage is None:
            logger.warning("account_value_no_brokerage", user_id=str(user_id))
            raise NotFoundError(
                "Brokerage account not found", resource="brokerage_account"
            )

        account = await alpaca.get_trading_account(brokerage.alpaca_account_id)
        missing = [f for f in _ACCOUNT_VALUE_FIELDS if account.get(f) is None]
        if missing:
            # Alpaca changed shape or returned a degenerate payload. Surface as
            # a 502 via AlpacaBrokerError so it gets logged/Sentry'd rather
            # than silently returning nulls to the client.
            logger.error(
                "account_value_missing_fields",
                user_id=str(user_id),
                alpaca_account_id=brokerage.alpaca_account_id,
                missing=missing,
            )
            raise AlpacaBrokerError(
                status_code=502,
                message="Alpaca trading-account response missing required fields",
                detail={"missing": missing},
            )

        return AccountValueResponse(
            equity=account["equity"],
            cash=account["cash"],
            buying_power=account["buying_power"],
            portfolio_value=account["portfolio_value"],
        )

    @staticmethod
    async def list_documents(
        db: AsyncSession,
        *,
        alpaca: AlpacaBrokerService,
        user_id: uuid.UUID,
        document_type: str | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> DocumentListResponse:
        brokerage = await BrokerageAccountRepository.get_by_user_id(db, user_id)
        if brokerage is None:
            raise NotFoundError(
                "Brokerage account not found", resource="brokerage_account"
            )

        raw = await alpaca.list_documents(
            brokerage.alpaca_account_id,
            document_type=document_type,
            start=start.isoformat() if start else None,
            end=end.isoformat() if end else None,
        )
        documents: list[DocumentResponse] = []
        for d in raw:
            try:
                documents.append(DocumentResponse.model_validate(d))
            except ValidationError as exc:
                # Skip malformed entries rather than 500 the whole list if
                # Alpaca adds/drops a field on a single doc.
                logger.warning(
                    "alpaca_document_malformed",
                    user_id=str(user_id),
                    alpaca_account_id=brokerage.alpaca_account_id,
                    raw=d,
                    error=str(exc),
                )
        return DocumentListResponse(documents=documents)

    @staticmethod
    async def download_document(
        db: AsyncSession,
        *,
        alpaca: AlpacaBrokerService,
        user_id: uuid.UUID,
        document_id: str,
    ) -> AsyncIterator[bytes]:
        brokerage = await BrokerageAccountRepository.get_by_user_id(db, user_id)
        if brokerage is None:
            raise NotFoundError(
                "Brokerage account not found", resource="brokerage_account"
            )

        logger.info(
            "document_download",
            user_id=str(user_id),
            alpaca_account_id=brokerage.alpaca_account_id,
            document_id=document_id,
        )
        return await alpaca.stream_document(
            brokerage.alpaca_account_id, document_id
        )

    @staticmethod
    async def delete_account(
        db: AsyncSession,
        user_id: uuid.UUID,
        alpaca: AlpacaBrokerService,
        supabase_admin: SupabaseAdminService,
    ) -> None:
        """Cascade-delete a user: close Alpaca account, purge DB rows, delete Supabase auth user.

        Order chosen to minimize the blast radius of partial failure:
        1. Close the Alpaca brokerage account if an open one exists — the only
           irreversible external side-effect; fail fast before touching our DB.
        2. Commit the `user_profiles` delete immediately so subsequent failures
           can't resurrect a user whose Alpaca account is already closed. Cascade
           FKs purge financial_profile / settings / brokerage_account /
           plaid_items / ach_relationships.
        3. Delete the Supabase `auth.users` row. Failures here are logged and
           reported to Sentry but NOT re-raised — the DB row is already gone,
           the Alpaca account is already closed, and a lingering auth row is an
           orphan to be reconciled out-of-band, not a reason to 5xx the client.
        """
        profile = await UserProfileRepository.get_by_id(db, user_id)
        if profile is None:
            raise NotFoundError("User profile not found", resource="user_profile")

        brokerage = await BrokerageAccountRepository.get_by_user_id(db, user_id)
        if brokerage is None:
            logger.info(
                "delete_account_skipped_alpaca_close",
                user_id=str(user_id),
                reason="no_brokerage_account",
            )
        elif brokerage.account_status in _BROKERAGE_TERMINAL_STATUSES:
            logger.info(
                "delete_account_skipped_alpaca_close",
                user_id=str(user_id),
                alpaca_account_id=brokerage.alpaca_account_id,
                reason="terminal_status",
                account_status=brokerage.account_status,
            )
        else:
            logger.info(
                "delete_account_closing_alpaca",
                user_id=str(user_id),
                alpaca_account_id=brokerage.alpaca_account_id,
                account_status=brokerage.account_status,
            )
            await alpaca.close_account(brokerage.alpaca_account_id)

        await db.delete(profile)
        # Commit immediately so the DB state is durable before we attempt the
        # Supabase admin call. Without this, a transient GoTrue error would roll
        # back the profile delete and leave the user with a closed Alpaca
        # account but an active DB row — the "zombie" state.
        await db.commit()

        try:
            await supabase_admin.delete_user(str(user_id))
        except (SupabaseAdminError, SupabaseAdminUnavailableError) as exc:
            # Profile row and Alpaca account are gone; an orphan auth.users row
            # is operationally notable but must not fail the request.
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("alert_type", "supabase_admin_delete_orphaned")
                scope.set_context(
                    "delete_account",
                    {
                        "user_id": str(user_id),
                        "stage": "supabase_delete_after_db_commit",
                    },
                )
                sentry_sdk.capture_exception(exc)
            logger.error(
                "delete_account_supabase_orphan",
                user_id=str(user_id),
                error=str(exc),
            )
            return

        logger.info("delete_account_completed", user_id=str(user_id))

    @staticmethod
    async def close_brokerage_account(
        db: AsyncSession,
        user_id: uuid.UUID,
        alpaca: AlpacaBrokerService,
    ) -> None:
        """Close the user's Alpaca brokerage account, leaving the Sevino profile intact.

        Unlike `delete_account`, this leaves `user_profiles` and auth rows in
        place — the user keeps their login and can re-onboard later. Only the
        brokerage side is torn down. Safety gates block closure while funds or
        positions are still at Alpaca.

        Order: Alpaca close → DB status update. If the DB commit fails after
        Alpaca has been told to close, the client gets a 500 while the local
        row stays `ACTIVE`; reconciliation is expected to rebuild status from
        Alpaca out-of-band. Mirrors the tradeoff documented in `delete_account`.
        """
        brokerage = await _require_active_brokerage_for_close(db, user_id)
        await _block_if_open_positions(alpaca, brokerage, user_id)
        await _block_if_pending_transfers(alpaca, brokerage, user_id)
        await _block_if_non_zero_cash(alpaca, brokerage, user_id)

        logger.info(
            "close_brokerage_closing_alpaca",
            user_id=str(user_id),
            alpaca_account_id=brokerage.alpaca_account_id,
        )
        await alpaca.close_account(brokerage.alpaca_account_id)
        await BrokerageAccountRepository.update_status(
            db, brokerage.id, STATUS_ACCOUNT_CLOSED
        )
        await db.commit()
        logger.info(
            "close_brokerage_completed",
            user_id=str(user_id),
            alpaca_account_id=brokerage.alpaca_account_id,
        )


_ALPACA_CONTACT_FIELDS = ("phone_number", "street_address", "city", "state", "postal_code")
_ALPACA_IDENTITY_MAP = {
    "first_name": "given_name",
    "middle_name": "middle_name",
    "last_name": "family_name",
}


def _build_alpaca_profile_update_payload(fields: dict) -> dict:
    contact = {k: fields[k] for k in _ALPACA_CONTACT_FIELDS if k in fields}
    identity = {
        alpaca_key: fields[local_key]
        for local_key, alpaca_key in _ALPACA_IDENTITY_MAP.items()
        if local_key in fields
    }
    payload: dict = {}
    if contact:
        payload["contact"] = contact
    if identity:
        payload["identity"] = identity
    return payload


async def _require_active_brokerage_for_close(db: AsyncSession, user_id: uuid.UUID):
    brokerage = await BrokerageAccountRepository.get_by_user_id(db, user_id)
    if brokerage is None or brokerage.account_status != STATUS_ACTIVE:
        raise NotFoundError(
            "Active brokerage account not found",
            resource="brokerage_account",
        )
    return brokerage


async def _block_if_open_positions(
    alpaca: AlpacaBrokerService, brokerage, user_id: uuid.UUID
) -> None:
    positions = await alpaca.list_positions(brokerage.alpaca_account_id)
    if not positions:
        return
    logger.warning(
        "close_brokerage_blocked_open_positions",
        user_id=str(user_id),
        alpaca_account_id=brokerage.alpaca_account_id,
        position_count=len(positions),
    )
    raise ConflictError(
        "Close all positions before closing your account",
        code="OPEN_POSITIONS",
        detail={"position_count": len(positions)},
    )


async def _block_if_pending_transfers(
    alpaca: AlpacaBrokerService, brokerage, user_id: uuid.UUID
) -> None:
    transfers = await alpaca.list_transfers(brokerage.alpaca_account_id)
    pending = [
        t for t in transfers if t.get("status") in PENDING_TRANSFER_STATUSES
    ]
    if not pending:
        return
    logger.warning(
        "close_brokerage_blocked_pending_transfers",
        user_id=str(user_id),
        alpaca_account_id=brokerage.alpaca_account_id,
        pending_count=len(pending),
    )
    raise ConflictError(
        "Wait for pending transfers to settle before closing your account",
        code="PENDING_TRANSFERS",
        detail={"pending_count": len(pending)},
    )


async def _block_if_non_zero_cash(
    alpaca: AlpacaBrokerService, brokerage, user_id: uuid.UUID
) -> None:
    # Alpaca rejects close with a generic 40310000 error if cash > 0, so
    # pre-flight the check to surface a structured NON_ZERO_BALANCE conflict
    # the client can branch on.
    trading_account = await alpaca.get_trading_account(brokerage.alpaca_account_id)
    cash_raw = trading_account.get("cash")
    if cash_raw is None:
        logger.error(
            "close_brokerage_cash_missing",
            user_id=str(user_id),
            alpaca_account_id=brokerage.alpaca_account_id,
        )
        raise AlpacaBrokerError(
            status_code=502,
            message="Alpaca trading-account response missing cash field",
        )
    try:
        cash_balance = Decimal(cash_raw)
    except InvalidOperation as exc:
        logger.error(
            "close_brokerage_cash_unparseable",
            user_id=str(user_id),
            alpaca_account_id=brokerage.alpaca_account_id,
            cash_raw=cash_raw,
        )
        raise AlpacaBrokerError(
            status_code=502,
            message="Alpaca cash value unparseable",
            detail={"cash_raw": str(cash_raw)},
        ) from exc
    if cash_balance > 0:
        logger.warning(
            "close_brokerage_blocked_non_zero_cash",
            user_id=str(user_id),
            alpaca_account_id=brokerage.alpaca_account_id,
            cash_balance=str(cash_balance),
        )
        raise ConflictError(
            "Withdraw your cash balance before closing your account",
            code="NON_ZERO_BALANCE",
            detail={"cash_balance": str(cash_balance)},
        )
