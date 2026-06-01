"""Data access for `recurring_investments` — per-user scheduled-buy plans.

`list_live_for_user` returns only active + paused plans (the ones a user
manages); cancelled and completed plans are terminal history and stay out of
the management list.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recurring_investment import RecurringInvestment

STATUS_ACTIVE = "active"
STATUS_PAUSED = "paused"
STATUS_COMPLETED = "completed"
STATUS_CANCELLED = "cancelled"

LIVE_STATUSES = (STATUS_ACTIVE, STATUS_PAUSED)
TERMINAL_STATUSES = (STATUS_COMPLETED, STATUS_CANCELLED)


class RecurringInvestmentRepository:

    @staticmethod
    async def create(
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        symbol: str,
        amount: Decimal,
        frequency: str,
        start_date: date,
        end_condition_kind: str,
        end_on_date: date | None,
        end_after_count: int | None,
        next_run_date: date,
    ) -> RecurringInvestment:
        item = RecurringInvestment(
            user_id=user_id,
            symbol=symbol,
            amount=amount,
            frequency=frequency,
            start_date=start_date,
            end_condition_kind=end_condition_kind,
            end_on_date=end_on_date,
            end_after_count=end_after_count,
            status=STATUS_ACTIVE,
            next_run_date=next_run_date,
        )
        db.add(item)
        await db.flush()
        return item

    @staticmethod
    async def list_live_for_user(
        db: AsyncSession, user_id: uuid.UUID
    ) -> list[RecurringInvestment]:
        result = await db.execute(
            select(RecurringInvestment)
            .where(
                RecurringInvestment.user_id == user_id,
                RecurringInvestment.status.in_(LIVE_STATUSES),
            )
            .order_by(RecurringInvestment.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_due(
        db: AsyncSession, as_of: date
    ) -> list[RecurringInvestment]:
        """Active plans whose next run is due (today or earlier), ordered by id
        for a stable sweep."""
        result = await db.execute(
            select(RecurringInvestment)
            .where(
                RecurringInvestment.status == STATUS_ACTIVE,
                RecurringInvestment.next_run_date <= as_of,
            )
            .order_by(RecurringInvestment.id)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_id_for_user(
        db: AsyncSession, item_id: uuid.UUID, user_id: uuid.UUID
    ) -> RecurringInvestment | None:
        """Ownership-guarded lookup — returns None for another user's row so
        callers don't need a separate authorization check."""
        result = await db.execute(
            select(RecurringInvestment).where(
                RecurringInvestment.id == item_id,
                RecurringInvestment.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def update(
        db: AsyncSession, item: RecurringInvestment, **fields: Any
    ) -> RecurringInvestment:
        for key, value in fields.items():
            setattr(item, key, value)
        await db.flush()
        # `updated_at` is server-side (onupdate=now()), so the flush expires
        # it; refresh reloads it in the async context before serialization
        # would otherwise trigger a lazy (sync) reload.
        await db.refresh(item)
        return item
