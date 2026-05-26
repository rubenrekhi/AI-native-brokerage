"""Shared change-for-range helper so model prose and iOS card don't drift."""

from __future__ import annotations

from app.ai.blocks import Bar


PERFORMANCE_RANGES: tuple[str, ...] = ("1D", "1W", "1M", "3M", "6M", "1Y")


def bars_from_chart(chart: dict) -> list[Bar]:
    return [
        Bar(t=bar["timestamp"], c=float(bar["close"]))
        for bar in chart.get("bars", [])
    ]


def change_for_range(
    *,
    range_label: str,
    bars: list[Bar],
    price: float,
    daily_change_abs: float,
    daily_change_pct: float,
) -> tuple[float, float]:
    # "1D" uses FMP's daily change (vs yesterday's close), not first-bar diff —
    # 1D bars start at today's open. Longer ranges diff first-bar to price.
    # Fall back to daily change on degenerate bars so the card never blanks.
    if range_label == "1D":
        return daily_change_abs, daily_change_pct
    if not bars:
        return daily_change_abs, daily_change_pct
    first_close = bars[0].c
    if first_close <= 0:
        return daily_change_abs, daily_change_pct
    change_abs = price - first_close
    change_pct = change_abs / first_close
    return change_abs, change_pct
