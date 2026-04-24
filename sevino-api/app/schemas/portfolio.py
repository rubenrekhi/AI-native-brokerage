from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.schemas._types import MoneyStr, PctStr


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
