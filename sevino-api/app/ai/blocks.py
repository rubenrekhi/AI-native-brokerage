"""Discriminated-union schemas for assistant UI blocks.

Per AI v0 plan B1.1 / C1.3 (sevino-api/docs/ai-v0-plan.md). The agent loop
streams blocks via SSE and persists the final list to ``messages.content_blocks``
JSONB; the wire format mirrors the iOS ``enum Block`` so both ends round-trip
identically. Adding a variant is just a new subclass plus an entry in the
union below.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter


class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    block_id: str
    text: str


class StatusBlock(BaseModel):
    type: Literal["status"] = "status"
    block_id: str
    label: str
    state: Literal["active", "complete", "failed"]


class Bar(BaseModel):
    """One price point inside a :class:`StockCardBlock` chart payload.

    Minimal ``{t, c}`` shape — just enough to render the v0 sparkline. Raw
    Alpaca OHLCV is preserved on ``tool_executions.internal_trace``; if iOS
    later wants candlesticks or volume bars, that's a schema bump.
    """

    t: str  # ISO 8601 timestamp
    c: float  # close price


class StockCardBlock(BaseModel):
    type: Literal["stock_card"] = "stock_card"
    block_id: str
    symbol: str
    company_name: str
    logo_url: str | None = None
    price: float
    change_abs: float
    change_pct: float
    color_state: Literal["positive", "negative", "neutral"]
    bars: list[Bar]
    range: str
    range_options: list[str]


Block = Annotated[
    TextBlock | StatusBlock | StockCardBlock, Field(discriminator="type")
]


# Module-level adapters so callers don't rebuild a TypeAdapter per validation.
# ``BlockAdapter`` validates a single block dict; ``BlockListAdapter`` validates
# the full ``messages.content_blocks`` shape.
BlockAdapter: TypeAdapter[TextBlock | StatusBlock | StockCardBlock] = TypeAdapter(
    Block
)
BlockListAdapter: TypeAdapter[
    list[TextBlock | StatusBlock | StockCardBlock]
] = TypeAdapter(list[Block])
