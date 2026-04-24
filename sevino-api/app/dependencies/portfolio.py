from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.exceptions import ConflictError
from app.repositories.brokerage_account import STATUS_ACTIVE, BrokerageAccountRepository


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
    status = row.account_status if row else None
    if row is None or status != STATUS_ACTIVE:
        raise ConflictError(
            "Your brokerage account is not active yet.",
            code="ACCOUNT_NOT_ACTIVE",
            detail={"account_status": status},
        )
    return AlpacaAccountContext(
        user_id=uid,
        alpaca_account_id=row.alpaca_account_id,
        account_status=row.account_status,
    )
