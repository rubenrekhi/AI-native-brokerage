"""Data access for `order_events` — the per-user record of orders placed
through Alpaca.

Rows are written by the trading service when an order is submitted and
updated in place by the trade-events SSE handler as the order's lifecycle
progresses (`new` → `partially_filled` → `filled`, or to `canceled` /
`expired` / `rejected`).
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.brokerage_account import BrokerageAccount
from app.models.order_event import OrderEvent


class OpenOrderRow(NamedTuple):
    order: OrderEvent
    alpaca_account_id: str


# Statuses Alpaca considers terminal — an order in any of these will not
# receive further trade_updates, so the reconcile sweep on SSE reconnect
# skips them. Exported for use by the trade-events handler. `replaced` is
# intentionally excluded: it terminates the old order id but the new one
# is still open under a different id.
TERMINAL_ORDER_STATUSES = frozenset(
    {"filled", "canceled", "expired", "rejected"}
)


class OrderEventRepository:

    @staticmethod
    async def create(
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        alpaca_order_id: str,
        symbol: str,
        side: str,
        order_type: str,
        status: str,
        qty: Decimal | None = None,
        notional: Decimal | None = None,
        limit_price: Decimal | None = None,
        submitted_at: datetime | None = None,
        conversation_id: uuid.UUID | None = None,
    ) -> OrderEvent:
        order = OrderEvent(
            user_id=user_id,
            alpaca_order_id=alpaca_order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            status=status,
            qty=qty,
            notional=notional,
            limit_price=limit_price,
            submitted_at=submitted_at,
            conversation_id=conversation_id,
        )
        db.add(order)
        await db.flush()
        return order

    @staticmethod
    async def get_by_id_for_user(
        db: AsyncSession, order_id: uuid.UUID, user_id: uuid.UUID
    ) -> OrderEvent | None:
        """Ownership-guarded lookup — returns None if the order belongs to a
        different user, so callers don't need a separate authorization check."""
        result = await db.execute(
            select(OrderEvent).where(
                OrderEvent.id == order_id,
                OrderEvent.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_alpaca_order_id(
        db: AsyncSession, alpaca_order_id: str
    ) -> OrderEvent | None:
        """Intentionally not user-scoped: the SSE handler receives Alpaca's
        order id from a webhook payload and has no user context until after
        the lookup."""
        result = await db.execute(
            select(OrderEvent).where(
                OrderEvent.alpaca_order_id == alpaca_order_id
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_open_with_alpaca_account_id(
        db: AsyncSession,
    ) -> list[OpenOrderRow]:
        """Return every non-terminal order joined with its owning brokerage
        account's `alpaca_account_id`, so the reconcile sweep can call
        Alpaca's per-account order endpoint without a follow-up query per
        row. Orders whose owning user has no brokerage account are excluded
        (INNER JOIN drops them)."""
        result = await db.execute(
            select(OrderEvent, BrokerageAccount.alpaca_account_id)
            .join(
                BrokerageAccount,
                BrokerageAccount.user_id == OrderEvent.user_id,
            )
            .where(OrderEvent.status.notin_(TERMINAL_ORDER_STATUSES))
        )
        return [
            OpenOrderRow(order=row[0], alpaca_account_id=row[1])
            for row in result.all()
        ]
