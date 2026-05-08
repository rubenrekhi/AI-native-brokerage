from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class CashInterestResponse(BaseModel):
    """Aggregated cash sweep snapshot: balance, APY, accrued and realized interest.

    Monetary values are string decimals (matches AccountValueResponse). `apy`
    is a decimal fraction (0.0425 = 4.25%). `interest_paid_out` is constrained
    to the cadences the iOS PaidOutCadence enum accepts so a misconfigured
    deploy fails at validation rather than breaking iOS decode.
    """

    balance: str
    apy: str
    this_month_earned: str
    days_accrued: int
    lifetime_earned: str
    lifetime_since: datetime | None
    buying_power: str
    pending_deposits: str
    interest_paid_out: Literal["monthly", "quarterly", "annually"]
    fdic_insured_limit: str
    sweep_status: str | None
