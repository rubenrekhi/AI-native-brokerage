"""Unit tests for the recurring-engine pure helpers (no DB / no network)."""

import uuid
from datetime import date

from app.models.recurring_investment import RecurringInvestment
from app.services.recurring_engine import _advance_or_complete, _client_order_id


def _plan(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        next_run_date=date(2026, 6, 15),
        frequency="weekly",
        end_condition_kind="never",
        end_on_date=None,
        end_after_count=None,
        executions_count=0,
        status="active",
    )
    defaults.update(overrides)
    return RecurringInvestment(**defaults)


def test_client_order_id_is_deterministic_and_not_a_digest_prefix():
    plan = _plan()
    coid = _client_order_id(plan, date(2026, 6, 15))
    assert coid == f"ri_{plan.id.hex}_20260615"
    # Must not match the digest's recurring-detection prefixes.
    assert not coid.startswith(("recurring_", "dca_", "scheduled_", "auto_"))
    # Stable across calls.
    assert _client_order_id(plan, date(2026, 6, 15)) == coid


def test_advance_never_moves_to_next_cadence():
    plan = _plan(frequency="weekly")
    _advance_or_complete(plan)
    assert plan.next_run_date == date(2026, 6, 22)
    assert plan.status == "active"


def test_advance_after_count_completes_when_reached():
    plan = _plan(
        end_condition_kind="after_count", end_after_count=3, executions_count=3
    )
    _advance_or_complete(plan)
    assert plan.status == "completed"


def test_advance_after_count_continues_below_threshold():
    plan = _plan(
        end_condition_kind="after_count", end_after_count=3, executions_count=1
    )
    _advance_or_complete(plan)
    assert plan.status == "active"
    assert plan.next_run_date == date(2026, 6, 22)


def test_advance_on_date_completes_when_next_exceeds():
    plan = _plan(end_condition_kind="on_date", end_on_date=date(2026, 6, 18))
    _advance_or_complete(plan)  # next cadence 2026-06-22 > 2026-06-18
    assert plan.status == "completed"


def test_advance_on_date_continues_when_within_window():
    plan = _plan(end_condition_kind="on_date", end_on_date=date(2026, 7, 1))
    _advance_or_complete(plan)  # next cadence 2026-06-22 <= 2026-07-01
    assert plan.status == "active"
    assert plan.next_run_date == date(2026, 6, 22)
