"""Builds the live time + market-status block appended to the system prompt.

This block is kept *out* of the cached system prompt on purpose. The static
prompt is sent as a cache breakpoint (see ``runtime/loop.py``), so a clock
value baked into it would invalidate the prompt cache on every turn. The
text produced here is appended *after* the breakpoint — uncached — so the
static prefix still gets a cache hit while the model sees a fresh clock.

Market times are always rendered in US Eastern (``America/New_York``);
``ZoneInfo`` picks EST vs EDT for the instant, so the label is correct
year-round rather than a hardcoded "EST" that would be wrong half the year.
When the client sends its IANA timezone, the user's local time is rendered
alongside Eastern so the model can reason in both frames at once.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ET = ZoneInfo("America/New_York")


def _format_zone(dt: datetime, zone: ZoneInfo) -> str:
    # astimezone() reads a naive datetime as system-local; every input here is UTC.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(zone)
    return f"{local.strftime('%A, %B %-d, %Y at %-I:%M %p')} {local.tzname()}"


def _format_et(dt: datetime) -> str:
    return _format_zone(dt, ET)


def _resolve_zone(name: str | None) -> ZoneInfo | None:
    """Resolve a client-supplied IANA identifier to a ``ZoneInfo``.

    ``name`` is untrusted client input. ``ZoneInfo`` raises ``ValueError`` for
    keys that are absolute paths or contain ``..`` (its path-traversal guard)
    and ``ZoneInfoNotFoundError`` for well-formed but unknown zones — both mean
    "can't trust this", so both fall back to ``None`` and the caller degrades
    to Eastern-only rather than failing the turn.
    """
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def _parse_clock_ts(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def build_time_context(
    now_utc: datetime,
    market_status: dict[str, Any] | None,
    client_timezone: str | None = None,
) -> str:
    """Render the time/market-status block for ``now_utc``.

    ``market_status`` is the payload from
    ``MarketDataService.get_market_status`` (``is_open`` / ``next_open`` /
    ``next_close``), or ``None`` when the clock is unavailable — in which case
    only the current time is reported.

    ``client_timezone`` is the device's IANA identifier (e.g.
    ``"America/Los_Angeles"``). When present and valid, the user's local time
    is rendered alongside Eastern; when it resolves to the same wall clock as
    Eastern (equal UTC offset at this instant), the duplicate collapses to the
    single Eastern line. Market times stay in Eastern regardless.
    """
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    user_zone = _resolve_zone(client_timezone)
    if user_zone is not None and (
        now_utc.astimezone(user_zone).utcoffset()
        == now_utc.astimezone(ET).utcoffset()
    ):
        user_zone = None

    if user_zone is not None:
        paragraph = (
            f"The current date and time is {_format_zone(now_utc, user_zone)} "
            "(the user's local time). In US Eastern Time — the timezone US "
            f"markets operate on — it is {_format_et(now_utc)}."
        )
    else:
        paragraph = (
            f"The current date and time is {_format_et(now_utc)} "
            "(US Eastern Time — the timezone US markets operate on)."
        )

    if market_status is not None:
        if bool(market_status.get("is_open")):
            paragraph += " The US stock market is currently open."
            next_close = _parse_clock_ts(market_status.get("next_close"))
            if next_close is not None:
                paragraph += f" It next closes {_format_et(next_close)}."
        else:
            paragraph += " The US stock market is currently closed."
            next_open = _parse_clock_ts(market_status.get("next_open"))
            if next_open is not None:
                paragraph += f" It next opens {_format_et(next_open)}."

    return f"## Current date, time, and market status\n\n{paragraph}"
