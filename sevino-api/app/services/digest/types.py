"""Internal types shared across the digest generation pipeline.

Not wire format — these are the in-process contracts the generators,
shortlist, and reranker fork on. The persisted/streamed shapes live in
``cards.py``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from app.models.user_financial_profile import UserFinancialProfile
from app.services.digest.cards import DigestCard


@dataclass(frozen=True)
class MarketState:
    """Coarse US-market session at context-build time.

    ``session`` is derived from the wall clock in ET and ignores market
    holidays — generators that need exact open/closed status should consult
    a calendar source. Good enough to frame copy ("after yesterday's
    close") in the morning digest.
    """

    as_of: datetime
    session: str  # "pre" | "open" | "post" | "closed"


@dataclass(frozen=True)
class DigestContext:
    """Everything the generators read, gathered once per user per run."""

    user_id: uuid.UUID
    portfolio_snapshot: dict[str, Any] | None
    holdings: list[dict[str, Any]]
    financial_profile: UserFinancialProfile | None
    favorited_radar_symbols: list[str]
    market_state: MarketState


@dataclass(frozen=True)
class CardCandidate:
    """A generator's proposed card plus the metadata the shortlist and
    reranker score and deduplicate on before a subset is persisted."""

    card: DigestCard
    event_type: str
    magnitude_score: float
    related_symbols: list[str] = field(default_factory=list)
    dedupe_key: str = ""


class Generator(Protocol):
    """One digest card source (dividends, big movers, earnings, ...).

    The pipeline runs every generator concurrently via ``asyncio.gather``
    and flattens their candidates before the heuristic shortlist and the
    Anthropic reranker (T11). Implementations must be read-only over the
    context and tolerate missing inputs (no brokerage account, empty
    holdings) by returning ``[]``.
    """

    async def generate(self, ctx: DigestContext) -> list[CardCandidate]: ...
