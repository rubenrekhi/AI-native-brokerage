"""Pydantic models for /v1/settings/* endpoints."""

from pydantic import BaseModel


class AccountValueResponse(BaseModel):
    """Live brokerage account balances (all values are dollar strings from Alpaca)."""

    equity: str
    cash: str
    buying_power: str
    portfolio_value: str
