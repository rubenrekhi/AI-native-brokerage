"""`market_state` rule: surfaces prompts about the broader market.

Three sub-rules, each bucket-gated to when its question makes sense:
``big_move`` (a notable SPY day), ``sector_lead_lag`` (a held sector
diverging from SPY intraday), and ``morning_watch`` (a pre-market nudge).
The whole category is silent at night when no market data is fresh.

FMP reports a quote's day change as a percentage value (``"1.24"`` for
1.24%), so returns are divided by 100 to compare against fractional
thresholds. Held-sector detection reads ``assets.sector`` (populated by
Radar's enrichment); until that data exists, ``sector_lead_lag`` finds no
held sectors and stays silent. Magnitudes are absolute returns/spreads on
the same 0–1 scale as ``portfolio_state`` so the ranker orders coherently;
the routine morning nudge sorts last with 0.
"""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError
from app.models.asset import Asset
from app.models.radar_item import RadarItem
from app.repositories.brokerage_account import (
    STATUS_ACTIVE,
    BrokerageAccountRepository,
)
from app.schemas.shortcuts import Shortcut
from app.services.alpaca_broker import (
    AlpacaBrokerError,
    AlpacaBrokerService,
    AlpacaBrokerUnavailableError,
)
from app.services.shortcuts.rules.portfolio_state import PortfolioSnapshot
from app.services.market_data import (
    MarketDataError,
    MarketDataInvalidInputError,
    MarketDataService,
    MarketDataUnavailableError,
    MarketDataUpstreamError,
)
from app.services.shortcuts.context import ShortcutContext
from app.services.shortcuts.time_buckets import TimeBucket

logger = structlog.get_logger(__name__)

SECTOR_TO_ETF = {
    "Technology": "XLK",
    "Financial Services": "XLF",
    "Energy": "XLE",
    "Healthcare": "XLV",
    "Industrials": "XLI",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Utilities": "XLU",
    "Basic Materials": "XLB",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}

BIG_MOVE_THRESHOLD = Decimal("0.02")
SECTOR_SPREAD_THRESHOLD = Decimal("0.015")

_SPY = "SPY"

_MARKET_DATA_ERRORS = (
    MarketDataError,
    MarketDataInvalidInputError,
    MarketDataUnavailableError,
    MarketDataUpstreamError,
)
_ALPACA_ERRORS = (AlpacaBrokerError, AlpacaBrokerUnavailableError, NotFoundError)


async def evaluate(
    ctx: ShortcutContext,
    db: AsyncSession,
    alpaca: AlpacaBrokerService | None,
    market_data: MarketDataService | None,
    *,
    snapshot: PortfolioSnapshot | None = None,
) -> list[Shortcut]:
    """Emit market-aware shortcuts; empty at night or with no fresh data.

    ``snapshot`` is the portfolio snapshot from ``portfolio_state`` reused
    here to avoid a second Alpaca positions call. When provided we read
    symbols/sectors from it directly; when omitted we fall back to fetching
    via Alpaca (kept for the unit-test path that mocks Alpaca directly).
    """
    if ctx.bucket == TimeBucket.NIGHT:
        return []

    shortcuts: list[Shortcut] = []
    shortcuts += await _morning_watch(ctx, db, alpaca, snapshot=snapshot)
    shortcuts += await _big_move(ctx, market_data)
    shortcuts += await _sector_lead_lag(ctx, db, alpaca, market_data, snapshot=snapshot)
    return shortcuts


async def _big_move(
    ctx: ShortcutContext, market_data: MarketDataService | None
) -> list[Shortcut]:
    if ctx.bucket not in (TimeBucket.MARKET_HOURS, TimeBucket.AFTER_MARKET):
        return []
    quotes = await _batch_quotes(market_data, [_SPY])
    spy_return = _day_return(quotes.get(_SPY))
    if spy_return is None or abs(spy_return) < BIG_MOVE_THRESHOLD:
        return []
    direction = "up" if spy_return > 0 else "down"
    return [
        Shortcut.create(
            text=f"Why is the market {direction} today?",
            category="market_state",
            magnitude=float(abs(spy_return)),
        )
    ]


async def _sector_lead_lag(
    ctx: ShortcutContext,
    db: AsyncSession,
    alpaca: AlpacaBrokerService | None,
    market_data: MarketDataService | None,
    *,
    snapshot: PortfolioSnapshot | None = None,
) -> list[Shortcut]:
    # Intraday relative move loses meaning once the session closes.
    if ctx.bucket != TimeBucket.MARKET_HOURS:
        return []
    sectors = await _held_sectors(ctx.user_id, db, alpaca, snapshot=snapshot)
    sector_etfs = [(s, SECTOR_TO_ETF[s]) for s in sorted(sectors)]
    if not sector_etfs:
        return []

    quotes = await _batch_quotes(
        market_data, [_SPY] + [etf for _, etf in sector_etfs]
    )
    spy_return = _day_return(quotes.get(_SPY))
    if spy_return is None:
        return []

    out: list[Shortcut] = []
    for sector, etf in sector_etfs:
        etf_return = _day_return(quotes.get(etf))
        if etf_return is None:
            continue
        spread = etf_return - spy_return
        if abs(spread) < SECTOR_SPREAD_THRESHOLD:
            continue
        direction = "leading" if spread > 0 else "lagging"
        out.append(
            Shortcut.create(
                text=f"Why is {sector} {direction} today?",
                category="market_state",
                magnitude=float(abs(spread)),
            )
        )
    return out


async def _morning_watch(
    ctx: ShortcutContext,
    db: AsyncSession,
    alpaca: AlpacaBrokerService | None,
    *,
    snapshot: PortfolioSnapshot | None = None,
) -> list[Shortcut]:
    if ctx.bucket != TimeBucket.MORNING:
        return []
    if snapshot is not None:
        has_positions = bool(snapshot.positions)
    else:
        has_positions = bool(await _position_symbols(ctx.user_id, db, alpaca))
    if not has_positions and not await _has_radar_item(ctx.user_id, db):
        return []
    return [
        Shortcut.create(
            text="Anything I should watch today?",
            category="market_state",
            magnitude=0.0,
        )
    ]


async def _held_sectors(
    user_id: uuid.UUID,
    db: AsyncSession,
    alpaca: AlpacaBrokerService | None,
    *,
    snapshot: PortfolioSnapshot | None = None,
) -> set[str]:
    if snapshot is not None:
        # Sectors already attached to each Position by the shared snapshot —
        # filter to ones with a known sector ETF and we're done.
        return {p.sector for p in snapshot.positions if p.sector in SECTOR_TO_ETF}
    symbols = await _position_symbols(user_id, db, alpaca)
    if not symbols:
        return set()
    stmt = (
        select(Asset.sector)
        .where(Asset.symbol.in_(symbols), Asset.sector.in_(SECTOR_TO_ETF))
        .distinct()
    )
    return set((await db.execute(stmt)).scalars().all())


async def _position_symbols(
    user_id: uuid.UUID, db: AsyncSession, alpaca: AlpacaBrokerService | None
) -> list[str]:
    if alpaca is None:
        return []
    account = await BrokerageAccountRepository.get_by_user_id(db, user_id)
    if account is None or account.account_status != STATUS_ACTIVE:
        return []
    try:
        raw_positions = await alpaca.list_positions(account.alpaca_account_id)
    except _ALPACA_ERRORS as exc:
        logger.warning(
            "shortcuts_market_positions_failed",
            user_id=str(user_id),
            error=str(exc),
        )
        return []
    return [p["symbol"] for p in raw_positions]


async def _has_radar_item(user_id: uuid.UUID, db: AsyncSession) -> bool:
    stmt = (
        select(func.count())
        .select_from(RadarItem)
        .where(RadarItem.user_id == user_id)
    )
    return (await db.execute(stmt)).scalar_one() > 0


async def _batch_quotes(
    market_data: MarketDataService | None, symbols: list[str]
) -> dict[str, dict[str, Any]]:
    if market_data is None:
        return {}
    try:
        response = await market_data.get_batch_quotes(symbols)
    except _MARKET_DATA_ERRORS as exc:
        logger.warning(
            "shortcuts_market_quotes_failed", symbols=symbols, error=str(exc)
        )
        return {}
    return {q["symbol"]: q for q in response.get("quotes", []) if q.get("symbol")}


def _day_return(quote: dict[str, Any] | None) -> Decimal | None:
    if quote is None:
        return None
    raw = quote.get("change_percent")
    if raw is None:
        return None
    try:
        return Decimal(str(raw)) / Decimal(100)
    except (InvalidOperation, ValueError, TypeError):
        return None
