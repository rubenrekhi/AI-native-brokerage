"""Pydantic models for /v1/funding/* endpoints."""

import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LinkTokenResponse(BaseModel):
    link_token: str


class LinkBankRequest(BaseModel):
    public_token: str
    account_id: str  # Plaid `accounts[0].id` from onSuccess metadata
    institution_name: str | None = None
    account_mask: str | None = None
    account_name: str | None = None
    nickname: str | None = None


class AchRelationshipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    alpaca_relationship_id: str
    institution_name: str | None = None
    account_mask: str | None = None
    account_type: str | None = None
    nickname: str | None = None
    status: str


class TransferRequest(BaseModel):
    relationship_id: uuid.UUID  # local AchRelationship PK, NOT Alpaca's
    amount: Decimal = Field(..., gt=0, max_digits=12, decimal_places=2)
    direction: Literal["INCOMING", "OUTGOING"]


class TransferBank(BaseModel):
    nickname: str | None = None
    account_mask: str | None = None
    institution_name: str | None = None


class TransferResponse(BaseModel):
    """Alpaca transfer record plus our merged `bank` metadata.

    Extra fields from Alpaca pass through untouched.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    status: str
    amount: str
    direction: str
    created_at: str | None = None
    bank: TransferBank | None = None


class TransferListResponse(BaseModel):
    transfers: list[TransferResponse]
