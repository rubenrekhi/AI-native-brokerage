"""Maps a UTC instant to a US-market time bucket.

Buckets are anchored to US Eastern Time so market-related content lines
up with NYSE hours; ``ZoneInfo`` handles DST automatically.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


class TimeBucket(StrEnum):
    MORNING = "morning"
    MARKET_HOURS = "market_hours"
    AFTER_MARKET = "after_market"
    NIGHT = "night"


def current_bucket(now_utc: datetime) -> TimeBucket:
    et = now_utc.astimezone(ET)
    minutes = et.hour * 60 + et.minute
    if 4 * 60 <= minutes < 9 * 60 + 30:
        return TimeBucket.MORNING
    if 9 * 60 + 30 <= minutes < 16 * 60:
        return TimeBucket.MARKET_HOURS
    if 16 * 60 <= minutes < 20 * 60:
        return TimeBucket.AFTER_MARKET
    return TimeBucket.NIGHT
