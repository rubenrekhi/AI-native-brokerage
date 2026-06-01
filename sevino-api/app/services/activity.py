"""Account activity feed: a unified, time-sorted view over a user's trades,
transfers, dividends, and interest for the AI ``get_account_activity`` tool.

Fans out to the Alpaca order, transfer, and DIV/INT activity endpoints,
normalizes each into a common row shape, windows them to a date range, and
sums per-type totals so the model can answer "what did I do this month / how
much did I deposit / have my dividends come in" from one call.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.alpaca_broker import AlpacaBrokerService
from app.services.brokerage import require_brokerage

logger = structlog.get_logger(__name__)

ActivityType = Literal["trade", "deposit", "withdrawal", "dividend", "interest"]

ALL_ACTIVITY_TYPES: tuple[ActivityType, ...] = (
    "trade",
    "deposit",
    "withdrawal",
    "dividend",
    "interest",
)

# Statuses where an order actually moved shares. Only these count toward
# ``totals.executed_trades`` — a working or canceled order isn't a trade you
# made, even when it's surfaced in the feed.
_EXECUTED_ORDER_STATUSES = frozenset({"filled", "partially_filled"})

# Terminal orders where nothing (more) will ever trade.
#
# ``done_for_day`` is deliberately NOT terminal: it means the order stopped
# executing for today's session but resumes next trading day, so a GTC /
# multi-day order is still live. It stays in the working set — surfaced by
# default and counted toward ``open_orders``.
_TERMINAL_NON_FILL_STATUSES = frozenset(
    {"canceled", "rejected", "expired", "replaced"}
)

# Orders on their way out: a cancel or replace has been requested. Alpaca may
# still fill them before the request settles, but the user has moved to close
# them, so they aren't working orders you're waiting on — treated like terminal
# orders for counting and default visibility, not as open orders.
_PENDING_CLOSE_STATUSES = frozenset({"pending_cancel", "pending_replace"})

# Neither transaction history nor a working order: excluded from the default
# feed and from ``totals.open_orders``, surfaced only when the caller asks via
# ``include_canceled`` ("did my order get canceled / rejected?"). Everything
# else (executed + still-working orders) shows by default, so an unknown future
# Alpaca status fails open (surfaced) rather than silently dropped.
_NON_WORKING_STATUSES = _TERMINAL_NON_FILL_STATUSES | _PENDING_CLOSE_STATUSES

# Alpaca caps the orders list at 500. The date window bounds real volume; the
# merged feed is truncated to the caller's ``limit`` after summing totals.
_ORDER_FETCH_LIMIT = 500

# The transfers endpoint takes no date filter (only direction/limit/offset), so
# unlike orders / dividends / interest it can't be windowed server-side — we cap
# the fetch and window client-side. Results are newest-first, so any recent
# window is fully covered; an all-time query on an account with more than this
# many transfers would miss the oldest few.
_TRANSFER_FETCH_LIMIT = 500

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


class ActivityService:
    @staticmethod
    async def get_activity(
        db: AsyncSession,
        *,
        alpaca: AlpacaBrokerService,
        user_id: uuid.UUID,
        types: list[ActivityType] | None = None,
        after: str | None = None,
        until: str | None = None,
        symbol: str | None = None,
        include_canceled: bool = False,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Build the unified activity payload for ``user_id``.

        Executed and still-working orders are included by default; canceled /
        rejected / expired orders are surfaced only when ``include_canceled`` is
        set. Raises ``NotFoundError`` when the user has no active brokerage
        account. Per-source upstream failures are logged and skipped; only an
        all-source failure re-raises the first source exception.
        """
        brokerage = await require_brokerage(db, user_id)
        account_id = brokerage.alpaca_account_id

        after_dt = _parse_dt(after, end_of_day=False)
        until_dt = _parse_dt(until, end_of_day=True)
        # A ticker can only match a trade or a dividend; transfers and interest
        # are dropped from the request rather than returned as never-matching.
        wanted = _effective_types(types, symbol=symbol)

        fetchers: list[tuple[str, Any]] = []
        if "trade" in wanted:
            # Alpaca windows orders on ``submitted_at``, but ``_trade_row`` sorts
            # and re-windows on ``filled_at``: an order filled just outside a
            # window it was submitted into is dropped client-side, and one
            # submitted before the window but filled inside it is never fetched.
            # Bites only multi-day orders straddling a boundary; same-day fills
            # (the common case) are unaffected.
            fetchers.append(
                (
                    "trade",
                    alpaca.list_orders(
                        account_id,
                        status="all",
                        symbols=symbol,
                        after=after_dt.isoformat() if after_dt else None,
                        until=until_dt.isoformat() if until_dt else None,
                        limit=_ORDER_FETCH_LIMIT,
                        direction="desc",
                    ),
                )
            )
        if "deposit" in wanted or "withdrawal" in wanted:
            # A single-direction request lets Alpaca drop the other half; both
            # directions wanted → no filter, window applied client-side.
            wanted_transfers = wanted & {"deposit", "withdrawal"}
            transfer_direction = (
                "INCOMING"
                if wanted_transfers == {"deposit"}
                else "OUTGOING" if wanted_transfers == {"withdrawal"} else None
            )
            fetchers.append(
                (
                    "transfer",
                    alpaca.list_transfers(
                        account_id,
                        direction=transfer_direction,
                        limit=_TRANSFER_FETCH_LIMIT,
                    ),
                )
            )
        if "dividend" in wanted:
            fetchers.append(
                (
                    "dividend",
                    alpaca.get_dividend_activities(
                        account_id=account_id,
                        after=after_dt.isoformat() if after_dt else None,
                        until=until_dt.isoformat() if until_dt else None,
                        paginate=True,
                    ),
                )
            )
        if "interest" in wanted:
            fetchers.append(
                (
                    "interest",
                    alpaca.get_interest_activities(
                        account_id=account_id,
                        after=after_dt.isoformat() if after_dt else None,
                        until=until_dt.isoformat() if until_dt else None,
                        paginate=True,
                    ),
                )
            )

        results = await asyncio.gather(
            *(coro for _, coro in fetchers), return_exceptions=True
        )

        rows: list[tuple[datetime, dict[str, Any]]] = []
        succeeded: set[str] = set()
        partial = False
        for (source, _), result in zip(fetchers, results):
            if isinstance(result, BaseException):
                partial = True
                logger.warning(
                    "account_activity_source_failed",
                    user_id=str(user_id),
                    source=source,
                    error=str(result),
                    exc_type=type(result).__name__,
                )
                continue
            succeeded.add(source)
            rows.extend(
                _normalize_source(
                    source,
                    result,
                    wanted=wanted,
                    after=after_dt,
                    until=until_dt,
                    symbol=symbol,
                    include_canceled=include_canceled,
                )
            )

        if fetchers and not succeeded:
            # Every requested source failed — surface as unavailable rather than
            # claiming the user had no activity. Re-raise the first error so the
            # tool maps it to a graceful "temporarily unavailable".
            first_exc = next(r for r in results if isinstance(r, BaseException))
            raise first_exc

        rows.sort(key=lambda pair: pair[0], reverse=True)
        activities = [row for _, row in rows]

        totals = _totals(activities, succeeded)
        matched = len(activities)
        truncated = matched > limit
        if truncated:
            activities = activities[:limit]

        payload: dict[str, Any] = {
            "range": {
                "after": after_dt.isoformat() if after_dt else None,
                "until": until_dt.isoformat() if until_dt else None,
            },
            "count": len(activities),
            "matched": matched,
            "truncated": truncated,
            "totals": totals,
            "activities": activities,
        }
        if partial:
            # Tell the model some data is missing so it can caveat rather than
            # assert a complete picture.
            payload["partial"] = True
        if symbol and not wanted:
            # A symbol paired only with non-symbol types (deposit/withdrawal/
            # interest) filters every requested type out, so nothing is fetched.
            # Flag it so the model explains the mismatch instead of reporting an
            # empty history.
            payload["note"] = (
                f"'{symbol}' only narrows trades and dividends; the requested "
                "activity types aren't symbol-specific, so nothing was fetched. "
                "Drop the symbol to see them."
            )
        return payload


def _effective_types(
    types: list[ActivityType] | None, *, symbol: str | None
) -> set[ActivityType]:
    selected: set[ActivityType] = (
        set(ALL_ACTIVITY_TYPES) if not types else set(types)
    )
    if symbol:
        selected &= {"trade", "dividend"}
    return selected


def _normalize_source(
    source: str,
    raw: Any,
    *,
    wanted: set[ActivityType],
    after: datetime | None,
    until: datetime | None,
    symbol: str | None,
    include_canceled: bool,
) -> list[tuple[datetime, dict[str, Any]]]:
    if not isinstance(raw, list):
        return []
    out: list[tuple[datetime, dict[str, Any]]] = []
    for rec in raw:
        if not isinstance(rec, dict):
            continue
        built = _ROW_BUILDERS[source](rec)
        if built is None:
            continue
        ts, row = built
        if row["type"] not in wanted:
            continue
        if (
            source == "trade"
            and not include_canceled
            and row["status"] in _NON_WORKING_STATUSES
        ):
            continue
        # The DIV endpoint isn't symbol-scoped (orders are, server-side), so
        # filter dividend rows to the requested ticker here.
        if symbol and row.get("symbol") != symbol:
            continue
        if not _in_window(ts, after, until):
            continue
        out.append((ts or _EPOCH, row))
    return out


def _trade_row(o: dict[str, Any]) -> tuple[datetime | None, dict[str, Any]] | None:
    status = o.get("status")
    side = o.get("side")
    symbol = o.get("symbol")
    filled_qty_d = _dec(o.get("filled_qty"))
    fill_price = _dec(o.get("filled_avg_price"))
    value = (
        filled_qty_d * fill_price
        if filled_qty_d is not None and fill_price is not None
        else None
    )
    amount = None
    if value:
        # Falsy value (a working order with no fill yet) leaves amount null.
        amount = _money(-value) if side == "buy" else _money(value)
    ts = _first_dt(o, ("filled_at", "submitted_at", "created_at"))
    limit_price = o.get("limit_price")
    notional = o.get("notional")
    row: dict[str, Any] = {
        "type": "trade",
        "date": _iso(ts),
        "symbol": symbol,
        "side": side,
        "order_type": o.get("order_type"),
        "status": status,
        # ``qty`` is what was ordered; ``filled_qty`` is what executed. They
        # differ for working and partially-filled orders.
        "qty": o.get("qty"),
        "filled_qty": o.get("filled_qty"),
        "price": o.get("filled_avg_price"),
        "amount": amount,
        "summary": _trade_summary(
            side=side,
            symbol=symbol,
            status=status,
            order_qty=o.get("qty"),
            filled_qty=o.get("filled_qty"),
            notional=notional,
            fill_price=fill_price,
            limit_price=_dec(limit_price),
        ),
    }
    # Carried only when set — they matter for working limit/notional orders and
    # would be null noise on a plain filled market order.
    if limit_price is not None:
        row["limit_price"] = limit_price
    if notional is not None:
        row["notional"] = notional
    return ts, row


def _transfer_row(
    t: dict[str, Any],
) -> tuple[datetime | None, dict[str, Any]] | None:
    direction = t.get("direction")
    kind: ActivityType = "deposit" if direction == "INCOMING" else "withdrawal"
    amount = _dec(t.get("amount"))
    ts = _first_dt(t, ("created_at", "updated_at"))
    signed = None
    if amount is not None:
        signed = _money(amount if kind == "deposit" else -amount)
    return ts, {
        "type": kind,
        "date": _iso(ts),
        "symbol": None,
        "amount": signed,
        "status": t.get("status"),
        "summary": _transfer_summary(kind, amount, t.get("status")),
    }


def _dividend_row(
    d: dict[str, Any],
) -> tuple[datetime | None, dict[str, Any]] | None:
    net = _dec(d.get("net_amount"))
    # The DIV bucket also carries withholdings (DIVNRA/DIVTAX) and ADR fees
    # (DIVFEE) as negative amounts; the positive filter keeps only payments.
    if net is None or net <= 0:
        return None
    symbol = d.get("symbol")
    ts = _first_dt(d, ("created_at", "date", "transaction_time"))
    return ts, {
        "type": "dividend",
        "date": _iso(ts),
        "symbol": symbol,
        "amount": _money(net),
        "status": d.get("status"),
        "summary": _dividend_summary(symbol, net),
    }


def _interest_row(
    i: dict[str, Any],
) -> tuple[datetime | None, dict[str, Any]] | None:
    net = _dec(i.get("net_amount"))
    # Positive net = interest earned (e.g. FDIC sweep). Negative INT rows are
    # margin charges, out of scope for the cash-sweep feed.
    if net is None or net <= 0:
        return None
    ts = _first_dt(i, ("date", "created_at", "transaction_time"))
    return ts, {
        "type": "interest",
        "date": _iso(ts),
        "symbol": i.get("symbol"),
        "amount": _money(net),
        "status": i.get("status"),
        "summary": _interest_summary(net, i.get("description")),
    }


_ROW_BUILDERS = {
    "trade": _trade_row,
    "transfer": _transfer_row,
    "dividend": _dividend_row,
    "interest": _interest_row,
}


def _totals(
    activities: list[dict[str, Any]], succeeded: set[str]
) -> dict[str, Any]:
    """Sum per-type totals over the full windowed set (pre-truncation).

    Only includes a key for a source that was actually fetched and returned —
    omitting a key is honest about "we didn't look", a 0.00 would lie.
    """
    totals: dict[str, Any] = {}
    if "transfer" in succeeded:
        totals["deposited"] = _money(
            _sum(a["amount"] for a in activities if a["type"] == "deposit")
        )
        # Withdrawal rows carry a negative amount; negate the sum so
        # ``withdrawn`` reads as a positive dollar magnitude.
        totals["withdrawn"] = _money(
            -_sum(a["amount"] for a in activities if a["type"] == "withdrawal")
        )
    if "dividend" in succeeded:
        totals["dividends"] = _money(
            _sum(a["amount"] for a in activities if a["type"] == "dividend")
        )
    if "interest" in succeeded:
        totals["interest"] = _money(
            _sum(a["amount"] for a in activities if a["type"] == "interest")
        )
    if "trade" in succeeded:
        trade_rows = [a for a in activities if a["type"] == "trade"]
        # Split the count so "trades I made" and "orders still pending" are
        # each handed to the model directly — it never has to (mis)count rows.
        # ``executed_trades`` is fills only; ``open_orders`` is still-working
        # orders (no fill yet, and neither terminal nor on their way out via a
        # cancel/replace). A canceled or pending-cancel order is in neither.
        totals["executed_trades"] = sum(
            1 for a in trade_rows if a["status"] in _EXECUTED_ORDER_STATUSES
        )
        totals["open_orders"] = sum(
            1
            for a in trade_rows
            if a["status"] not in _EXECUTED_ORDER_STATUSES
            and a["status"] not in _NON_WORKING_STATUSES
        )
    return totals


def _trade_summary(
    *,
    side: Any,
    symbol: Any,
    status: Any,
    order_qty: Any,
    filled_qty: Any,
    notional: Any,
    fill_price: Decimal | None,
    limit_price: Decimal | None,
) -> str:
    sym = symbol or "?"
    if status in _EXECUTED_ORDER_STATUSES and fill_price is not None:
        verb = "Bought" if side == "buy" else "Sold" if side == "sell" else "Traded"
        qty_part = f"{filled_qty} " if filled_qty else ""
        prefix = "Partially " if status == "partially_filled" else ""
        body = f"{verb} {qty_part}{sym} @ ${_money(fill_price)}"
        return f"{prefix}{body[0].lower()}{body[1:]}" if prefix else body
    # Working or terminal order — describe the order, not a (non-existent) fill.
    action = "Buy" if side == "buy" else "Sell" if side == "sell" else "Order"
    if order_qty:
        size = f"{order_qty} {sym}"
    elif notional is not None:
        size = f"${notional} of {sym}"
    else:
        size = sym
    price_part = f" @ ${_money(limit_price)} limit" if limit_price is not None else ""
    return f"{action} order: {size}{price_part} ({status})"


def _transfer_summary(kind: ActivityType, amount: Decimal | None, status: Any) -> str:
    verb = "Deposited" if kind == "deposit" else "Withdrew"
    amt = f"${_money(amount)}" if amount is not None else "funds"
    suffix = f" ({status})" if status and status not in ("COMPLETE", "settled") else ""
    return f"{verb} {amt}{suffix}"


def _dividend_summary(symbol: Any, net: Decimal) -> str:
    sym = f" from {symbol}" if symbol else ""
    return f"Dividend{sym}: ${_money(net)}"


def _interest_summary(net: Decimal, description: Any) -> str:
    if isinstance(description, str) and description:
        return f"Interest: ${_money(net)} ({description})"
    return f"Interest: ${_money(net)}"


def _first_dt(rec: dict[str, Any], keys: tuple[str, ...]) -> datetime | None:
    for key in keys:
        dt = _parse_dt(rec.get(key))
        if dt is not None:
            return dt
    return None


def _in_window(
    ts: datetime | None, after: datetime | None, until: datetime | None
) -> bool:
    if after is None and until is None:
        return True
    # A record we can't date can't be proven in-range — exclude it from a
    # windowed query rather than mislabel it as "this week".
    if ts is None:
        return False
    if after is not None and ts < after:
        return False
    if until is not None and ts > until:
        return False
    return True


def _parse_dt(raw: Any, *, end_of_day: bool = False) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    s = raw.strip()
    date_only = bool(_DATE_ONLY.match(s))
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if date_only and end_of_day:
        dt = dt + timedelta(days=1) - timedelta(microseconds=1)
    return dt.astimezone(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _sum(values: Any) -> Decimal:
    total = Decimal("0")
    for v in values:
        d = _dec(v)
        if d is not None:
            total += d
    return total


def _money(value: Decimal | None) -> str:
    return f"{(value or Decimal('0')):.2f}"
