"""Pydantic schemas for the `/v1/radar` endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas._types import MoneyStr, PctStr

RadarSource = Literal["user_added", "ai_generated"]


class RadarItemCreate(BaseModel):
    """Body for `POST /v1/radar`. The server hardcodes every other field
    (source, favorited state, expiry) — iOS only chooses the ticker."""

    model_config = ConfigDict(frozen=True)

    symbol: str = Field(min_length=1, max_length=10)


class RadarItemUpdate(BaseModel):
    """Body for `PATCH /v1/radar/{id}`. Only the favorite flag is editable."""

    model_config = ConfigDict(frozen=True)

    is_favorited: bool


class RadarItemRead(BaseModel):
    """Response shape for radar list / create / update endpoints.

    The `price` / `change_abs` / `change_pct` overlay fields are populated
    only on GET — the service merges them in from market-data quotes.
    POST and PATCH responses leave them as None.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    symbol: str
    company_name: str | None
    context_blurb: str | None
    source: RadarSource
    is_favorited: bool
    relevance_score: float | None
    expires_at: datetime | None
    created_at: datetime

    price: MoneyStr | None = None
    change_abs: MoneyStr | None = None
    change_pct: PctStr | None = None
