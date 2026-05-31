from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import cache_get_or_set
from app.dependencies.portfolio import AlpacaAccountContext
from app.repositories.asset import AssetRepository
from app.schemas.portfolio import (
    HoldingsResponse,
    PortfolioHistoryPoint,
    PortfolioHistoryResponse,
    PortfolioSnapshotResponse,
    Position,
)
from app.services.alpaca_broker import AlpacaBrokerService

HISTORY_TTL = 60


class PortfolioRange(StrEnum):
    ONE_DAY = "1D"
    ONE_WEEK = "1W"
    ONE_MONTH = "1M"
    THREE_MONTHS = "3M"
    SIX_MONTHS = "6M"
    YTD = "YTD"
    ONE_YEAR = "1Y"
    ALL = "ALL"


def range_to_alpaca_params(
    r: PortfolioRange, *, now: datetime | None = None
) -> dict[str, str]:
    """Map the iOS-facing range to Alpaca /portfolio/history query params.

    Alpaca accepts any subset of ``{period, timeframe, start}`` and computes
    the rest. ``now`` is injectable so YTD is deterministic in tests.
    """
    now = now or datetime.now(tz=timezone.utc)
    match r:
        case PortfolioRange.ONE_DAY:
            return {"period": "1D", "timeframe": "5Min"}
        case PortfolioRange.ONE_WEEK:
            # Alpaca rejects "30Min" — valid intraday timeframes are
            # {1Min, 5Min, 15Min, 1H, 1D}. "1H" yields ~45 bars over a
            # week of regular sessions, a clean curve density for the
            # iOS chart.
            return {"period": "1W", "timeframe": "1H"}
        case PortfolioRange.ONE_MONTH:
            return {"period": "1M", "timeframe": "1D"}
        case PortfolioRange.THREE_MONTHS:
            return {"period": "3M", "timeframe": "1D"}
        case PortfolioRange.SIX_MONTHS:
            return {"period": "6M", "timeframe": "1D"}
        case PortfolioRange.YTD:
            # Alpaca silently caps the response at ~1 month from `start`
            # when `end` is omitted, so a Jan 1 query in May would only
            # return Jan 1–31 — yielding an empty chart for accounts
            # opened mid-year. Always pass an explicit `end`.
            start = f"{now.year}-01-01T00:00:00Z"
            end = now.strftime("%Y-%m-%dT%H:%M:%SZ")
            return {"timeframe": "1D", "start": start, "end": end}
        case PortfolioRange.ONE_YEAR:
            return {"period": "1A", "timeframe": "1D"}
        case PortfolioRange.ALL:
            return {"period": "all", "timeframe": "1W"}


class PortfolioService:
    """Compose Alpaca + Redis + DB into typed portfolio responses.

    Caller is expected to have passed `get_alpaca_account_context`, which
    409s on non-ACTIVE accounts — so this service trusts that
    `ctx.account_status == "ACTIVE"` on entry.
    """

    def __init__(
        self,
        alpaca: AlpacaBrokerService,
        redis: aioredis.Redis,
        db: AsyncSession,
    ):
        self._alpaca = alpaca
        self._redis = redis
        self._db = db

    async def get_snapshot(
        self, ctx: AlpacaAccountContext
    ) -> PortfolioSnapshotResponse:
        raw = await self._alpaca.get_trading_account(ctx.alpaca_account_id)
        return PortfolioSnapshotResponse.model_validate(
            _build_snapshot(raw, ctx.account_status)
        )

    async def get_holdings(
        self, ctx: AlpacaAccountContext
    ) -> HoldingsResponse:
        raw_account, raw_positions = await asyncio.gather(
            self._alpaca.get_trading_account(ctx.alpaca_account_id),
            self._alpaca.list_positions(ctx.alpaca_account_id),
        )
        symbols = [p["symbol"] for p in raw_positions]
        names = await AssetRepository.get_names_by_symbols(self._db, symbols)
        return HoldingsResponse.model_validate(
            _build_holdings(raw_account, raw_positions, names, ctx.account_status)
        )

    async def get_history(
        self,
        ctx: AlpacaAccountContext,
        r: PortfolioRange,
        *,
        now: datetime | None = None,
    ) -> PortfolioHistoryResponse:
        key = f"portfolio:history:{ctx.user_id}:{r.value}"
        params = range_to_alpaca_params(r, now=now)

        async def fetch() -> dict:
            raw = await self._alpaca.get_portfolio_history(
                ctx.alpaca_account_id, **params
            )
            return _build_history(raw, r)

        cached = await cache_get_or_set(self._redis, key, HISTORY_TTL, fetch)
        return PortfolioHistoryResponse.model_validate(cached)


def _build_snapshot(raw: dict, status: str) -> dict:
    equity = Decimal(raw.get("equity") or "0")
    last_equity = Decimal(raw.get("last_equity") or "0")
    cash = Decimal(raw.get("cash") or "0")
    buying_power = Decimal(raw.get("buying_power") or "0")
    daily_abs = equity - last_equity
    daily_pct = (
        daily_abs / last_equity if last_equity != 0 else Decimal("0")
    )
    return PortfolioSnapshotResponse(
        account_status=status,
        currency=raw.get("currency") or "USD",
        equity=equity,
        last_equity=last_equity,
        cash=cash,
        buying_power=buying_power,
        daily_change_abs=daily_abs,
        daily_change_pct=daily_pct,
    ).model_dump(mode="json")


def _build_holdings(
    raw_account: dict,
    raw_positions: list[dict],
    names: dict[str, str],
    status: str,
) -> dict:
    positions: list[Position] = []
    for p in raw_positions:
        qty = Decimal(p.get("qty") or "0")
        current_price = Decimal(p.get("current_price") or "0")
        lastday_price = Decimal(p.get("lastday_price") or "0")
        # New listings can omit lastday_price — treat as no change. Both
        # fields zero out together so the response can't surface the
        # contradictory "$0.00 (+X%)" pairing.
        if lastday_price > 0:
            change_today = (current_price - lastday_price) * qty
            change_today_percent = Decimal(p.get("change_today") or "0")
        else:
            change_today = Decimal("0")
            change_today_percent = Decimal("0")
        positions.append(
            Position(
                symbol=p["symbol"],
                name=names.get(p["symbol"], p["symbol"]),
                qty=qty,
                avg_entry_price=Decimal(p.get("avg_entry_price") or "0"),
                current_price=current_price,
                market_value=Decimal(p.get("market_value") or "0"),
                cost_basis=Decimal(p.get("cost_basis") or "0"),
                unrealized_pl=Decimal(p.get("unrealized_pl") or "0"),
                unrealized_plpc=Decimal(p.get("unrealized_plpc") or "0"),
                change_today=change_today,
                change_today_percent=change_today_percent,
            )
        )
    positions.sort(key=lambda p: p.market_value, reverse=True)
    total = sum((p.market_value for p in positions), Decimal("0"))
    return HoldingsResponse(
        account_status=status,
        currency=raw_account.get("currency") or "USD",
        cash=Decimal(raw_account.get("cash") or "0"),
        buying_power=Decimal(raw_account.get("buying_power") or "0"),
        total_market_value=total,
        positions=positions,
    ).model_dump(mode="json")


def _build_history(raw: dict, r: PortfolioRange) -> dict:
    timestamps = raw.get("timestamp") or []
    equities = raw.get("equity") or []
    points: list[PortfolioHistoryPoint] = []
    for ts, eq in zip(timestamps, equities):
        if eq is None:
            continue
        eq_d = Decimal(str(eq))
        if eq_d == 0:
            # Pre-market / no-trade bars come back as 0; drop so the chart
            # doesn't render a flat line down to zero before the open.
            continue
        points.append(PortfolioHistoryPoint(t=_to_dt(ts), v=eq_d))
    base = Decimal(str(raw.get("base_value") or "0"))
    end = points[-1].v if points else Decimal("0")
    gain_abs = end - base
    gain_pct = (gain_abs / base) if base != 0 else Decimal("0")
    return PortfolioHistoryResponse(
        range=r.value,
        timeframe=raw.get("timeframe") or "",
        currency="USD",
        base_value=base,
        end_value=end,
        gain_abs=gain_abs,
        gain_pct=gain_pct,
        points=points,
    ).model_dump(mode="json")


def _to_dt(ts: int | float) -> datetime:
    """Alpaca portfolio history timestamps come in two widths.

    Older sandbox responses return seconds (10-digit int), newer ones
    return milliseconds (13-digit int). Distinguish by magnitude: any
    value above ~10^10 must be ms (10^10 seconds is year ~2286).
    """
    ts_int = int(ts)
    if ts_int > 10_000_000_000:
        return datetime.fromtimestamp(ts_int / 1000, tz=timezone.utc)
    return datetime.fromtimestamp(ts_int, tz=timezone.utc)
