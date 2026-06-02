"""Data access for `recurring_investment_executions`. The `(plan, run_date)`
unique constraint makes a write idempotent across retries."""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recurring_investment import RecurringInvestment
from app.models.recurring_investment_execution import (
    RecurringInvestmentExecution,
)

STATUS_EXECUTED = "executed"
STATUS_SKIPPED_INSUFFICIENT_FUNDS = "skipped_insufficient_funds"
STATUS_FAILED = "failed"


class RecurringInvestmentExecutionRepository:

    @staticmethod
    async def get_status(
        db: AsyncSession, recurring_investment_id: uuid.UUID, run_date: date
    ) -> str | None:
        """The logged status for this (plan, run_date), or None if not yet
        processed. The engine uses this as an idempotency backstop and to keep
        the batch summary accurate on a defensive re-run."""
        result = await db.execute(
            select(RecurringInvestmentExecution.status).where(
                RecurringInvestmentExecution.recurring_investment_id
                == recurring_investment_id,
                RecurringInvestmentExecution.run_date == run_date,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create(
        db: AsyncSession,
        *,
        plan: RecurringInvestment,
        run_date: date,
        status: str,
        alpaca_order_id: str | None = None,
        detail: str | None = None,
    ) -> RecurringInvestmentExecution:
        row = RecurringInvestmentExecution(
            recurring_investment_id=plan.id,
            user_id=plan.user_id,
            run_date=run_date,
            status=status,
            symbol=plan.symbol,
            amount=plan.amount,
            alpaca_order_id=alpaca_order_id,
            detail=detail,
        )
        db.add(row)
        await db.flush()
        return row

    @staticmethod
    async def list_for_plan(
        db: AsyncSession, recurring_investment_id: uuid.UUID
    ) -> list[RecurringInvestmentExecution]:
        result = await db.execute(
            select(RecurringInvestmentExecution)
            .where(
                RecurringInvestmentExecution.recurring_investment_id
                == recurring_investment_id
            )
            .order_by(RecurringInvestmentExecution.run_date)
        )
        return list(result.scalars().all())
