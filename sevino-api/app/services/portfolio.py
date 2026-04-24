from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum


class PortfolioRange(StrEnum):
    ONE_DAY = "1D"
    ONE_WEEK = "1W"
    ONE_MONTH = "1M"
    THREE_MONTHS = "3M"
    SIX_MONTHS = "6M"
    YTD = "YTD"
    ONE_YEAR = "1Y"
    ALL = "ALL"


def range_to_alpaca_params(
    r: PortfolioRange, *, now: datetime | None = None
) -> dict[str, str]:
    """Map the iOS-facing range to Alpaca /portfolio/history query params.

    Alpaca accepts any subset of ``{period, timeframe, start}`` and computes
    the rest. ``now`` is injectable so YTD is deterministic in tests.
    """
    now = now or datetime.now(tz=timezone.utc)
    match r:
        case PortfolioRange.ONE_DAY:
            return {"period": "1D", "timeframe": "5Min"}
        case PortfolioRange.ONE_WEEK:
            return {"period": "1W", "timeframe": "30Min"}
        case PortfolioRange.ONE_MONTH:
            return {"period": "1M", "timeframe": "1D"}
        case PortfolioRange.THREE_MONTHS:
            return {"period": "3M", "timeframe": "1D"}
        case PortfolioRange.SIX_MONTHS:
            return {"period": "6M", "timeframe": "1D"}
        case PortfolioRange.YTD:
            start = f"{now.year}-01-01T00:00:00Z"
            return {"timeframe": "1D", "start": start}
        case PortfolioRange.ONE_YEAR:
            return {"period": "1A", "timeframe": "1D"}
        case PortfolioRange.ALL:
            return {"period": "all", "timeframe": "1W"}
