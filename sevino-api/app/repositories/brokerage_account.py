import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.brokerage_account import BrokerageAccount

STATUS_ACTIVE = "ACTIVE"
STATUS_ACCOUNT_CLOSED = "ACCOUNT_CLOSED"


class BrokerageAccountRepository:

    @staticmethod
    async def get_by_user_id(
        db: AsyncSession, user_id: uuid.UUID
    ) -> BrokerageAccount | None:
        result = await db.execute(
            select(BrokerageAccount).where(BrokerageAccount.user_id == user_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_alpaca_account_id(
        db: AsyncSession, alpaca_account_id: str
    ) -> BrokerageAccount | None:
        result = await db.execute(
            select(BrokerageAccount).where(
                BrokerageAccount.alpaca_account_id == alpaca_account_id
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create(
        db: AsyncSession,
        user_id: uuid.UUID,
        alpaca_account_id: str,
        account_status: str,
        **fields,
    ) -> BrokerageAccount:
        account = BrokerageAccount(
            user_id=user_id,
            alpaca_account_id=alpaca_account_id,
            account_status=account_status,
            kyc_submitted_at=datetime.now(timezone.utc),
            **fields,
        )
        db.add(account)
        await db.flush()
        return account

    @staticmethod
    async def update_status(
        db: AsyncSession,
        account_id: uuid.UUID,
        status: str,
        **fields,
    ) -> BrokerageAccount:
        result = await db.execute(
            select(BrokerageAccount).where(BrokerageAccount.id == account_id)
        )
        account = result.scalar_one()
        account.account_status = status
        for key, value in fields.items():
            if hasattr(account, key):
                setattr(account, key, value)
        await db.flush()
        return account

    @staticmethod
    async def get_pending(db: AsyncSession) -> list[BrokerageAccount]:
        result = await db.execute(
            select(BrokerageAccount).where(
                BrokerageAccount.account_status.in_(("SUBMITTED", "ACTION_REQUIRED"))
            )
        )
        return list(result.scalars().all())
