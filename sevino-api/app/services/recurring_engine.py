"""Recurring-investments execution engine (PRD 11.6).

Processes plans whose `next_run_date` is due: re-validates, checks settled
cash, places a notional market-day buy, logs the run, and advances the
schedule. Insufficient cash is a skip (no order, no bank pull); the next
cadence date is the next attempt. Idempotency comes from three layers — the
`(plan, run_date)` execution-log unique constraint, a deterministic
`client_order_id`, and advancing `next_run_date` — so a retried or crashed run
can't double-buy.

Each plan runs inside its own SAVEPOINT, so one plan's failure rolls back only
that plan; the caller owns the outer commit. Plans are processed sequentially;
transient upstream errors (429 / 5xx) bubble up so the cron can re-run soon
rather than defer the buy a full day.
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import sentry_sdk
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, NotFoundError
from app.models.recurring_investment import RecurringInvestment
from app.repositories.order_event import OrderEventRepository
from app.repositories.recurring_investment import (
    STATUS_ACTIVE,
    STATUS_COMPLETED,
    STATUS_PAUSED,
    RecurringInvestmentRepository,
)
from app.repositories.recurring_investment_execution import (
    STATUS_EXECUTED,
    STATUS_FAILED,
    STATUS_SKIPPED_INSUFFICIENT_FUNDS,
    RecurringInvestmentExecutionRepository,
)
from app.services.alpaca_broker import (
    AlpacaBrokerError,
    AlpacaBrokerService,
    AlpacaBrokerUnavailableError,
)
from app.services.recurring_investment import compute_next_run_date
from app.services.trading import validate_trade_prerequisites

logger = structlog.get_logger(__name__)

__all__ = ["run_due_recurring_investments", "execute_recurring_investment"]


def _client_order_id(plan: RecurringInvestment, run_date: date) -> str:
    # Deterministic per (plan, run date) so a retried run re-sends the same id
    # and Alpaca rejects the duplicate — no double-buy. The `ri_` prefix avoids
    # `recurring_`/`dca_`/`scheduled_`/`auto_`, which would light up the digest.
    return f"ri_{plan.id.hex}_{run_date:%Y%m%d}"


def _is_transient(exc: AlpacaBrokerError) -> bool:
    return exc.status_code == 429 or exc.status_code >= 500


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _advance_or_complete(plan: RecurringInvestment) -> None:
    """Advance `next_run_date` one cadence step, or mark the plan completed if
    its end condition is now satisfied. `after_count` counts only successful
    executions (the caller bumps `executions_count` before calling this on a
    successful buy; a skip leaves it unchanged)."""
    if (
        plan.end_condition_kind == "after_count"
        and plan.end_after_count is not None
        and plan.executions_count >= plan.end_after_count
    ):
        plan.status = STATUS_COMPLETED
        return
    next_run = compute_next_run_date(plan.next_run_date, plan.frequency)
    if (
        plan.end_condition_kind == "on_date"
        and plan.end_on_date is not None
        and next_run > plan.end_on_date
    ):
        plan.status = STATUS_COMPLETED
        return
    plan.next_run_date = next_run


async def execute_recurring_investment(
    session: AsyncSession,
    *,
    alpaca: AlpacaBrokerService,
    plan: RecurringInvestment,
    as_of: date,
) -> str:
    run_date = plan.next_run_date

    prior_status = await RecurringInvestmentExecutionRepository.get_status(
        session, plan.id, run_date
    )
    if prior_status is not None:
        # Idempotency backstop: never re-place or re-count a (plan, run_date)
        # that's already logged. Normal flow advances next_run_date so a
        # processed plan isn't re-selected; this keeps a defensive re-run a
        # clean no-op. Return the prior outcome so the batch summary stays
        # accurate — a prior skip/failure must not be counted as executed.
        _advance_or_complete(plan)
        await session.flush()
        return prior_status

    try:
        brokerage, asset = await validate_trade_prerequisites(
            session,
            alpaca=alpaca,
            user_id=plan.user_id,
            symbol=plan.symbol,
            side="buy",
            notional=str(plan.amount),
        )
    except ConflictError as exc:
        return await _pause_failed(
            session, plan, run_date, reason=exc.code or "validation_failed"
        )

    try:
        account = await alpaca.get_trading_account(brokerage.alpaca_account_id)
    except NotFoundError:
        # Account closed/removed at Alpaca out of band — the plan can't run.
        return await _pause_failed(
            session, plan, run_date, reason="account_not_found"
        )
    except AlpacaBrokerError as exc:
        if _is_transient(exc):
            raise
        return await _log_failed(
            session, plan, run_date, detail=f"account_fetch: {exc.message}"
        )

    cash = _parse_decimal(account.get("cash"))
    if cash is None or cash < plan.amount:
        await RecurringInvestmentExecutionRepository.create(
            session,
            plan=plan,
            run_date=run_date,
            status=STATUS_SKIPPED_INSUFFICIENT_FUNDS,
            detail=f"cash={cash}",
        )
        _advance_or_complete(plan)
        await session.flush()
        logger.info(
            "recurring_skipped_insufficient_funds",
            recurring_investment_id=str(plan.id),
            cash=str(cash),
            amount=str(plan.amount),
        )
        return STATUS_SKIPPED_INSUFFICIENT_FUNDS

    payload = {
        "symbol": asset.symbol,
        "side": "buy",
        "type": "market",
        "time_in_force": "day",
        "notional": str(plan.amount),
        "client_order_id": _client_order_id(plan, run_date),
    }
    try:
        alpaca_order = await alpaca.create_order(
            brokerage.alpaca_account_id, payload
        )
    except NotFoundError:
        # Same permanent condition as the account-fetch path — pause rather
        # than advance, so the plan doesn't fail on every future cadence date.
        return await _pause_failed(
            session, plan, run_date, reason="account_not_found"
        )
    except AlpacaBrokerError as exc:
        if _is_transient(exc):
            raise
        return await _handle_order_business_error(session, plan, run_date, exc)

    # Explicit None check, not `or`: Alpaca echoing notional "0" is falsy and
    # would wrongly fall back to plan.amount.
    order_notional = _parse_decimal(alpaca_order.get("notional"))
    if order_notional is None:
        order_notional = plan.amount
    await OrderEventRepository.create(
        session,
        user_id=plan.user_id,
        alpaca_order_id=alpaca_order["id"],
        symbol=alpaca_order.get("symbol", asset.symbol),
        side="buy",
        order_type=alpaca_order.get("type", "market"),
        status=alpaca_order.get("status", "accepted"),
        notional=order_notional,
        submitted_at=_parse_datetime(alpaca_order.get("submitted_at")),
    )
    await RecurringInvestmentExecutionRepository.create(
        session,
        plan=plan,
        run_date=run_date,
        status=STATUS_EXECUTED,
        alpaca_order_id=alpaca_order["id"],
    )
    plan.executions_count += 1
    plan.last_run_at = datetime.now(timezone.utc)
    _advance_or_complete(plan)
    await session.flush()
    logger.info(
        "recurring_executed",
        recurring_investment_id=str(plan.id),
        alpaca_order_id=alpaca_order["id"],
        symbol=asset.symbol,
        amount=str(plan.amount),
        status=plan.status,
    )
    return STATUS_EXECUTED


async def _pause_failed(
    session: AsyncSession,
    plan: RecurringInvestment,
    run_date: date,
    *,
    reason: str,
) -> str:
    await RecurringInvestmentExecutionRepository.create(
        session, plan=plan, run_date=run_date, status=STATUS_FAILED, detail=reason
    )
    plan.status = STATUS_PAUSED
    await session.flush()
    logger.warning(
        "recurring_paused_after_failure",
        recurring_investment_id=str(plan.id),
        reason=reason,
    )
    return STATUS_FAILED


async def _log_failed(
    session: AsyncSession,
    plan: RecurringInvestment,
    run_date: date,
    *,
    detail: str,
) -> str:
    # Non-transient error we can't classify. Record it and advance so the plan
    # doesn't retry the same broken date forever.
    await RecurringInvestmentExecutionRepository.create(
        session, plan=plan, run_date=run_date, status=STATUS_FAILED, detail=detail
    )
    _advance_or_complete(plan)
    await session.flush()
    logger.error(
        "recurring_execution_failed",
        recurring_investment_id=str(plan.id),
        detail=detail,
    )
    return STATUS_FAILED


async def _handle_order_business_error(
    session: AsyncSession,
    plan: RecurringInvestment,
    run_date: date,
    exc: AlpacaBrokerError,
) -> str:
    message = (exc.message or "").lower()
    if exc.status_code == 422 and "client_order_id" in message:
        # The order landed on a prior attempt that didn't persist locally. The
        # deterministic client_order_id means Alpaca holds exactly one order
        # for this (plan, date), so record it once and advance.
        await RecurringInvestmentExecutionRepository.create(
            session,
            plan=plan,
            run_date=run_date,
            status=STATUS_EXECUTED,
            detail="duplicate_client_order_id",
        )
        plan.executions_count += 1
        plan.last_run_at = datetime.now(timezone.utc)
        _advance_or_complete(plan)
        await session.flush()
        logger.info(
            "recurring_execution_idempotent_replay",
            recurring_investment_id=str(plan.id),
        )
        return STATUS_EXECUTED
    if exc.status_code == 403 and (
        "insufficient" in message or "buying power" in message
    ):
        await RecurringInvestmentExecutionRepository.create(
            session,
            plan=plan,
            run_date=run_date,
            status=STATUS_SKIPPED_INSUFFICIENT_FUNDS,
            detail=exc.message,
        )
        # Local cash gate passed but Alpaca rejected for funds — our cash view
        # drifted (stale read or balance moved). Worth a signal, not an error.
        logger.warning(
            "recurring_order_rejected_after_cash_gate_passed",
            recurring_investment_id=str(plan.id),
            detail=exc.message,
        )
        _advance_or_complete(plan)
        await session.flush()
        return STATUS_SKIPPED_INSUFFICIENT_FUNDS
    return await _log_failed(
        session, plan, run_date, detail=f"order_rejected: {exc.message}"
    )


async def run_due_recurring_investments(
    session: AsyncSession,
    *,
    alpaca: AlpacaBrokerService,
    as_of: date,
) -> dict[str, int]:
    plans = await RecurringInvestmentRepository.list_due(session, as_of)
    summary = {
        "due": len(plans),
        "executed": 0,
        "skipped": 0,
        "failed": 0,
        "completed": 0,
        "transient": 0,
        "errored": 0,
    }
    for plan in plans:
        # Capture identifiers before the savepoint: a rollback can expire ORM
        # attributes, and reading them in the except blocks would trigger a
        # sync lazy-load (MissingGreenlet) in this async context.
        plan_id = str(plan.id)
        plan_user_id = str(plan.user_id)
        try:
            async with session.begin_nested():
                outcome = await execute_recurring_investment(
                    session, alpaca=alpaca, plan=plan, as_of=as_of
                )
            if outcome == STATUS_EXECUTED:
                summary["executed"] += 1
            elif outcome == STATUS_SKIPPED_INSUFFICIENT_FUNDS:
                summary["skipped"] += 1
            elif outcome == STATUS_FAILED:
                summary["failed"] += 1
            if plan.status == STATUS_COMPLETED:
                summary["completed"] += 1
        except (AlpacaBrokerError, AlpacaBrokerUnavailableError) as exc:
            if isinstance(exc, AlpacaBrokerError) and not _is_transient(exc):
                # A non-transient broker error escaped the inner handlers —
                # count as errored (don't trigger a retry) and surface it.
                summary["errored"] += 1
                logger.error(
                    "recurring_plan_broker_error",
                    recurring_investment_id=plan_id,
                    status_code=exc.status_code,
                    error=str(exc),
                )
                with sentry_sdk.new_scope() as scope:
                    scope.set_tag("task", "process_due_recurring")
                    scope.set_tag("recurring_investment_id", plan_id)
                    scope.set_tag("user_id", plan_user_id)
                    sentry_sdk.capture_exception(exc)
            else:
                summary["transient"] += 1
                logger.warning(
                    "recurring_plan_transient",
                    recurring_investment_id=plan_id,
                    status_code=getattr(exc, "status_code", None),
                    error=str(exc),
                )
        except Exception as exc:
            summary["errored"] += 1
            logger.error(
                "recurring_plan_unexpected_error",
                recurring_investment_id=plan_id,
                error=str(exc),
                exc_info=True,
            )
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("task", "process_due_recurring")
                scope.set_tag("recurring_investment_id", plan_id)
                scope.set_tag("user_id", plan_user_id)
                sentry_sdk.capture_exception(exc)
    logger.info(
        "recurring_run_complete", as_of=as_of.isoformat(), **summary
    )
    return summary
