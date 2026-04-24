"""Pydantic models for /v1/settings/* endpoints."""

import uuid
from datetime import date as _date
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.schemas.onboarding import FinancialProfileData, ProfileData


class Theme(str, Enum):
    system = "system"
    light = "light"
    dark = "dark"


class TextSize(str, Enum):
    small = "small"
    standard = "standard"
    large = "large"


class UserSettingsResponse(BaseModel):
    theme: Theme
    text_size: TextSize
    notifications_enabled: bool
    ai_internet_access: bool

    model_config = ConfigDict(from_attributes=True)


class UserSettingsPatchRequest(BaseModel):
    theme: Theme | None = None
    text_size: TextSize | None = None
    notifications_enabled: bool | None = None
    ai_internet_access: bool | None = None

    @model_validator(mode="after")
    def at_least_one_field(self) -> "UserSettingsPatchRequest":
        if not self.model_dump(exclude_none=True):
            raise ValueError("at least one field must be provided")
        return self


class BrokerageAccountSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    account_number: str | None = None
    account_status: str
    kyc_results: dict[str, Any] | None = None


class LinkedAccountSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    alpaca_relationship_id: str
    institution_name: str | None = None
    account_mask: str | None = None
    account_type: str | None = None
    nickname: str | None = None
    status: str


class SettingsProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    profile: ProfileData
    financial_profile: FinancialProfileData | None = None
    brokerage: BrokerageAccountSummary | None = None
    linked_accounts: list[LinkedAccountSummary] = []
    member_since: datetime


class AccountValueResponse(BaseModel):
    """Live brokerage account balances (all values are dollar strings from Alpaca)."""

    equity: str
    cash: str
    buying_power: str
    portfolio_value: str


class DocumentResponse(BaseModel):
    id: str
    type: str
    date: _date | None = None
    name: str | None = None

    @field_validator("name", mode="before")
    @classmethod
    def _blank_name_to_none(cls, v: Any) -> Any:
        if isinstance(v, str) and not v.strip():
            return None
        return v


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]


class DeleteAccountRequest(BaseModel):
    """Body for DELETE /v1/settings/account. Requires literal "DELETE" string."""

    confirmation: str

    @field_validator("confirmation")
    @classmethod
    def must_be_delete(cls, v: str) -> str:
        if v != "DELETE":
            raise ValueError('confirmation must be the literal string "DELETE"')
        return v
