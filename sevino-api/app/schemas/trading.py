"""Pydantic schemas for the order-placement API.

Validation rules enforced here come from Alpaca's order constraints:
market orders accept either `qty` or `notional` (dollar amount); limit
orders require `limit_price` and a whole-share `qty` (Alpaca rejects
fractional limit orders); stop orders require `stop_price` and, like
limit orders, a whole-share `qty` (Alpaca rejects fractional and notional
stop orders).
"""

import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def time_in_force_for(order_type: str) -> str:
    """Default Sevino time-in-force convention: market → day, limit/stop → gtc.

    Lives on the schema because it's a wire-format derivation, not a
    business rule the service owns: the column isn't persisted on
    ``order_events`` (it's deterministic from ``order_type``), so the
    response schema synthesizes it whenever the row is rendered. Alpaca
    accepts whatever we send; if Alpaca ever silently coerces this
    (e.g. ``day`` → ``gtc`` for an extended-hours flag), the service
    layer logs a warning so the assumption is audited rather than
    invisible.
    """
    return "day" if order_type == "market" else "gtc"


def _parse_positive_decimal(value: str, field_name: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError):
        raise ValueError(f"{field_name} must be a valid decimal number")
    if parsed <= 0:
        raise ValueError(f"{field_name} must be positive")
    return parsed


class PlaceOrderRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=10)
    side: Literal["buy", "sell"]
    type: Literal["market", "limit", "stop"]
    qty: str | None = None
    notional: str | None = None
    limit_price: str | None = None
    stop_price: str | None = None
    conversation_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _validate_order(self) -> "PlaceOrderRequest":
        if self.qty is not None and self.notional is not None:
            raise ValueError("Provide either qty or notional, not both")
        if self.qty is None and self.notional is None:
            raise ValueError("Either qty or notional is required")

        if self.notional is not None and self.type != "market":
            raise ValueError(
                "Dollar amount orders are only supported for market orders"
            )

        if self.type == "limit" and self.limit_price is None:
            raise ValueError("Limit orders require a limit price")
        if self.type == "market" and self.limit_price is not None:
            raise ValueError("Market orders cannot have a limit price")
        if self.type == "stop" and self.limit_price is not None:
            raise ValueError("Stop orders cannot have a limit price")

        if self.type == "stop" and self.stop_price is None:
            raise ValueError("Stop orders require a stop price")
        if self.type != "stop" and self.stop_price is not None:
            raise ValueError("Only stop orders can have a stop price")

        if self.qty is not None:
            qty_decimal = _parse_positive_decimal(self.qty, "qty")
            if (
                self.type in ("limit", "stop")
                and qty_decimal != qty_decimal.to_integral_value()
            ):
                label = "Limit" if self.type == "limit" else "Stop"
                raise ValueError(
                    f"{label} orders require whole share quantities"
                )
        if self.notional is not None:
            _parse_positive_decimal(self.notional, "notional")
        if self.limit_price is not None:
            _parse_positive_decimal(self.limit_price, "limit_price")
        if self.stop_price is not None:
            _parse_positive_decimal(self.stop_price, "stop_price")

        return self


_DECIMAL_FIELDS = (
    "qty",
    "notional",
    "limit_price",
    "stop_price",
    "filled_qty",
    "filled_avg_price",
)


class PlaceOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    alpaca_order_id: str
    symbol: str
    side: str
    type: str
    time_in_force: str
    qty: str | None = None
    notional: str | None = None
    limit_price: str | None = None
    stop_price: str | None = None
    status: str
    submitted_at: datetime | None = None
    created_at: datetime

    @model_validator(mode="before")
    @classmethod
    def _coerce_order_event(cls, data: Any) -> Any:
        """Map an ``OrderEvent`` ORM instance into the response shape.

        Translates the column rename (``order_type`` → ``type``), synthesizes
        the derived ``time_in_force`` field (the column isn't persisted),
        and stringifies ``Decimal`` values for the wire so callers can use
        ``Schema.model_validate(order)`` directly instead of hand-mapping
        in the route layer.
        """
        if isinstance(data, dict) or not hasattr(data, "order_type"):
            return data

        mapped: dict[str, Any] = {
            "id": data.id,
            "alpaca_order_id": data.alpaca_order_id,
            "symbol": data.symbol,
            "side": data.side,
            "type": data.order_type,
            "time_in_force": time_in_force_for(data.order_type),
            "status": data.status,
            "submitted_at": data.submitted_at,
            "created_at": data.created_at,
        }
        for field_name in _DECIMAL_FIELDS:
            if field_name not in cls.model_fields:
                continue
            value = getattr(data, field_name, None)
            mapped[field_name] = None if value is None else str(value)
        if "filled_at" in cls.model_fields:
            mapped["filled_at"] = getattr(data, "filled_at", None)
        if "conversation_id" in cls.model_fields:
            mapped["conversation_id"] = getattr(data, "conversation_id", None)
        return mapped


class OrderDetailResponse(PlaceOrderResponse):
    filled_qty: str | None = None
    filled_avg_price: str | None = None
    filled_at: datetime | None = None
    conversation_id: uuid.UUID | None = None
