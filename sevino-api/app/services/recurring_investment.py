"""Recurring-investments orchestrator: create, list, pause, resume, and cancel
scheduled buys.

Account / symbol / fractionability checks reuse `validate_trade_prerequisites`
so a recurring plan is gated by the same rules as a one-off trade. Recurring
buys are placed as notional (dollar-amount) orders, which Alpaca only allows on
fractionable assets.
"""

import calendar
import uuid
from datetime import date, datetime, timedelta, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, NotFoundError
from app.models.recurring_investment import RecurringInvestment
from app.repositories.recurring_investment import (
    STATUS_ACTIVE,
    STATUS_CANCELLED,
    STATUS_PAUSED,
    TERMINAL_STATUSES,
    RecurringInvestmentRepository,
)
from app.schemas.recurring_investment import (
    EndConditionAfterCount,
    EndConditionOnDate,
    RecurringEndCondition,
    RecurringInvestmentCreate,
)
from app.services.alpaca_broker import AlpacaBrokerService
from app.services.trading import validate_trade_prerequisites

logger = structlog.get_logger(__name__)

__all__ = ["RecurringInvestmentService", "compute_next_run_date"]


def compute_next_run_date(current: date, frequency: str) -> date:
    """Advance one cadence step from `current`.

    `daily` skips weekends (Sat/Sun) so consecutive non-trading days don't
    stack a queued order onto the next open. Weekly/biweekly preserve the
    weekday; monthly preserves the day-of-month, clamping to the last day of
    short months. Market-holiday handling lives in the execution engine, where
    Alpaca's calendar is available.
    """
    if frequency == "daily":
        nxt = current + timedelta(days=1)
        while nxt.weekday() >= 5:
            nxt += timedelta(days=1)
        return nxt
    if frequency == "weekly":
        return current + timedelta(days=7)
    if frequency == "biweekly":
        return current + timedelta(days=14)
    if frequency == "monthly":
        return _add_one_month(current)
    raise ValueError(f"Unsupported frequency: {frequency}")


def _add_one_month(d: date) -> date:
    # d.month % 12 + 1 wraps December → January (12 % 12 + 1 = 1); d.month // 12
    # bumps the year only on that wrap.
    year = d.year + d.month // 12
    month = d.month % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))


def _end_condition_columns(
    end_condition: RecurringEndCondition,
) -> tuple[str, date | None, int | None]:
    if isinstance(end_condition, EndConditionOnDate):
        return "on_date", end_condition.date, None
    if isinstance(end_condition, EndConditionAfterCount):
        return "after_count", None, end_condition.count
    return "never", None, None


class RecurringInvestmentService:

    @staticmethod
    async def create(
        db: AsyncSession,
        *,
        alpaca: AlpacaBrokerService,
        user_id: uuid.UUID,
        data: RecurringInvestmentCreate,
    ) -> RecurringInvestment:
        start_date = data.start_date.date()
        today = datetime.now(timezone.utc).date()
        if start_date < today:
            raise ConflictError(
                "Start date can't be in the past.",
                code="RECURRING_START_DATE_IN_PAST",
                detail={"start_date": start_date.isoformat()},
            )

        _brokerage, asset = await validate_trade_prerequisites(
            db,
            alpaca=alpaca,
            user_id=user_id,
            symbol=data.ticker,
            side="buy",
            notional=str(data.amount),
        )

        kind, end_on_date, end_after_count = _end_condition_columns(
            data.end_condition
        )
        item = await RecurringInvestmentRepository.create(
            db,
            user_id=user_id,
            symbol=asset.symbol,
            amount=data.amount,
            frequency=data.frequency,
            start_date=start_date,
            end_condition_kind=kind,
            end_on_date=end_on_date,
            end_after_count=end_after_count,
            next_run_date=start_date,
        )
        logger.info(
            "recurring_investment_created",
            user_id=str(user_id),
            recurring_investment_id=str(item.id),
            symbol=item.symbol,
            amount=str(item.amount),
            frequency=item.frequency,
        )
        return item

    @staticmethod
    async def list_for_user(
        db: AsyncSession, *, user_id: uuid.UUID
    ) -> list[RecurringInvestment]:
        return await RecurringInvestmentRepository.list_live_for_user(
            db, user_id
        )

    @staticmethod
    async def pause(
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        recurring_investment_id: uuid.UUID,
    ) -> RecurringInvestment:
        item = await _get_owned(db, user_id, recurring_investment_id)
        if item.status in TERMINAL_STATUSES:
            raise ConflictError(
                "This recurring investment can no longer be paused.",
                code="RECURRING_NOT_MODIFIABLE",
                detail={"status": item.status},
            )
        if item.status == STATUS_PAUSED:
            return item
        await RecurringInvestmentRepository.update(
            db, item, status=STATUS_PAUSED
        )
        logger.info(
            "recurring_investment_paused",
            user_id=str(user_id),
            recurring_investment_id=str(item.id),
        )
        return item

    @staticmethod
    async def resume(
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        recurring_investment_id: uuid.UUID,
    ) -> RecurringInvestment:
        item = await _get_owned(db, user_id, recurring_investment_id)
        if item.status != STATUS_PAUSED:
            raise ConflictError(
                "Only a paused recurring investment can be resumed.",
                code="RECURRING_NOT_PAUSED",
                detail={"status": item.status},
            )
        # Skip cadence dates strictly in the past so a plan paused across
        # several dates doesn't fire make-up buys; today stays, so a same-day
        # resume can still run.
        today = datetime.now(timezone.utc).date()
        next_run = item.next_run_date
        while next_run < today:
            next_run = compute_next_run_date(next_run, item.frequency)
        await RecurringInvestmentRepository.update(
            db, item, status=STATUS_ACTIVE, next_run_date=next_run
        )
        logger.info(
            "recurring_investment_resumed",
            user_id=str(user_id),
            recurring_investment_id=str(item.id),
            next_run_date=next_run.isoformat(),
        )
        return item

    @staticmethod
    async def cancel(
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        recurring_investment_id: uuid.UUID,
    ) -> RecurringInvestment:
        item = await _get_owned(db, user_id, recurring_investment_id)
        if item.status == STATUS_CANCELLED:
            return item
        await RecurringInvestmentRepository.update(
            db, item, status=STATUS_CANCELLED
        )
        logger.info(
            "recurring_investment_cancelled",
            user_id=str(user_id),
            recurring_investment_id=str(item.id),
        )
        return item


async def _get_owned(
    db: AsyncSession, user_id: uuid.UUID, recurring_investment_id: uuid.UUID
) -> RecurringInvestment:
    item = await RecurringInvestmentRepository.get_by_id_for_user(
        db, recurring_investment_id, user_id
    )
    if item is None:
        raise NotFoundError("Recurring investment not found")
    return item
