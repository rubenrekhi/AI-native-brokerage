from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.exceptions import IncompleteOnboardingError
from app.repositories.brokerage_account import BrokerageAccountRepository


@dataclass(frozen=True)
class AlpacaAccountContext:
    user_id: uuid.UUID
    alpaca_account_id: str
    account_status: str


async def get_alpaca_account_context(
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AlpacaAccountContext:
    uid = uuid.UUID(user_id)
    row = await BrokerageAccountRepository.get_by_user_id(db, uid)
    if row is None:
        raise IncompleteOnboardingError("Brokerage account has not been created yet")
    return AlpacaAccountContext(
        user_id=uid,
        alpaca_account_id=row.alpaca_account_id,
        account_status=row.account_status,
    )
