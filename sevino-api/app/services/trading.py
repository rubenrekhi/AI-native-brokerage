"""Trading orchestrator: place, cancel, and fetch orders.

Mirrors `funding.py` shape — validate locally, call Alpaca, persist row,
return. Time-in-force is derived from order type, not user-supplied: market
orders queue for the next session (`day`), limit and stop orders sit until
canceled (`gtc`).
"""

import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, NotFoundError
from app.models.asset import Asset
from app.models.brokerage_account import BrokerageAccount
from app.models.order_event import OrderEvent
from app.repositories.asset import AssetRepository
from app.repositories.brokerage_account import (
    STATUS_ACTIVE as BROKERAGE_ACCOUNT_STATUS_ACTIVE,
)
from app.repositories.brokerage_account import BrokerageAccountRepository
from app.repositories.order_event import (
    TERMINAL_ORDER_STATUSES,
    OrderEventRepository,
)
from app.schemas.trading import PlaceOrderRequest, time_in_force_for
from app.services.alpaca_broker import (
    AlpacaBrokerError,
    AlpacaBrokerService,
    AlpacaBrokerUnavailableError,
)

logger = structlog.get_logger(__name__)

__all__ = ["TradingService", "validate_trade_prerequisites", "time_in_force_for"]


class TradingService:

    @staticmethod
    async def place_order(
        db: AsyncSession,
        *,
        alpaca: AlpacaBrokerService,
        user_id: uuid.UUID,
        data: PlaceOrderRequest,
    ) -> OrderEvent:
        brokerage, asset = await validate_trade_prerequisites(
            db,
            alpaca=alpaca,
            user_id=user_id,
            symbol=data.symbol,
            side=data.side,
            qty=data.qty,
            notional=data.notional,
        )

        time_in_force = time_in_force_for(data.type)
        payload: dict[str, Any] = {
            "symbol": asset.symbol,
            "side": data.side,
            "type": data.type,
            "time_in_force": time_in_force,
            "client_order_id": str(uuid.uuid4()),
        }
        if data.qty is not None:
            payload["qty"] = data.qty
        if data.notional is not None:
            payload["notional"] = data.notional
        if data.limit_price is not None:
            payload["limit_price"] = data.limit_price
        if data.stop_price is not None:
            payload["stop_price"] = data.stop_price

        alpaca_order = await alpaca.create_order(
            brokerage.alpaca_account_id, payload
        )

        # Audit our local time-in-force convention against what Alpaca echoed.
        # Today they always agree (we send the value, Alpaca returns it
        # verbatim). If Alpaca ever silently coerces it (e.g. an extended-
        # hours flag promotes ``day`` to ``gtc``), the response schema would
        # otherwise lie about it because the column isn't persisted. Logging
        # only — the response still surfaces our computed value via
        # `time_in_force_for(order_type)`.
        echoed_tif = alpaca_order.get("time_in_force")
        if echoed_tif is not None and echoed_tif != time_in_force:
            logger.warning(
                "order_time_in_force_diverged",
                user_id=str(user_id),
                alpaca_order_id=alpaca_order.get("id"),
                requested_time_in_force=time_in_force,
                echoed_time_in_force=echoed_tif,
            )

        order_event = await OrderEventRepository.create(
            db,
            user_id=user_id,
            alpaca_order_id=alpaca_order["id"],
            symbol=alpaca_order.get("symbol", asset.symbol),
            side=alpaca_order.get("side", data.side),
            order_type=alpaca_order.get("type", data.type),
            status=alpaca_order.get("status", "accepted"),
            qty=_decimal_or_none(alpaca_order.get("qty")),
            notional=_decimal_or_none(alpaca_order.get("notional")),
            limit_price=_decimal_or_none(alpaca_order.get("limit_price")),
            stop_price=_decimal_or_none(alpaca_order.get("stop_price")),
            submitted_at=_datetime_or_none(alpaca_order.get("submitted_at")),
            conversation_id=data.conversation_id,
        )

        logger.info(
            "order_placed",
            user_id=str(user_id),
            order_id=str(order_event.id),
            alpaca_order_id=order_event.alpaca_order_id,
            symbol=order_event.symbol,
            side=order_event.side,
            order_type=order_event.order_type,
            time_in_force=time_in_force,
            status=order_event.status,
        )
        return order_event

    @staticmethod
    async def cancel_order(
        db: AsyncSession,
        *,
        alpaca: AlpacaBrokerService,
        user_id: uuid.UUID,
        order_id: uuid.UUID,
    ) -> OrderEvent:
        order = await OrderEventRepository.get_by_id_for_user(
            db, order_id, user_id
        )
        if order is None:
            raise NotFoundError("Order not found")

        if order.status in TERMINAL_ORDER_STATUSES:
            raise ConflictError(
                "This order can no longer be canceled.",
                code="ORDER_NOT_CANCELABLE",
                detail={"status": order.status},
            )

        # Cancel still goes through `_require_active_brokerage` even though
        # ownership is already proven by `get_by_id_for_user`. The check is
        # for compliance, not authorization: an account in CLOSED / SUBMITTED
        # / ACTION_REQUIRED state cannot transact (Alpaca will reject the
        # cancel request anyway), so we surface the same ACCOUNT_NOT_ACTIVE
        # error iOS already handles for placement instead of leaking a less
        # specific Alpaca rejection.
        brokerage = await _require_active_brokerage(db, user_id)

        try:
            await alpaca.cancel_order(
                brokerage.alpaca_account_id, order.alpaca_order_id
            )
        except AlpacaBrokerError as exc:
            # Alpaca returns 422 when the order has already filled / been
            # canceled in the brief window between our cancelability check
            # and the network call. Translate to the same domain error so
            # iOS handles it identically to the local terminal-status path.
            if exc.status_code == 422:
                logger.warning(
                    "order_cancel_rejected_by_alpaca",
                    user_id=str(user_id),
                    order_id=str(order.id),
                    alpaca_order_id=order.alpaca_order_id,
                    alpaca_message=exc.message,
                )
                raise ConflictError(
                    "This order can no longer be canceled.",
                    code="ORDER_NOT_CANCELABLE",
                    detail={"alpaca_message": exc.message},
                ) from exc
            # 5xx upstream is a transient outage, not a business-rule
            # rejection. Translate so the global handler returns 503 with
            # `ALPACA_UNAVAILABLE` instead of the generic 422 the
            # `AlpacaBrokerError` handler maps everything else to.
            if exc.status_code >= 500:
                logger.error(
                    "order_cancel_alpaca_unavailable",
                    user_id=str(user_id),
                    order_id=str(order.id),
                    alpaca_order_id=order.alpaca_order_id,
                    status_code=exc.status_code,
                    alpaca_message=exc.message,
                )
                raise AlpacaBrokerUnavailableError(exc.message) from exc
            raise

        order.status = "pending_cancel"
        await db.flush()
        logger.info(
            "order_cancel_requested",
            user_id=str(user_id),
            order_id=str(order.id),
            alpaca_order_id=order.alpaca_order_id,
        )
        return order

    @staticmethod
    async def get_order(
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        order_id: uuid.UUID,
    ) -> OrderEvent:
        order = await OrderEventRepository.get_by_id_for_user(
            db, order_id, user_id
        )
        if order is None:
            raise NotFoundError("Order not found")
        return order


async def validate_trade_prerequisites(
    db: AsyncSession,
    *,
    alpaca: AlpacaBrokerService,
    user_id: uuid.UUID,
    symbol: str,
    side: Literal["buy", "sell"],
    qty: str | None = None,
    notional: str | None = None,
) -> tuple[BrokerageAccount, Asset]:
    """Reusable pre-trade validation. Raises domain errors on failure.

    Checks (ordered): brokerage gate first because an inactive account
    moots downstream checks; asset existence before the position fetch
    because Alpaca returns a confusing 422 if you ask for a position on
    a delisted symbol.

    1. User has an ACTIVE brokerage account
    2. Symbol exists in the assets table and is tradeable
    3. Symbol supports the requested share granularity (whole-shares-only
       assets reject fractional qty and any notional order)
    4. For sells: user holds the symbol, and qty (if provided) doesn't
       exceed position

    Returns (brokerage, asset) on success so callers can reuse them
    without re-querying.
    """
    brokerage = await _require_active_brokerage(db, user_id)

    normalized_symbol = symbol.upper()
    asset = await AssetRepository.get_by_symbol(db, normalized_symbol)
    if asset is None:
        logger.warning(
            "order_blocked_symbol_not_tradeable",
            user_id=str(user_id),
            symbol=normalized_symbol,
        )
        raise ConflictError(
            f"{normalized_symbol} is not available for trading.",
            code="SYMBOL_NOT_TRADEABLE",
            detail={"symbol": normalized_symbol},
        )

    _require_fractionable_if_needed(
        user_id=user_id,
        asset=asset,
        qty=qty,
        notional=notional,
    )

    if side == "sell":
        await _verify_sufficient_position(
            alpaca=alpaca,
            alpaca_account_id=brokerage.alpaca_account_id,
            symbol=normalized_symbol,
            qty=qty,
        )

    return brokerage, asset


def _require_fractionable_if_needed(
    *,
    user_id: uuid.UUID,
    asset: Asset,
    qty: str | None,
    notional: str | None,
) -> None:
    # Alpaca already rejects whole-shares-only orders that ask for
    # fractional quantities, just with a slow round-trip and a generic
    # 422. Short-circuit locally so iOS can surface a sharp message
    # without the network hop.
    if asset.fractionable:
        return
    needs_fractional = notional is not None
    if not needs_fractional and qty is not None:
        # Mirrors `_verify_sufficient_position`'s defensive parse: schema
        # validates qty in the place_order flow, but the helper is reusable
        # so we keep INVALID_QTY consistent across pre-trade checks.
        try:
            qty_decimal = Decimal(qty)
        except InvalidOperation as exc:
            raise ConflictError(
                "Order quantity must be a valid decimal number.",
                code="INVALID_QTY",
                detail={"qty": qty},
            ) from exc
        needs_fractional = qty_decimal != qty_decimal.to_integral_value()
    if not needs_fractional:
        return
    logger.warning(
        "order_blocked_asset_not_fractionable",
        user_id=str(user_id),
        symbol=asset.symbol,
        qty=qty,
        notional=notional,
    )
    raise ConflictError(
        f"{asset.symbol} does not support fractional shares.",
        code="ASSET_NOT_FRACTIONABLE",
        detail={"symbol": asset.symbol},
    )


async def _verify_sufficient_position(
    *,
    alpaca: AlpacaBrokerService,
    alpaca_account_id: str,
    symbol: str,
    qty: str | None,
) -> None:
    """Pre-flight check for sell orders.

    Alpaca rejects oversells too, but with a generic 422. Surface the
    sharper INSUFFICIENT_POSITION code so iOS can render a useful
    message ("you only hold N shares") instead of "validation failed."
    Notional sells skip the qty comparison — Alpaca enforces the
    dollar-amount cap on its side.
    """
    try:
        position = await alpaca.get_position(alpaca_account_id, symbol)
    except NotFoundError as exc:
        raise ConflictError(
            f"You don't hold any shares of {symbol}.",
            code="INSUFFICIENT_POSITION",
            detail={"symbol": symbol},
        ) from exc

    if qty is None:
        return

    # `qty` is typed as `str | None` so this helper can be reused outside the
    # `place_order` flow (where the schema layer has already validated). Wrap
    # the parse defensively: a future caller that passes raw user input
    # otherwise gets an opaque 500 from `decimal.InvalidOperation`.
    try:
        requested = Decimal(qty)
    except InvalidOperation as exc:
        raise ConflictError(
            "Order quantity must be a valid decimal number.",
            code="INVALID_QTY",
            detail={"qty": qty},
        ) from exc
    held = Decimal(str(position.get("qty", "0")))
    if requested > held:
        raise ConflictError(
            f"You only hold {held} shares of {symbol}.",
            code="INSUFFICIENT_POSITION",
            detail={
                "symbol": symbol,
                "requested_qty": qty,
                "held_qty": str(held),
            },
        )


async def _require_active_brokerage(
    db: AsyncSession, user_id: uuid.UUID
) -> BrokerageAccount:
    brokerage = await BrokerageAccountRepository.get_by_user_id(db, user_id)
    account_status = brokerage.account_status if brokerage else None
    if account_status != BROKERAGE_ACCOUNT_STATUS_ACTIVE:
        logger.warning(
            "trading_blocked_account_not_active",
            user_id=str(user_id),
            account_status=account_status,
        )
        raise ConflictError(
            "Your brokerage account is not active yet.",
            code="ACCOUNT_NOT_ACTIVE",
            detail={"account_status": account_status},
        )
    return brokerage


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _datetime_or_none(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
