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
    PortfolioSnapshotResponse,
    Position,
)
from app.services.alpaca_broker import AlpacaBrokerService

SNAPSHOT_TTL = 30
HOLDINGS_TTL = 30


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
            return {"period": "1W", "timeframe": "30Min"}
        case PortfolioRange.ONE_MONTH:
            return {"period": "1M", "timeframe": "1D"}
        case PortfolioRange.THREE_MONTHS:
            return {"period": "3M", "timeframe": "1D"}
        case PortfolioRange.SIX_MONTHS:
            return {"period": "6M", "timeframe": "1D"}
        case PortfolioRange.YTD:
            start = f"{now.year}-01-01T00:00:00Z"
            return {"timeframe": "1D", "start": start}
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
        key = f"portfolio:snapshot:{ctx.user_id}"

        async def fetch() -> dict:
            raw = await self._alpaca.get_trading_account(ctx.alpaca_account_id)
            return _build_snapshot(raw, ctx.account_status)

        cached = await cache_get_or_set(self._redis, key, SNAPSHOT_TTL, fetch)
        return PortfolioSnapshotResponse.model_validate(cached)

    async def get_holdings(
        self, ctx: AlpacaAccountContext
    ) -> HoldingsResponse:
        key = f"portfolio:holdings:{ctx.user_id}"

        async def fetch() -> dict:
            raw_account, raw_positions = await asyncio.gather(
                self._alpaca.get_trading_account(ctx.alpaca_account_id),
                self._alpaca.get_positions(ctx.alpaca_account_id),
            )
            symbols = [p["symbol"] for p in raw_positions]
            names = await AssetRepository.get_names_by_symbols(self._db, symbols)
            return _build_holdings(raw_account, raw_positions, names, ctx.account_status)

        cached = await cache_get_or_set(self._redis, key, HOLDINGS_TTL, fetch)
        return HoldingsResponse.model_validate(cached)


def _build_snapshot(raw: dict, status: str) -> dict:
    equity = Decimal(raw.get("equity") or "0")
    last_equity = Decimal(raw.get("last_equity") or "0")
    cash = Decimal(raw.get("cash") or "0")
    buying_power = Decimal(raw.get("buying_power") or "0")
    daily_abs = equity - last_equity
    daily_pct = (
        daily_abs / last_equity if last_equity != 0 else Decimal("0")
    )
    # Cache the JSON-ready dict so cache hits + misses produce the same shape.
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
    positions = [
        Position(
            symbol=p["symbol"],
            name=names.get(p["symbol"], p["symbol"]),
            qty=Decimal(p.get("qty") or "0"),
            avg_entry_price=Decimal(p.get("avg_entry_price") or "0"),
            current_price=Decimal(p.get("current_price") or "0"),
            market_value=Decimal(p.get("market_value") or "0"),
            cost_basis=Decimal(p.get("cost_basis") or "0"),
            unrealized_pl=Decimal(p.get("unrealized_pl") or "0"),
            unrealized_plpc=Decimal(p.get("unrealized_plpc") or "0"),
        )
        for p in raw_positions
    ]
    positions.sort(key=lambda p: p.market_value, reverse=True)
    total = sum((p.market_value for p in positions), Decimal("0"))
    return HoldingsResponse(
        account_status=status,
        currency=raw_account.get("currency") or "USD",
        cash=Decimal(raw_account.get("cash") or "0"),
        total_market_value=total,
        positions=positions,
    ).model_dump(mode="json")
