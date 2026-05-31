"""Overnight and pre-market move detection for digest generators."""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import sentry_sdk
import structlog

from app.exceptions import MarketDataUnavailableError, MarketDataUpstreamError

logger = structlog.get_logger(__name__)

ET = ZoneInfo("America/New_York")

HOLDING_MOVE_PCT = Decimal("0.02")
WATCHLIST_MOVE_PCT = Decimal("0.03")
INDEX_MOVE_PCT = Decimal("0.0075")
BEGINNER_MOVE_PCT = Decimal("0.01")

_DAILY_LOOKBACK = timedelta(days=10)
_ZERO = Decimal("0")
_SENTRY_FAILURE_RATE = Decimal("0.25")


@dataclass(frozen=True)
class MoveData:
    prev_close: Decimal
    current: Decimal
    change_abs: Decimal
    change_pct: Decimal
    has_premarket_activity: bool


class StockBarsProvider(Protocol):
    async def get_stock_bars(
        self,
        symbol: str,
        *,
        timeframe: str,
        start: datetime,
        end: datetime | None = None,
        limit: int = 10000,
    ) -> Sequence[Mapping[str, Any]]:
        ...


_BarsCacheKey = tuple[str, str, datetime, datetime | None, int]


class RunScopedStockBarsProvider:
    """Deduplicate identical bar fetches during one digest generation run."""

    def __init__(self, inner: StockBarsProvider) -> None:
        self._inner = inner
        self._tasks: dict[
            _BarsCacheKey, asyncio.Task[Sequence[Mapping[str, Any]]]
        ] = {}

    async def get_stock_bars(
        self,
        symbol: str,
        *,
        timeframe: str,
        start: datetime,
        end: datetime | None = None,
        limit: int = 10000,
    ) -> Sequence[Mapping[str, Any]]:
        key = (_normalize_symbol(symbol), timeframe, start, end, limit)
        task = self._tasks.get(key)
        if task is None:
            task = asyncio.create_task(
                self._inner.get_stock_bars(
                    symbol,
                    timeframe=timeframe,
                    start=start,
                    end=end,
                    limit=limit,
                )
            )
            self._tasks[key] = task
        return await task


@dataclass(frozen=True)
class _DetectionResult:
    symbol: str
    move: MoveData
    failure_stage: str | None = None
    error_type: str | None = None


async def detect_overnight_moves(
    symbols: list[str], market_data: StockBarsProvider, *, now: datetime | None = None
) -> dict[str, MoveData]:
    """Return overnight/pre-market moves keyed by normalized symbol.

    The helper compares the latest completed daily close with the latest
    1-minute bar after that close. If there are no bars in the overnight
    window, the symbol is still returned with ``current == prev_close`` and
    ``has_premarket_activity=False``.
    """
    now_utc = _as_utc(now or datetime.now(timezone.utc))
    normalized = [_normalize_symbol(symbol) for symbol in symbols]
    results = await asyncio.gather(
        *(_detect_symbol(symbol, market_data, now_utc) for symbol in normalized)
    )
    moves = {result.symbol: result.move for result in results}
    failure_count = sum(1 for result in results if result.failure_stage is not None)
    move_count = sum(
        1
        for move in moves.values()
        if move.has_premarket_activity and move.change_pct != 0
    )
    logger.info(
        "digest_move_detection_complete",
        symbol_count=len(normalized),
        move_count=move_count,
        failure_count=failure_count,
    )
    _capture_batch_failures(results)
    return moves


def is_meaningful_move(move: MoveData, threshold: Decimal) -> bool:
    return move.has_premarket_activity and abs(move.change_pct) >= threshold


async def _detect_symbol(
    symbol: str, market_data: StockBarsProvider, now_utc: datetime
) -> _DetectionResult:
    try:
        daily_bars = await _fetch_bars(
            market_data,
            symbol,
            timeframe="1Day",
            start=now_utc - _DAILY_LOOKBACK,
            end=now_utc,
            limit=10,
        )
        prev_bar = _latest_completed_daily_bar(daily_bars, now_utc)
    except (MarketDataUnavailableError, MarketDataUpstreamError) as exc:
        logger.warning(
            "digest_move_detection_fetch_failed",
            symbol=symbol,
            stage="daily",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return _DetectionResult(
            symbol=symbol,
            move=_empty_move(),
            failure_stage="daily",
            error_type=type(exc).__name__,
        )

    if prev_bar is None:
        return _DetectionResult(symbol=symbol, move=_empty_move())

    prev_close = _bar_close(prev_bar)
    if prev_close is None or prev_close <= _ZERO:
        return _DetectionResult(symbol=symbol, move=_empty_move())

    try:
        window_start = _regular_close_utc(_bar_session_date(prev_bar, now_utc))
        minute_bars = await _fetch_bars(
            market_data,
            symbol,
            timeframe="1Min",
            start=window_start,
            end=now_utc,
            limit=10000,
        )
    except (MarketDataUnavailableError, MarketDataUpstreamError) as exc:
        logger.warning(
            "digest_move_detection_fetch_failed",
            symbol=symbol,
            stage="intraday",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return _DetectionResult(
            symbol=symbol,
            move=_flat_move(prev_close),
            failure_stage="intraday",
            error_type=type(exc).__name__,
        )

    latest = _latest_bar_with_close(minute_bars)
    if latest is None:
        return _DetectionResult(symbol=symbol, move=_flat_move(prev_close))

    current = _bar_close(latest)
    if current is None:
        return _DetectionResult(symbol=symbol, move=_flat_move(prev_close))

    change_abs = current - prev_close
    change_pct = change_abs / prev_close
    return _DetectionResult(
        symbol=symbol,
        move=MoveData(
            prev_close=prev_close,
            current=current,
            change_abs=change_abs,
            change_pct=change_pct,
            has_premarket_activity=True,
        ),
    )


async def _fetch_bars(
    market_data: StockBarsProvider,
    symbol: str,
    *,
    timeframe: str,
    start: datetime,
    end: datetime,
    limit: int,
) -> list[Mapping[str, Any]]:
    result = await market_data.get_stock_bars(
        symbol,
        timeframe=timeframe,
        start=start,
        end=end,
        limit=limit,
    )
    return _coerce_bars(result)


def _capture_batch_failures(results: Sequence[_DetectionResult]) -> None:
    failure_results = [result for result in results if result.failure_stage is not None]
    if not failure_results:
        return

    failure_count = len(failure_results)
    failure_rate = Decimal(failure_count) / Decimal(len(results))
    if failure_rate < _SENTRY_FAILURE_RATE:
        return

    stage_counts = Counter(result.failure_stage for result in failure_results)
    error_counts = Counter(result.error_type for result in failure_results)
    with sentry_sdk.new_scope() as scope:
        scope.set_tag("digest_component", "move_detection")
        scope.set_tag("alert_type", "digest_move_detection_failures")
        scope.set_tag("symbol_count", str(len(results)))
        scope.set_tag("failure_count", str(failure_count))
        scope.set_context(
            "digest_move_detection",
            {
                "symbol_count": len(results),
                "failure_count": failure_count,
                "failure_rate": str(failure_rate),
                "stage_counts": dict(stage_counts),
                "error_counts": dict(error_counts),
                "symbols": [result.symbol for result in failure_results[:25]],
            },
        )
        sentry_sdk.capture_message(
            "digest_move_detection_failures",
            level="warning",
        )


def _coerce_bars(result: Any) -> list[Mapping[str, Any]]:
    if result is None:
        return []
    if isinstance(result, Mapping):
        for key in ("bars", "data"):
            bars = result.get(key)
            if isinstance(bars, Sequence) and not isinstance(bars, (str, bytes)):
                return [bar for bar in bars if isinstance(bar, Mapping)]
        return []
    bars_attr = getattr(result, "bars", None)
    if isinstance(bars_attr, Mapping):
        flattened: list[Mapping[str, Any]] = []
        for bars in bars_attr.values():
            if isinstance(bars, Sequence):
                flattened.extend(bar for bar in bars if isinstance(bar, Mapping))
        return flattened
    if isinstance(result, Sequence) and not isinstance(result, (str, bytes)):
        return [bar for bar in result if isinstance(bar, Mapping)]
    return []


def _latest_completed_daily_bar(
    bars: Sequence[Mapping[str, Any]], now_utc: datetime
) -> Mapping[str, Any] | None:
    today_et = now_utc.astimezone(ET).date()
    completed = [bar for bar in bars if _bar_session_date(bar, now_utc) < today_et]
    return _latest_bar_with_close(completed or bars)


def _latest_bar_with_close(
    bars: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    valid = [bar for bar in bars if _bar_close(bar) is not None]
    if not valid:
        return None
    return max(valid, key=_bar_timestamp_sort_key)


def _bar_close(bar: Mapping[str, Any]) -> Decimal | None:
    raw = bar.get("c", bar.get("close"))
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None


def _bar_session_date(bar: Mapping[str, Any], fallback: datetime) -> date:
    timestamp = _parse_bar_timestamp(bar)
    if timestamp is None:
        return fallback.astimezone(ET).date()
    return timestamp.astimezone(ET).date()


def _bar_timestamp_sort_key(bar: Mapping[str, Any]) -> datetime:
    return _parse_bar_timestamp(bar) or datetime.min.replace(tzinfo=timezone.utc)


def _parse_bar_timestamp(bar: Mapping[str, Any]) -> datetime | None:
    raw = bar.get("t", bar.get("timestamp"))
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return _as_utc(raw)
    if isinstance(raw, date):
        return datetime.combine(raw, time.min, tzinfo=ET).astimezone(timezone.utc)
    if isinstance(raw, str):
        if len(raw) == 10:
            try:
                parsed_date = date.fromisoformat(raw)
            except ValueError:
                return None
            return datetime.combine(parsed_date, time.min, tzinfo=ET).astimezone(
                timezone.utc
            )
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed_date = date.fromisoformat(raw)
            except ValueError:
                return None
            return datetime.combine(parsed_date, time.min, tzinfo=ET).astimezone(
                timezone.utc
            )
        return _as_utc(parsed)
    return None


def _regular_close_utc(session_date: date) -> datetime:
    return datetime.combine(session_date, time(16, 0), tzinfo=ET).astimezone(
        timezone.utc
    )


def _normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _empty_move() -> MoveData:
    return MoveData(
        prev_close=_ZERO,
        current=_ZERO,
        change_abs=_ZERO,
        change_pct=_ZERO,
        has_premarket_activity=False,
    )


def _flat_move(prev_close: Decimal) -> MoveData:
    return MoveData(
        prev_close=prev_close,
        current=prev_close,
        change_abs=_ZERO,
        change_pct=_ZERO,
        has_premarket_activity=False,
    )
