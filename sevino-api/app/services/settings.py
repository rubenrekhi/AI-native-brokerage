"""Settings service: user preferences CRUD + read-only views over brokerage state."""

import uuid

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

logger = structlog.get_logger(__name__)

_ACCOUNT_VALUE_FIELDS = ("equity", "cash", "buying_power", "portfolio_value")


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
