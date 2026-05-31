from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError
from app.schemas.brokerage import OrderResponse
from app.services.alpaca_broker import (
    AlpacaBrokerError,
    AlpacaBrokerService,
    AlpacaBrokerUnavailableError,
)
from app.services.brokerage import BrokerageService
from app.services.digest.cards import OrderActivityItem, PendingOrderActivityCard
from app.services.digest.context import ET
from app.services.digest.generators._helpers import (
    money,
    parse_decimal,
    parse_datetime,
)
from app.services.digest.types import CardCandidate, DigestContext

logger = structlog.get_logger(__name__)

_RECURRING_PREFIXES = (
    "recurring_",
    "recurring-",
    "dca_",
    "dca-",
    "scheduled_",
    "scheduled-",
    "auto_",
    "auto-",
)
_FILLED_STATUSES = {"filled", "partially_filled"}
_RECURRING_SKIP_STATUSES = {"canceled", "expired", "rejected"}


class PendingOrdersGenerator:
    """Builds a card for order activity since the prior market close."""

    async def generate(
        self,
        ctx: DigestContext,
        db: AsyncSession,
        alpaca: AlpacaBrokerService,
    ) -> list[CardCandidate]:
        window_start = _prior_close(ctx.market_state.as_of)
        try:
            response = await BrokerageService.list_orders(
                db,
                alpaca=alpaca,
                user_id=ctx.user_id,
                status="closed",
                after=window_start.isoformat(),
                until=ctx.market_state.as_of.isoformat(),
                limit=100,
            )
        except NotFoundError:
            return []
        except (AlpacaBrokerError, AlpacaBrokerUnavailableError):
            logger.warning(
                "digest_pending_orders_unavailable", user_id=str(ctx.user_id)
            )
            return []

        filled: list[OrderActivityItem] = []
        recurring_executed: list[OrderActivityItem] = []
        recurring_skipped: list[OrderActivityItem] = []
        total_filled = Decimal("0")
        symbols: set[str] = set()

        for order in response.orders:
            if not _order_in_window(order, window_start):
                continue
            item = _activity_item(order)
            is_recurring = _is_recurring(order)
            if order.status in _FILLED_STATUSES:
                notional = _filled_notional(order)
                if notional is not None:
                    total_filled += notional
                symbols.add(item.symbol)
                if is_recurring:
                    recurring_executed.append(item)
                else:
                    filled.append(item)
            elif is_recurring and order.status in _RECURRING_SKIP_STATUSES:
                symbols.add(item.symbol)
                recurring_skipped.append(item)

        activity_count = (
            len(filled) + len(recurring_executed) + len(recurring_skipped)
        )
        if activity_count == 0:
            return []

        related_symbols = sorted(symbols)
        card = PendingOrderActivityCard(
            filled=filled,
            recurring_executed=recurring_executed,
            recurring_skipped=recurring_skipped,
            related_symbols=related_symbols,
            card_context={
                "window_start": window_start.isoformat(),
                "total_filled_notional": str(money(total_filled)),
                "activity_count": activity_count,
                "recurring_detection": "client_order_id_prefix",
            },
        )
        return [
            CardCandidate(
                card=card,
                event_type="pending_order_activity",
                magnitude_score=(
                    float(total_filled)
                    if total_filled > 0
                    else float(activity_count)
                ),
                related_symbols=related_symbols,
                dedupe_key=(
                    f"pending_orders:{ctx.user_id}:"
                    f"{window_start.date().isoformat()}"
                ),
            )
        ]


def _prior_close(now_utc: datetime) -> datetime:
    now_et = now_utc.astimezone(ET)
    close_today = datetime.combine(now_et.date(), time(hour=16), tzinfo=ET)
    if now_et.weekday() < 5 and now_et >= close_today:
        return close_today.astimezone(timezone.utc)

    days_back = 1
    candidate = now_et.date() - timedelta(days=days_back)
    while candidate.weekday() >= 5:
        days_back += 1
        candidate = now_et.date() - timedelta(days=days_back)
    return datetime.combine(candidate, time(hour=16), tzinfo=ET).astimezone(
        timezone.utc
    )


def _order_in_window(order: OrderResponse, window_start: datetime) -> bool:
    happened_at = parse_datetime(order.filled_at) or parse_datetime(
        order.canceled_at
    ) or parse_datetime(order.expired_at) or parse_datetime(order.failed_at)
    if happened_at is None and order.status == "partially_filled":
        happened_at = parse_datetime(order.submitted_at) or parse_datetime(
            order.created_at
        )
    return happened_at is not None and happened_at >= window_start


def _is_recurring(order: OrderResponse) -> bool:
    # App-created manual orders use UUID client_order_id values today. This
    # prefix hook is for future scheduled-order jobs and external Alpaca rows.
    client_order_id = (order.client_order_id or "").lower()
    return any(client_order_id.startswith(prefix) for prefix in _RECURRING_PREFIXES)


def _activity_item(order: OrderResponse) -> OrderActivityItem:
    notional = _filled_notional(order)
    symbol = order.symbol.upper()
    return OrderActivityItem(
        symbol=symbol,
        name=None,
        side=order.side if order.side in {"buy", "sell"} else None,
        qty=parse_decimal(order.filled_qty) or parse_decimal(order.qty),
        notional=money(notional) if notional is not None else None,
    )


def _filled_notional(order: OrderResponse) -> Decimal | None:
    notional = parse_decimal(order.notional)
    if notional is not None:
        return notional
    qty = parse_decimal(order.filled_qty) or parse_decimal(order.qty)
    price = parse_decimal(order.filled_avg_price) or parse_decimal(
        order.limit_price
    )
    if qty is None or price is None:
        return None
    return qty * price
