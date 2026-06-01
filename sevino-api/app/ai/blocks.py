"""Block schemas streamed via SSE and persisted to ``messages.content_blocks``.

Mirrors the iOS ``enum Block``. Persisted user-attachment context blocks
(input-only, never streamed, never replayed) live in ``app.ai.context_blocks``
— not in this ``Block`` union (see SEV-615).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter

from app.schemas.recurring_investment import (
    RecurringEndCondition,
    RecurringFrequency,
)


class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    block_id: str
    text: str


class StatusBlock(BaseModel):
    type: Literal["status"] = "status"
    block_id: str
    label: str
    state: Literal["active", "complete", "failed"]


class ThinkingBlock(BaseModel):
    # ``redacted=True`` is Anthropic's encrypted ``redacted_thinking`` variant.
    # Not persisted to content_blocks — reopening the conversation loses these.
    type: Literal["thinking"] = "thinking"
    block_id: str
    text: str = ""
    redacted: bool = False
    state: Literal["streaming", "complete"] = "streaming"


class Bar(BaseModel):
    t: str  # ISO 8601 timestamp
    c: float  # close price


class RangeBars(BaseModel):
    # List, not dict, so range labels like "1D" survive Swift's
    # convertToSnakeCase. "1D" change is vs yesterday's close (from FMP
    # quote); longer ranges are price - first_bar.close.
    range: str
    bars: list[Bar]
    change_abs: float
    change_pct: float


class StockStats(BaseModel):
    # FMP returns missing values as 0/""; iOS skips None rows.
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
    bars: list[Bar]
    bars_by_range: list[RangeBars] | None = None
    range: str
    range_options: list[str]
    stats: StockStats | None = None


class RecurringInvestmentSetupBlock(BaseModel):
    type: Literal["recurring_investment_setup"] = "recurring_investment_setup"
    block_id: str
    ticker: str
    company_name: str
    exchange: str
    current_price: str
    default_amount: str
    default_frequency: RecurringFrequency
    default_start_date: str
    default_end_condition: RecurringEndCondition
    disclaimer: str


Block = Annotated[
    TextBlock
    | StatusBlock
    | StockCardBlock
    | ThinkingBlock
    | RecurringInvestmentSetupBlock,
    Field(discriminator="type"),
]


BlockAdapter: TypeAdapter[
    TextBlock
    | StatusBlock
    | StockCardBlock
    | ThinkingBlock
    | RecurringInvestmentSetupBlock
] = TypeAdapter(Block)
BlockListAdapter: TypeAdapter[
    list[
        TextBlock
        | StatusBlock
        | StockCardBlock
        | ThinkingBlock
        | RecurringInvestmentSetupBlock
    ]
] = TypeAdapter(list[Block])
