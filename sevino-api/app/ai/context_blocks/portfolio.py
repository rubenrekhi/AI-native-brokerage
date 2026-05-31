from __future__ import annotations

from typing import Literal

from app.ai.context_blocks.base import ContextBlock
from app.schemas.conversations import ContextKind

# iOS sends the chart's selected range as ``data["time_range"]``: a
# ``TimeRange`` raw value (see AttachedContext.swift / TimeRange.swift). Only
# these known codes map to a fixed hint phrase; an absent or unrecognized
# value falls back to the generic description, so arbitrary client ``data``
# is never echoed into model input. The range is categorical UI state, not a
# market value, so it is safe to surface and does not go stale across turns.
_TIME_RANGE_LABELS = {
    "1D": "1-day",
    "1W": "1-week",
    "1M": "1-month",
    "3M": "3-month",
    "6M": "6-month",
    "YTD": "year-to-date",
    "1Y": "1-year",
    "ALL": "all-time",
}


class PortfolioContextBlock(ContextBlock):
    kind: Literal[ContextKind.PORTFOLIO] = ContextKind.PORTFOLIO

    def render_hint(self) -> str:
        raw = self.data.get("time_range")
        label = _TIME_RANGE_LABELS.get(raw) if isinstance(raw, str) else None
        if label is None:
            return (
                "The user is currently viewing their portfolio. This screen "
                "shows their total account value, the gain or loss over a "
                "selected time range, and an interactive value-over-time "
                "chart with range options from one day to all-time. Their "
                "message may be referring to a figure, trend, or time period "
                "shown here."
            )
        return (
            "The user is currently viewing their portfolio, with the value "
            f"chart set to the {label} range. This screen shows their total "
            "account value and the gain or loss over that range on an "
            "interactive value-over-time chart. Their message may be "
            "referring to a figure, trend, or the selected period shown here."
        )
