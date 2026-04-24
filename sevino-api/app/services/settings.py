"""Settings service: user preferences CRUD + read-only views over brokerage state."""

import uuid

import sentry_sdk
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError
from app.models.user_settings import UserSettings
from app.repositories.ach_relationship import AchRelationshipRepository
from app.repositories.brokerage_account import BrokerageAccountRepository
from app.repositories.financial_profile import FinancialProfileRepository
from app.repositories.user_profile import UserProfileRepository
from app.repositories.user_settings import UserSettingsRepository
from app.schemas.onboarding import FinancialProfileData, ProfileData
from app.schemas.settings import (
    AccountValueResponse,
    BrokerageAccountSummary,
    LinkedAccountSummary,
    SettingsProfileResponse,
    UserSettingsPatchRequest,
)
from app.services.alpaca_broker import AlpacaBrokerError, AlpacaBrokerService
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
_BROKERAGE_TERMINAL_STATUSES = frozenset({"ACCOUNT_CLOSED", "REJECTED"})


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
