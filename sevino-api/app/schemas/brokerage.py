from pydantic import BaseModel, ConfigDict


class OrderResponse(BaseModel):
    """Subset of an Alpaca order projected for the iOS trade-history UI.

    Alpaca returns ~30 fields per order; we expose only what the UI renders.
    Status is passed through raw (e.g. `filled`, `partially_filled`, `new`,
    `canceled`, `rejected`) — the client buckets these into pending /
    completed / failed pills.
    """

    model_config = ConfigDict(extra="ignore")

    id: str
    client_order_id: str | None = None
    symbol: str
    asset_class: str | None = None
    side: str
    order_type: str | None = None
    time_in_force: str | None = None
    qty: str | None = None
    notional: str | None = None
    filled_qty: str | None = None
    filled_avg_price: str | None = None
    limit_price: str | None = None
    stop_price: str | None = None
    status: str
    submitted_at: str | None = None
    filled_at: str | None = None
    canceled_at: str | None = None
    expired_at: str | None = None
    failed_at: str | None = None
    created_at: str | None = None


class OrderListResponse(BaseModel):
    orders: list[OrderResponse]


class PositionResponse(BaseModel):
    """Open position projected for the holdings filter on the trade-history UI."""

    model_config = ConfigDict(extra="ignore")

    symbol: str
    asset_class: str | None = None
    qty: str | None = None
    market_value: str | None = None


class PositionListResponse(BaseModel):
    positions: list[PositionResponse]
