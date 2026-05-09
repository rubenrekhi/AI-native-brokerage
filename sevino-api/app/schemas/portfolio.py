from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas._types import MoneyStr, PctStr, QtyStr


class PortfolioSnapshotResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    account_status: str
    currency: str
    equity: MoneyStr
    last_equity: MoneyStr
    cash: MoneyStr
    buying_power: MoneyStr
    daily_change_abs: MoneyStr
    daily_change_pct: PctStr


class Position(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    name: str
    qty: QtyStr
    avg_entry_price: MoneyStr
    current_price: MoneyStr
    market_value: MoneyStr
    cost_basis: MoneyStr
    unrealized_pl: MoneyStr
    unrealized_plpc: PctStr
    change_today: MoneyStr
    change_today_percent: PctStr


class HoldingsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    account_status: str
    currency: str
    cash: MoneyStr
    total_market_value: MoneyStr
    positions: list[Position]


class PortfolioHistoryPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    t: datetime
    v: MoneyStr


class PortfolioHistoryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    range: str
    timeframe: str
    currency: str
    base_value: MoneyStr
    end_value: MoneyStr
    gain_abs: MoneyStr
    gain_pct: PctStr
    points: list[PortfolioHistoryPoint]
