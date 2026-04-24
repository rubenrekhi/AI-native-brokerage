from __future__ import annotations

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


class HoldingsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    account_status: str
    currency: str
    cash: MoneyStr
    total_market_value: MoneyStr
    positions: list[Position]
