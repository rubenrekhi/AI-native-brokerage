"""Unit tests for the recurring-investment request/response schemas and the
iOS-mirroring wire format."""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas.recurring_investment import (
    EndConditionAfterCount,
    EndConditionNever,
    EndConditionOnDate,
    RecurringInvestmentCreate,
    RecurringInvestmentRead,
)


def _make_create(**overrides):
    base = {
        "block_id": "blk_ri",
        "ticker": "VOO",
        "amount": "50.00",
        "frequency": "weekly",
        "start_date": "2026-06-15T00:00:00Z",
        "end_condition": {"kind": "never"},
    }
    base.update(overrides)
    return RecurringInvestmentCreate.model_validate(base)


def test_create_parses_amount_string_to_decimal():
    model = _make_create()
    assert model.amount == Decimal("50.00")
    assert isinstance(model.end_condition, EndConditionNever)


def test_create_defaults_end_condition_to_never():
    model = RecurringInvestmentCreate.model_validate(
        {
            "ticker": "VOO",
            "amount": "50.00",
            "frequency": "monthly",
            "start_date": "2026-06-15T00:00:00Z",
        }
    )
    assert isinstance(model.end_condition, EndConditionNever)


def test_create_parses_on_date_end_condition():
    model = _make_create(
        end_condition={"kind": "on_date", "date": "2026-12-01T00:00:00Z"}
    )
    assert isinstance(model.end_condition, EndConditionOnDate)
    assert model.end_condition.date == date(2026, 12, 1)


def test_on_date_coerces_non_midnight_time_to_date():
    # A non-midnight time must not survive the round-trip: it's stored as a
    # Date column, so the end-date is calendar-day granular.
    model = _make_create(
        end_condition={"kind": "on_date", "date": "2026-12-01T15:30:00Z"}
    )
    assert model.end_condition.date == date(2026, 12, 1)
    dumped = model.model_dump(mode="json")
    assert dumped["end_condition"] == {
        "kind": "on_date",
        "date": "2026-12-01T00:00:00Z",
    }


def test_create_parses_after_count_end_condition():
    model = _make_create(end_condition={"kind": "after_count", "count": 24})
    assert isinstance(model.end_condition, EndConditionAfterCount)
    assert model.end_condition.count == 24


def test_create_accepts_daily_frequency():
    model = _make_create(frequency="daily")
    assert model.frequency == "daily"


def test_create_rejects_amount_below_one_dollar():
    with pytest.raises(ValidationError):
        _make_create(amount="0.50")


def test_create_rejects_unknown_frequency():
    with pytest.raises(ValidationError):
        _make_create(frequency="yearly")


def test_create_rejects_after_count_below_one():
    with pytest.raises(ValidationError):
        _make_create(end_condition={"kind": "after_count", "count": 0})


def test_create_rejects_end_date_not_after_start():
    with pytest.raises(ValidationError):
        _make_create(
            start_date="2026-06-15T00:00:00Z",
            end_condition={"kind": "on_date", "date": "2026-06-15T00:00:00Z"},
        )


def _orm_row(**overrides):
    base = dict(
        id=uuid.uuid4(),
        symbol="VOO",
        amount=Decimal("50.00"),
        frequency="weekly",
        start_date=date(2026, 6, 15),
        end_condition_kind="never",
        end_on_date=None,
        end_after_count=None,
        status="active",
        next_run_date=date(2026, 6, 15),
        executions_count=0,
        created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_read_coerces_orm_and_serializes_wire_shape():
    payload = RecurringInvestmentRead.model_validate(_orm_row()).model_dump(
        mode="json"
    )
    assert payload["ticker"] == "VOO"
    # Money is a decimal string, not a number.
    assert payload["amount"] == "50.00"
    assert payload["start_date"] == "2026-06-15"
    assert payload["next_run_date"] == "2026-06-15"
    assert payload["end_condition"] == {"kind": "never"}
    assert payload["status"] == "active"


def test_read_serializes_on_date_with_trailing_z():
    row = _orm_row(end_condition_kind="on_date", end_on_date=date(2026, 12, 1))
    payload = RecurringInvestmentRead.model_validate(row).model_dump(mode="json")
    assert payload["end_condition"] == {
        "kind": "on_date",
        "date": "2026-12-01T00:00:00Z",
    }


def test_read_serializes_after_count():
    row = _orm_row(end_condition_kind="after_count", end_after_count=12)
    payload = RecurringInvestmentRead.model_validate(row).model_dump(mode="json")
    assert payload["end_condition"] == {"kind": "after_count", "count": 12}
