from __future__ import annotations

from datetime import time, timedelta, timezone
from decimal import Decimal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import (
    MarketDataError,
    MarketDataUnavailableError,
    MarketDataUpstreamError,
)
from app.schemas.fmp import EarningsCalendarItem
from app.services.alpaca_broker import AlpacaBrokerService
from app.services.digest.cards import UpcomingEarningsCard
from app.services.digest.context import ET
from app.services.digest.generators._common import (
    held_positions,
    holding_name,
    position_weight,
    reports_at,
)
from app.services.digest.types import CardCandidate, DigestContext
from app.services.fmp import FmpClient

logger = structlog.get_logger(__name__)


class UpcomingEarningsGenerator:
    def __init__(self, *, fmp: FmpClient) -> None:
        self._fmp = fmp

    async def generate(
        self,
        ctx: DigestContext,
        _db: AsyncSession | None = None,
        _alpaca: AlpacaBrokerService | None = None,
    ) -> list[CardCandidate]:
        positions = held_positions(ctx)
        if not positions:
            return []

        today = ctx.market_state.as_of.astimezone(ET).date()
        through = today + timedelta(days=7)
        try:
            calendar = await self._fmp.get_earnings_calendar(today, through)
        except (
            MarketDataError,
            MarketDataUnavailableError,
            MarketDataUpstreamError,
        ) as exc:
            logger.warning(
                "digest_upcoming_earnings_unavailable",
                error=str(exc),
            )
            return []

        holdings_by_symbol = {
            holding["symbol"]: holding for holding in positions
        }
        candidates: list[CardCandidate] = []
        for report in calendar:
            holding = holdings_by_symbol.get(report.symbol.upper())
            if holding is None:
                continue
            candidates.append(_candidate_for_report(ctx, holding, report))
        return candidates


def _candidate_for_report(
    ctx: DigestContext,
    holding: dict,
    report: EarningsCalendarItem,
) -> CardCandidate:
    symbol = report.symbol.upper()
    today = ctx.market_state.as_of.astimezone(ET).date()
    days_until = (report.reported_date - today).days
    related_symbols = [symbol]
    report_at = reports_at(
        report.reported_date,
        report.time,
        default_time=time(12, 0),
    ).astimezone(timezone.utc)
    card = UpcomingEarningsCard(
        symbol=symbol,
        name=holding_name(holding),
        reports_at=report_at,
        relative_label=relative_label(days_until, today=today),
        related_symbols=related_symbols,
    )
    magnitude = position_weight(ctx, holding) * (
        Decimal("1") / Decimal(max(days_until, 1))
    )
    return CardCandidate(
        card=card,
        event_type="upcoming_earnings",
        magnitude_score=float(magnitude),
        related_symbols=related_symbols,
        dedupe_key=(
            f"upcoming_earnings:{symbol}:"
            f"{report.reported_date.isoformat()}"
        ),
    )


def relative_label(days_until: int, *, today) -> str:
    if days_until == 0:
        return "Today"
    if days_until == 1:
        return "Tomorrow"
    if 2 <= days_until <= 6:
        return (today + timedelta(days=days_until)).strftime("%A")
    return f"in {days_until} days"
