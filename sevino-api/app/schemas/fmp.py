from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from app.schemas._types import MoneyStr


class _EarningsBase(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)

    symbol: str
    reported_date: date = Field(validation_alias=AliasChoices("date", "reportedDate"))
    time: str | None = None
    eps_actual: MoneyStr | None = Field(
        default=None, validation_alias=AliasChoices("epsActual", "eps")
    )
    eps_estimate: MoneyStr | None = Field(
        default=None,
        validation_alias=AliasChoices("epsEstimated", "epsEstimate", "epsEst"),
    )
    revenue_actual: MoneyStr | None = Field(
        default=None, validation_alias=AliasChoices("revenueActual", "revenue")
    )
    revenue_estimate: MoneyStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "revenueEstimated", "revenueEstimate", "revenueEst"
        ),
    )
    fiscal_date_ending: date | None = Field(default=None, alias="fiscalDateEnding")

    @field_validator(
        "eps_actual",
        "eps_estimate",
        "revenue_actual",
        "revenue_estimate",
        mode="before",
    )
    @classmethod
    def _decimal_or_none(cls, value: Any) -> Decimal | None:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        try:
            return Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError("value must be a valid decimal number") from exc

    @field_validator("fiscal_date_ending", mode="before")
    @classmethod
    def _date_or_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class EarningsCalendarItem(_EarningsBase):
    last_updated: date | None = Field(
        default=None,
        validation_alias=AliasChoices("lastUpdated", "updatedFromDate"),
    )

    @field_validator("last_updated", mode="before")
    @classmethod
    def _last_updated_or_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class HistoricalEarningsItem(_EarningsBase):
    pass
