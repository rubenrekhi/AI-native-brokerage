from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.digest.context import ET
from app.services.digest.types import DigestContext

DEFAULT_POSITION_WEIGHT = Decimal("0.05")


def held_positions(ctx: DigestContext) -> list[dict[str, Any]]:
    """Return holdings with normalized symbols, de-duped in portfolio order."""
    positions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for holding in ctx.holdings:
        symbol = normalize_symbol(holding.get("symbol"))
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        positions.append({**holding, "symbol": symbol})
    return positions


def normalize_symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def holding_name(holding: dict[str, Any]) -> str:
    symbol = normalize_symbol(holding.get("symbol"))
    name = str(holding.get("name") or "").strip()
    return name or symbol


def position_weight(ctx: DigestContext, holding: dict[str, Any]) -> Decimal:
    for key in ("portfolio_weight", "weight"):
        value = to_decimal(holding.get(key))
        if value is not None:
            return max(value, Decimal("0"))

    market_value = to_decimal(holding.get("market_value"))
    if market_value is None:
        return DEFAULT_POSITION_WEIGHT

    total = to_decimal((ctx.portfolio_snapshot or {}).get("equity"))
    if total is None or total <= 0:
        total = sum(
            (
                value
                for value in (
                    to_decimal(item.get("market_value"))
                    for item in held_positions(ctx)
                )
                if value is not None
            ),
            Decimal("0"),
        )
    if total <= 0:
        return DEFAULT_POSITION_WEIGHT
    return max(market_value / total, Decimal("0"))


def to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def reports_at(
    reported_date,
    time_label: str | None,
    *,
    default_time: time,
) -> datetime:
    return datetime.combine(
        reported_date,
        report_time(time_label, default_time=default_time),
        tzinfo=ET,
    )


def report_time(time_label: str | None, *, default_time: time) -> time:
    normalized = (time_label or "").strip().lower()
    if normalized in {"bmo", "before market open"} or normalized.startswith(
        "before"
    ):
        return time(8, 0)
    if normalized in {"amc", "after market close"} or normalized.startswith(
        "after"
    ):
        return time(16, 0)
    if normalized in {"dmh", "during market hours"} or normalized.startswith(
        "during"
    ):
        return time(12, 0)
    return default_time
