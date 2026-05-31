"""DigestCard schemas — the discriminated union persisted to
``digest_snapshots.cards`` (JSONB) and streamed to iOS.

Mirrors the iOS ``enum DigestCard`` keyed on ``kind`` (see CLAUDE.md
"AI wire format"). There is no codegen: adding or changing a variant here
means hand-updating the Swift mirror in the same PR. Every money / quantity
/ percentage field uses the ``MoneyStr`` / ``QtyStr`` / ``PctStr`` aliases
so it serialises as a JSON string and shares ``Decimal`` semantics with iOS.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, TypeAdapter

from app.schemas._types import MoneyStr, PctStr, QtyStr


class DigestCardBase(BaseModel):
    """Fields every variant carries, independent of ``kind``.

    ``card_context`` is an opaque per-card bag the chat dock reads when the
    user taps into a card (§20.6) — the reranker and renderers don't
    interpret it, so it stays a free-form dict on the wire.
    """

    id: UUID = Field(default_factory=uuid4)
    priority: int = 0
    related_symbols: list[str] = Field(default_factory=list)
    card_context: dict = Field(default_factory=dict)


class DividendPayment(BaseModel):
    symbol: str
    amount: MoneyStr
    paid_at: datetime


class OrderActivityItem(BaseModel):
    symbol: str
    name: str | None = None
    side: Literal["buy", "sell"] | None = None
    qty: QtyStr | None = None
    notional: MoneyStr | None = None


class DividendsCard(DigestCardBase):
    kind: Literal["dividends"] = "dividends"
    payments: list[DividendPayment] = Field(default_factory=list)
    total_amount: MoneyStr
    period_label: str


class PendingOrderActivityCard(DigestCardBase):
    kind: Literal["pending_order_activity"] = "pending_order_activity"
    filled: list[OrderActivityItem] = Field(default_factory=list)
    recurring_executed: list[OrderActivityItem] = Field(default_factory=list)
    recurring_skipped: list[OrderActivityItem] = Field(default_factory=list)


class BigMoveCard(DigestCardBase):
    kind: Literal["big_move"] = "big_move"
    symbol: str
    name: str
    prev_close: MoneyStr
    current: MoneyStr
    change_abs: MoneyStr
    change_pct: PctStr
    reason: str | None = None


class WatchlistMoveCard(DigestCardBase):
    # Same payload as big_move, sourced from the user's favorited radar
    # symbols rather than their holdings — the distinct ``kind`` lets iOS
    # render the "from your watchlist" framing.
    kind: Literal["watchlist_move"] = "watchlist_move"
    symbol: str
    name: str
    prev_close: MoneyStr
    current: MoneyStr
    change_abs: MoneyStr
    change_pct: PctStr
    reason: str | None = None


class MarketContextCard(DigestCardBase):
    kind: Literal["market_context"] = "market_context"
    direction: Literal["up", "down", "mixed"]
    sp500_change_pct: PctStr
    nasdaq_change_pct: PctStr
    summary: str


class RadarRefreshCard(DigestCardBase):
    kind: Literal["radar_refresh"] = "radar_refresh"
    refreshed_at: datetime
    new_count: int
    removed_count: int


class EarningsResultCard(DigestCardBase):
    kind: Literal["earnings_result"] = "earnings_result"
    symbol: str
    name: str
    grade: str
    eps_actual: MoneyStr | None = None
    eps_estimate: MoneyStr | None = None
    rev_actual: MoneyStr | None = None
    rev_estimate: MoneyStr | None = None
    stock_reaction_pct: PctStr | None = None
    beat_miss_highlights: list[str] = Field(default_factory=list)


class UpcomingEarningsCard(DigestCardBase):
    kind: Literal["upcoming_earnings"] = "upcoming_earnings"
    symbol: str
    name: str
    reports_at: datetime
    relative_label: str


class NewsCard(DigestCardBase):
    kind: Literal["news"] = "news"
    symbol: str | None = None
    headline: str
    source: str
    url: str
    published_at: datetime
    summary: str


_CardUnion = (
    DividendsCard
    | PendingOrderActivityCard
    | BigMoveCard
    | WatchlistMoveCard
    | MarketContextCard
    | RadarRefreshCard
    | EarningsResultCard
    | UpcomingEarningsCard
    | NewsCard
)

DigestCard = Annotated[_CardUnion, Field(discriminator="kind")]


DigestCardAdapter: TypeAdapter[_CardUnion] = TypeAdapter(DigestCard)
DigestCardListAdapter: TypeAdapter[list[_CardUnion]] = TypeAdapter(
    list[DigestCard]
)
