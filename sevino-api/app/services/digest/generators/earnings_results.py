from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import (
    MarketDataError,
    MarketDataUnavailableError,
    MarketDataUpstreamError,
)
from app.schemas.fmp import HistoricalEarningsItem
from app.services.alpaca_broker import AlpacaBrokerService
from app.services.digest.cards import EarningsResultCard
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

INLINE_THRESHOLD = Decimal("0.005")
SOLID_BEAT_THRESHOLD = Decimal("0.02")
STRONG_BEAT_THRESHOLD = Decimal("0.05")
DEFAULT_REACTION_FLOOR = Decimal("0.05")


class EarningsResultsGenerator:
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

        results = await asyncio.gather(
            *(self._candidate_for_holding(ctx, holding) for holding in positions)
        )
        return [candidate for candidate in results if candidate is not None]

    async def _candidate_for_holding(
        self, ctx: DigestContext, holding: dict
    ) -> CardCandidate | None:
        symbol = holding["symbol"]
        try:
            rows = await self._fmp.get_historical_earnings(symbol, limit=1)
        except (
            MarketDataError,
            MarketDataUnavailableError,
            MarketDataUpstreamError,
        ) as exc:
            logger.warning(
                "digest_earnings_results_unavailable",
                symbol=symbol,
                error=str(exc),
            )
            return None

        if not rows:
            return None
        earnings = rows[0]
        if not _reported_since_prior_close(earnings, ctx.market_state.as_of):
            return None

        grade = grade_earnings(earnings)
        if grade is None:
            return None

        related_symbols = [symbol]
        card = EarningsResultCard(
            symbol=symbol,
            name=holding_name(holding),
            grade=grade.grade,
            eps_actual=earnings.eps_actual,
            eps_estimate=earnings.eps_estimate,
            rev_actual=earnings.revenue_actual,
            rev_estimate=earnings.revenue_estimate,
            stock_reaction_pct=None,
            beat_miss_highlights=grade.highlights,
            related_symbols=related_symbols,
        )
        weight = position_weight(ctx, holding)
        magnitude = weight * DEFAULT_REACTION_FLOOR
        return CardCandidate(
            card=card,
            event_type="earnings_result",
            magnitude_score=float(magnitude),
            related_symbols=related_symbols,
            dedupe_key=(
                f"earnings_result:{symbol}:"
                f"{earnings.reported_date.isoformat()}"
            ),
        )


@dataclass(frozen=True)
class EarningsGrade:
    grade: str
    highlights: list[str]


@dataclass(frozen=True)
class _MetricResult:
    label: str
    pct_diff: Decimal
    bucket: str


def grade_earnings(
    earnings: HistoricalEarningsItem,
) -> EarningsGrade | None:
    eps = _metric_result(
        "EPS", earnings.eps_actual, earnings.eps_estimate
    )
    revenue = _metric_result(
        "Revenue", earnings.revenue_actual, earnings.revenue_estimate
    )
    if eps is None or revenue is None:
        return None

    metrics = [eps, revenue]
    beat_count = sum(metric.bucket == "beat" for metric in metrics)
    inline_count = sum(metric.bucket == "inline" for metric in metrics)
    miss_count = sum(metric.bucket == "miss" for metric in metrics)

    if miss_count == 2:
        grade = "F"
    elif miss_count == 1:
        grade = "D"
    elif inline_count == 2:
        grade = "C"
    elif beat_count == 1 and inline_count == 1:
        grade = "B"
    elif all(metric.pct_diff > STRONG_BEAT_THRESHOLD for metric in metrics):
        grade = "A+"
    elif all(metric.pct_diff >= SOLID_BEAT_THRESHOLD for metric in metrics):
        grade = "A"
    else:
        grade = "A-"

    return EarningsGrade(
        grade=grade,
        highlights=[_highlight(metric) for metric in metrics],
    )


def _metric_result(
    label: str, actual: Decimal | None, estimate: Decimal | None
) -> _MetricResult | None:
    if actual is None or estimate is None or estimate == 0:
        return None
    pct_diff = (actual - estimate) / abs(estimate)
    if pct_diff > INLINE_THRESHOLD:
        bucket = "beat"
    elif pct_diff < -INLINE_THRESHOLD:
        bucket = "miss"
    else:
        bucket = "inline"
    return _MetricResult(label=label, pct_diff=pct_diff, bucket=bucket)


def _highlight(metric: _MetricResult) -> str:
    if metric.bucket == "inline":
        return f"{metric.label} inline with estimate"
    verb = "beat" if metric.bucket == "beat" else "missed"
    return f"{metric.label} {verb} by {_format_pct(abs(metric.pct_diff))}"


def _format_pct(value: Decimal) -> str:
    return f"{(value * Decimal('100')).quantize(Decimal('0.1')):.1f}%"


def _reported_since_prior_close(
    earnings: HistoricalEarningsItem, now_utc: datetime
) -> bool:
    now_et = _aware_utc(now_utc).astimezone(ET)
    report_dt = reports_at(
        earnings.reported_date,
        earnings.time,
        default_time=time(16, 0),
    )
    return _prior_close(now_et) <= report_dt <= now_et


def _prior_close(now_et: datetime) -> datetime:
    close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    if now_et.weekday() < 5 and now_et >= close:
        return close

    day = now_et.date() - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return datetime.combine(day, time(16, 0), tzinfo=ET)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
