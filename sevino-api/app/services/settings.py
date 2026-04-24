"""Settings service: read-only views over brokerage state for /v1/settings/*."""

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError
from app.repositories.brokerage_account import BrokerageAccountRepository
from app.schemas.settings import AccountValueResponse
from app.services.alpaca_broker import AlpacaBrokerError, AlpacaBrokerService

logger = structlog.get_logger(__name__)

_ACCOUNT_VALUE_FIELDS = ("equity", "cash", "buying_power", "portfolio_value")


class SettingsService:

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
