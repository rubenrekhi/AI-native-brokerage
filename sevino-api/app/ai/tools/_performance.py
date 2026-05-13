"""Shared per-range price-change helper used by both ``get_stock_info``
and ``display_stock_card``.

Both tools fetch the same chart-bar payloads (cached in Redis) and need
identical ``(change_abs, change_pct)`` values for each range. Sharing
this one function guarantees the model's prose and the iOS card always
agree on the numbers — the two tools can't drift apart because they
literally run the same arithmetic.
"""

from __future__ import annotations

from app.ai.blocks import Bar


# Ranges both tools fetch and report performance for. Intersected with
# what iOS's ``TimeRange`` enum knows and what ``MarketDataService.get_chart``
# supports, so every range maps cleanly on both sides.
PERFORMANCE_RANGES: tuple[str, ...] = ("1D", "1W", "1M", "3M", "6M", "1Y")


def bars_from_chart(chart: dict) -> list[Bar]:
    """Map a ``MarketDataService.get_chart`` payload onto the wire-format
    ``Bar`` list. Drops every field except ``timestamp`` → ``t`` and
    ``close`` → ``c`` per the minimal sparkline shape.
    """
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
    """Compute ``(change_abs, change_pct)`` for one range.

    * For ``"1D"``, return the FMP quote's daily change (vs *yesterday's
      close*). The 1D chart bars start at today's *market open*, so
      diffing first-bar-to-now would give "change since open" — which
      contradicts the conventional "X is up Y% today" meaning the AI
      uses in prose.
    * For longer ranges, derive from the chart: ``price - first_bar.close``.
      The first bar is approximately N-time-ago's close, which is what
      "change over this range" means there.

    Returns the daily fallback when bars are missing or the first bar's
    close is non-positive (degenerate input shouldn't blank the card —
    just show daily change instead of nothing).
    """
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
