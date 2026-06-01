"""Integration tests for the recurring-investments execution engine."""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.asset import Asset
from app.models.order_event import OrderEvent
from app.models.recurring_investment_execution import (
    RecurringInvestmentExecution,
)
from app.repositories.recurring_investment import RecurringInvestmentRepository
from app.repositories.recurring_investment_execution import (
    STATUS_EXECUTED,
    STATUS_FAILED,
    STATUS_SKIPPED_INSUFFICIENT_FUNDS,
    RecurringInvestmentExecutionRepository,
)
from app.services.alpaca_broker import AlpacaBrokerError, AlpacaBrokerService
from app.services.recurring_engine import run_due_recurring_investments
from tests.integration.conftest import _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync, reason="Local Postgres not running"
)


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _make_alpaca(cash: str = "1000.00") -> AsyncMock:
    mock = AsyncMock(spec=AlpacaBrokerService)
    mock.get_trading_account.return_value = {
        "cash": cash,
        "buying_power": cash,
    }
    counter = {"n": 0}

    def _create_order(account_id, payload):
        counter["n"] += 1
        return {
            "id": f"alpaca-ord-{counter['n']}",
            "symbol": payload["symbol"],
            "side": "buy",
            "type": "market",
            "status": "accepted",
            "notional": payload.get("notional"),
            "submitted_at": "2026-06-01T13:00:00Z",
        }

    mock.create_order.side_effect = _create_order
    return mock


@pytest.fixture
async def engine_assets(db_session):
    stmt = pg_insert(Asset).values(
        [
            {"symbol": "VOO", "name": "Vanguard S&P 500 ETF", "exchange": "NYSE", "tradeable": True, "fractionable": True},
            {"symbol": "BRKA", "name": "Berkshire Hathaway A", "exchange": "NYSE", "tradeable": True, "fractionable": False},
        ]
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["symbol"],
        set_={
            "tradeable": True,
            "fractionable": stmt.excluded.fractionable,
            "name": stmt.excluded.name,
        },
    )
    await db_session.execute(stmt)
    await db_session.flush()


async def _make_plan(
    db,
    user_id,
    *,
    symbol="VOO",
    amount="50.00",
    frequency="weekly",
    next_run_date,
    end_condition_kind="never",
    end_on_date=None,
    end_after_count=None,
    status="active",
):
    plan = await RecurringInvestmentRepository.create(
        db,
        user_id=user_id,
        symbol=symbol,
        amount=Decimal(amount),
        frequency=frequency,
        start_date=next_run_date,
        end_condition_kind=end_condition_kind,
        end_on_date=end_on_date,
        end_after_count=end_after_count,
        next_run_date=next_run_date,
    )
    if status != "active":
        plan.status = status
        await db.flush()
    return plan


async def test_due_plan_executes_advances_and_logs(
    db_session, test_user, test_brokerage_account, engine_assets
):
    today = _today()
    plan = await _make_plan(db_session, test_user, next_run_date=today)
    alpaca = _make_alpaca(cash="1000.00")

    summary = await run_due_recurring_investments(
        db_session, alpaca=alpaca, as_of=today
    )

    assert summary["executed"] == 1
    # Order placed with notional + a non-digest client_order_id.
    assert alpaca.create_order.await_count == 1
    _, payload = alpaca.create_order.await_args.args
    assert payload["notional"] == "50.00"
    assert payload["type"] == "market"
    assert payload["client_order_id"].startswith("ri_")

    await db_session.refresh(plan)
    assert plan.executions_count == 1
    assert plan.next_run_date == today + timedelta(days=7)
    assert plan.status == "active"

    order = (
        await db_session.execute(
            select(OrderEvent).where(OrderEvent.user_id == test_user)
        )
    ).scalar_one()
    assert order.symbol == "VOO"
    assert order.notional == Decimal("50.00")

    execs = await RecurringInvestmentExecutionRepository.list_for_plan(
        db_session, plan.id
    )
    assert len(execs) == 1
    assert execs[0].status == STATUS_EXECUTED


async def test_insufficient_cash_skips_without_ordering(
    db_session, test_user, test_brokerage_account, engine_assets
):
    today = _today()
    plan = await _make_plan(db_session, test_user, next_run_date=today)
    alpaca = _make_alpaca(cash="10.00")  # < $50

    summary = await run_due_recurring_investments(
        db_session, alpaca=alpaca, as_of=today
    )

    assert summary["skipped"] == 1
    alpaca.create_order.assert_not_awaited()

    await db_session.refresh(plan)
    assert plan.executions_count == 0
    assert plan.next_run_date == today + timedelta(days=7)

    execs = await RecurringInvestmentExecutionRepository.list_for_plan(
        db_session, plan.id
    )
    assert len(execs) == 1
    assert execs[0].status == STATUS_SKIPPED_INSUFFICIENT_FUNDS


async def test_after_count_completes_on_final_execution(
    db_session, test_user, test_brokerage_account, engine_assets
):
    today = _today()
    plan = await _make_plan(
        db_session,
        test_user,
        next_run_date=today,
        end_condition_kind="after_count",
        end_after_count=1,
    )
    alpaca = _make_alpaca()

    summary = await run_due_recurring_investments(
        db_session, alpaca=alpaca, as_of=today
    )

    assert summary["executed"] == 1
    assert summary["completed"] == 1
    await db_session.refresh(plan)
    assert plan.status == "completed"
    assert plan.executions_count == 1

    # A second run on the same day no longer sees it (status != active).
    summary2 = await run_due_recurring_investments(
        db_session, alpaca=alpaca, as_of=today
    )
    assert summary2["due"] == 0


async def test_on_date_completes_when_next_run_would_exceed(
    db_session, test_user, test_brokerage_account, engine_assets
):
    today = _today()
    plan = await _make_plan(
        db_session,
        test_user,
        next_run_date=today,
        frequency="weekly",
        end_condition_kind="on_date",
        end_on_date=today + timedelta(days=3),  # next cadence (+7) exceeds it
    )
    alpaca = _make_alpaca()

    summary = await run_due_recurring_investments(
        db_session, alpaca=alpaca, as_of=today
    )

    assert summary["executed"] == 1
    assert summary["completed"] == 1
    await db_session.refresh(plan)
    assert plan.status == "completed"


async def test_already_logged_run_is_idempotent(
    db_session, test_user, test_brokerage_account, engine_assets
):
    today = _today()
    plan = await _make_plan(db_session, test_user, next_run_date=today)
    # Simulate a prior run that logged today's execution but didn't advance.
    await RecurringInvestmentExecutionRepository.create(
        db_session, plan=plan, run_date=today, status=STATUS_EXECUTED
    )
    alpaca = _make_alpaca()

    await run_due_recurring_investments(db_session, alpaca=alpaca, as_of=today)

    # No new order placed; schedule advanced to unstick.
    alpaca.create_order.assert_not_awaited()
    await db_session.refresh(plan)
    assert plan.next_run_date == today + timedelta(days=7)
    execs = await RecurringInvestmentExecutionRepository.list_for_plan(
        db_session, plan.id
    )
    assert len(execs) == 1


async def test_already_logged_skip_is_counted_as_skip_not_executed(
    db_session, test_user, test_brokerage_account, engine_assets
):
    today = _today()
    plan = await _make_plan(db_session, test_user, next_run_date=today)
    # A prior run logged today as a skip but (defensively) didn't advance.
    await RecurringInvestmentExecutionRepository.create(
        db_session,
        plan=plan,
        run_date=today,
        status=STATUS_SKIPPED_INSUFFICIENT_FUNDS,
    )
    alpaca = _make_alpaca()

    summary = await run_due_recurring_investments(
        db_session, alpaca=alpaca, as_of=today
    )

    # The prior outcome (skip) is reflected in the summary, not miscounted as
    # executed; no new order placed; schedule advanced.
    assert summary["skipped"] == 1
    assert summary["executed"] == 0
    alpaca.create_order.assert_not_awaited()
    await db_session.refresh(plan)
    assert plan.next_run_date == today + timedelta(days=7)


async def test_duplicate_client_order_id_is_recorded_as_executed(
    db_session, test_user, test_brokerage_account, engine_assets
):
    today = _today()
    plan = await _make_plan(db_session, test_user, next_run_date=today)
    alpaca = _make_alpaca()
    alpaca.create_order.side_effect = AlpacaBrokerError(
        422, "client_order_id must be unique."
    )

    summary = await run_due_recurring_investments(
        db_session, alpaca=alpaca, as_of=today
    )

    # Order already landed on a prior attempt — recorded once, counted, advanced.
    assert summary["executed"] == 1
    await db_session.refresh(plan)
    assert plan.executions_count == 1
    assert plan.next_run_date == today + timedelta(days=7)
    execs = await RecurringInvestmentExecutionRepository.list_for_plan(
        db_session, plan.id
    )
    assert execs[0].status == STATUS_EXECUTED
    assert execs[0].detail == "duplicate_client_order_id"


async def test_generic_422_is_recorded_as_failed(
    db_session, test_user, test_brokerage_account, engine_assets
):
    today = _today()
    plan = await _make_plan(db_session, test_user, next_run_date=today)
    alpaca = _make_alpaca()
    alpaca.create_order.side_effect = AlpacaBrokerError(
        422, "some other validation error"
    )

    summary = await run_due_recurring_investments(
        db_session, alpaca=alpaca, as_of=today
    )

    # Not a duplicate and not insufficient funds → the order didn't land, so
    # record failed (not executed) and advance.
    assert summary["failed"] == 1
    assert summary["executed"] == 0
    await db_session.refresh(plan)
    assert plan.executions_count == 0
    execs = await RecurringInvestmentExecutionRepository.list_for_plan(
        db_session, plan.id
    )
    assert execs[0].status == STATUS_FAILED


async def test_non_fractionable_symbol_pauses_plan(
    db_session, test_user, test_brokerage_account, engine_assets
):
    today = _today()
    plan = await _make_plan(
        db_session, test_user, symbol="BRKA", next_run_date=today
    )
    alpaca = _make_alpaca()

    summary = await run_due_recurring_investments(
        db_session, alpaca=alpaca, as_of=today
    )

    assert summary["failed"] == 1
    alpaca.create_order.assert_not_awaited()
    await db_session.refresh(plan)
    assert plan.status == "paused"
    execs = await RecurringInvestmentExecutionRepository.list_for_plan(
        db_session, plan.id
    )
    assert execs[0].status == STATUS_FAILED


async def test_account_not_found_pauses_plan(
    db_session, test_user, test_brokerage_account, engine_assets
):
    from app.exceptions import NotFoundError

    today = _today()
    plan = await _make_plan(db_session, test_user, next_run_date=today)
    alpaca = _make_alpaca()
    alpaca.get_trading_account.side_effect = NotFoundError("account gone")

    summary = await run_due_recurring_investments(
        db_session, alpaca=alpaca, as_of=today
    )

    assert summary["failed"] == 1
    assert summary["errored"] == 0  # classified as permanent, not a Sentry page
    alpaca.create_order.assert_not_awaited()
    await db_session.refresh(plan)
    assert plan.status == "paused"


async def test_not_yet_due_and_paused_plans_are_skipped(
    db_session, test_user, test_brokerage_account, engine_assets
):
    today = _today()
    await _make_plan(
        db_session, test_user, symbol="VOO", next_run_date=today + timedelta(days=5)
    )
    await _make_plan(
        db_session, test_user, symbol="SPY", next_run_date=today, status="paused"
    )
    alpaca = _make_alpaca()

    summary = await run_due_recurring_investments(
        db_session, alpaca=alpaca, as_of=today
    )

    assert summary["due"] == 0
    alpaca.create_order.assert_not_awaited()


async def test_transient_error_leaves_plan_due(
    db_session, test_user, test_brokerage_account, engine_assets
):
    today = _today()
    plan = await _make_plan(db_session, test_user, next_run_date=today)
    alpaca = _make_alpaca()
    alpaca.create_order.side_effect = AlpacaBrokerError(503, "service unavailable")

    summary = await run_due_recurring_investments(
        db_session, alpaca=alpaca, as_of=today
    )

    assert summary["transient"] == 1
    assert summary["executed"] == 0
    await db_session.refresh(plan)
    # Not advanced — stays due for the next run.
    assert plan.next_run_date == today
    assert plan.executions_count == 0
    execs = await RecurringInvestmentExecutionRepository.list_for_plan(
        db_session, plan.id
    )
    assert execs == []
