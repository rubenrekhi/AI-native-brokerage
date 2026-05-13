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


class RangeBars(BaseModel):
    """Per-range chart data for a :class:`StockCardBlock`.

    Encoded as a list of ``{range, bars, change_abs, change_pct}``
    records rather than a ``{range: ...}`` dict so literal range
    labels like ``"1D"`` aren't subject to Swift's
    ``JSONEncoder.convertToSnakeCase`` mangling on the wire.

    Each entry carries its own change values so the iOS card can read
    the right number when the user slides the range selector — no
    FE-side derivation. The tool is the single source of truth.

    * For ``"1D"``, ``change_abs`` / ``change_pct`` are the
      authoritative daily change vs *yesterday's close* (from the
      FMP quote). Bars start at today's market open, which would
      give a misleading "change since open" if the FE just diffed
      first-bar to current price.
    * For longer ranges, ``change_abs`` is ``current_price -
      first_bar.close`` — current vs roughly N-time-ago's close.
    """

    range: str
    bars: list[Bar]
    change_abs: float
    change_pct: float


class StockStats(BaseModel):
    """Optional valuation/technical stats shown on an expanded card.

    Every field is optional — FMP doesn't always return every value, and
    iOS only renders rows for fields that arrive non-null. Money/quantity
    values are sent as raw decimal strings (or ints for counts) per the
    decimal-on-the-wire convention; iOS formats them at the view layer.
    """

    open: str | None = None
    day_high: str | None = None
    day_low: str | None = None
    previous_close: str | None = None
    year_high: str | None = None
    year_low: str | None = None
    volume: int | None = None
    avg_volume: int | None = None
    market_cap: int | None = None
    pe_ratio: str | None = None
    eps: str | None = None
    beta: str | None = None
    dividend_yield: str | None = None
    exchange: str | None = None


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
    # Bars for the initial ``range`` shown when the card first lands.
    # Mirrored into ``bars_by_range`` under that range's key so iOS's
    # ``bars(for:)`` resolver can return them through one code path.
    bars: list[Bar]
    # Optional: pre-fetched bars for every range option, indexed by
    # ``range_options`` label. When populated, the iOS card swaps chart
    # data client-side as the user slides the range selector — zero
    # network on slide. When ``None`` or missing a requested range,
    # iOS falls back to ``bars``.
    bars_by_range: list[RangeBars] | None = None
    range: str
    range_options: list[str]
    # Optional: expanded stats grid (bid/ask/52w/market cap/etc.). When
    # populated, iOS renders the grid below the chart. When ``None``,
    # the card shows the compact layout.
    stats: StockStats | None = None


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
