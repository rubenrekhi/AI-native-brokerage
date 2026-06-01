"""Request/response schemas for the recurring-investments API.

Mirror the iOS chat-card contract (``Models/Chat/Block.swift`` /
``RecurringInvestmentRequest.swift``): money as decimal strings, ISO-8601 dates
with a trailing ``Z``, ``frequency`` as snake_case literals, ``end_condition``
as a ``kind``-tagged union. Keep them in sync with the Swift side.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Union

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_serializer,
    model_validator,
)

from app.schemas._types import MoneyStr

RecurringFrequency = Literal["daily", "weekly", "biweekly", "monthly"]
RecurringStatus = Literal["active", "paused", "completed", "cancelled"]

MIN_RECURRING_AMOUNT = Decimal("1")


def _to_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if "T" in text or " " in text:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    return date.fromisoformat(text)


# Calendar-day granular: iOS sends it as a midnight-UTC datetime string, so
# accept that on input and echo the same shape back out.
OnDateValue = Annotated[date, BeforeValidator(_to_date)]


class EndConditionNever(BaseModel):
    kind: Literal["never"] = "never"


class EndConditionOnDate(BaseModel):
    kind: Literal["on_date"] = "on_date"
    date: OnDateValue

    @field_serializer("date")
    def _serialize_date(self, value: date) -> str:
        return f"{value.isoformat()}T00:00:00Z"


class EndConditionAfterCount(BaseModel):
    kind: Literal["after_count"] = "after_count"
    count: int = Field(..., ge=1)


RecurringEndCondition = Annotated[
    Union[EndConditionNever, EndConditionOnDate, EndConditionAfterCount],
    Field(discriminator="kind"),
]


class RecurringInvestmentCreate(BaseModel):
    block_id: str | None = None
    ticker: str = Field(..., min_length=1, max_length=10)
    amount: MoneyStr
    frequency: RecurringFrequency
    start_date: datetime
    end_condition: RecurringEndCondition = Field(default_factory=EndConditionNever)

    @model_validator(mode="after")
    def _validate(self) -> "RecurringInvestmentCreate":
        if self.amount < MIN_RECURRING_AMOUNT:
            raise ValueError("amount must be at least $1.00")
        if (
            isinstance(self.end_condition, EndConditionOnDate)
            and self.end_condition.date <= self.start_date.date()
        ):
            raise ValueError("end date must be after the start date")
        return self


class RecurringInvestmentUpdate(BaseModel):
    action: Literal["pause", "resume"]


def _end_condition_payload(model: Any) -> dict[str, Any]:
    kind = model.end_condition_kind
    if kind == "on_date":
        return {"kind": "on_date", "date": model.end_on_date}
    if kind == "after_count":
        return {"kind": "after_count", "count": model.end_after_count}
    return {"kind": "never"}


class RecurringInvestmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticker: str
    amount: MoneyStr
    frequency: RecurringFrequency
    start_date: date
    end_condition: RecurringEndCondition
    status: RecurringStatus
    next_run_date: date
    executions_count: int
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def _coerce_orm(cls, data: Any) -> Any:
        if isinstance(data, dict) or not hasattr(data, "symbol"):
            return data
        return {
            "id": data.id,
            "ticker": data.symbol,
            "amount": data.amount,
            "frequency": data.frequency,
            "start_date": data.start_date,
            "end_condition": _end_condition_payload(data),
            "status": data.status,
            "next_run_date": data.next_run_date,
            "executions_count": data.executions_count,
            "created_at": data.created_at,
            "updated_at": data.updated_at,
        }


class RecurringInvestmentListResponse(BaseModel):
    recurring_investments: list[RecurringInvestmentRead]
