"""Pydantic models for /v1/settings/* endpoints."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.schemas.onboarding import FinancialProfileData, ProfileData


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
