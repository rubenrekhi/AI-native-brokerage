"""`portfolio_state` rule: surfaces prompts about the user's live holdings.

Four sub-rules fire independently off one Alpaca snapshot — an
over-concentrated position, a dominant sector, idle cash, and an
end-of-day recap. Each carries a ``magnitude`` on a comparable 0–1 scale
(a position/sector/cash share of the portfolio) so the ranker can order
the whole category coherently; the routine recap sorts last with 0.
Positions come straight from Alpaca (no DB cache); sector
labels are read from ``assets.sector`` (populated by Radar's enrichment),
so allocation_drift degrades to silence until that data exists.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError
from app.models.asset import Asset
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
from app.services.shortcuts.context import ShortcutContext
from app.services.shortcuts.time_buckets import TimeBucket

logger = structlog.get_logger(__name__)

# Floor that gates concentration + allocation_drift so a $4 test portfolio
# can't trip "Is having 100% in NVDA too much?".
PORTFOLIO_FLOOR = Decimal("500")
CONCENTRATION_THRESHOLD = Decimal("0.25")
SECTOR_THRESHOLD = Decimal("0.40")
MIN_IDLE_CASH = Decimal("500")
IDLE_CASH_RATIO = Decimal("0.20")


@dataclass(frozen=True)
class Position:
    symbol: str
    market_value: Decimal
    sector: str | None


@dataclass(frozen=True)
class PortfolioSnapshot:
    total_value: Decimal
    cash: Decimal
    positions: list[Position]


async def evaluate(
    ctx: ShortcutContext,
    db: AsyncSession,
    alpaca: AlpacaBrokerService | None,
    *,
    snapshot: "PortfolioSnapshot | None" = None,
) -> list[Shortcut]:
    """Emit holdings-aware shortcuts; empty if there's no live snapshot.

    ``snapshot`` may be pre-fetched by the orchestrator and reused across
    multiple rule modules so we don't hit Alpaca's positions endpoint
    twice per request. When omitted, we fetch our own.
    """
    if snapshot is None:
        snapshot = await gather_snapshot(ctx.user_id, db, alpaca)
    if snapshot is None:
        return []

    shortcuts: list[Shortcut] = []
    shortcuts += _concentration(snapshot)
    shortcuts += _allocation_drift(snapshot)
    shortcuts += _idle_cash(snapshot)
    shortcuts += _daily_recap(snapshot, ctx.bucket)
    return shortcuts


async def gather_snapshot(
    user_id: uuid.UUID, db: AsyncSession, alpaca: AlpacaBrokerService | None
) -> PortfolioSnapshot | None:
    if alpaca is None:
        return None
    account = await BrokerageAccountRepository.get_by_user_id(db, user_id)
    if account is None or account.account_status != STATUS_ACTIVE:
        return None

    try:
        raw_account, raw_positions = await asyncio.gather(
            alpaca.get_trading_account(account.alpaca_account_id),
            alpaca.list_positions(account.alpaca_account_id),
        )
    except (AlpacaBrokerError, AlpacaBrokerUnavailableError, NotFoundError) as exc:
        logger.warning(
            "shortcuts_portfolio_snapshot_failed",
            user_id=str(user_id),
            error=str(exc),
        )
        return None

    sectors = await _sectors_for(db, [p["symbol"] for p in raw_positions])
    positions = [
        Position(
            symbol=p["symbol"],
            market_value=Decimal(p.get("market_value") or "0"),
            sector=sectors.get(p["symbol"]),
        )
        for p in raw_positions
    ]
    return PortfolioSnapshot(
        total_value=Decimal(raw_account.get("equity") or "0"),
        cash=Decimal(raw_account.get("cash") or "0"),
        positions=positions,
    )


async def _sectors_for(
    db: AsyncSession, symbols: list[str]
) -> dict[str, str]:
    if not symbols:
        return {}
    stmt = select(Asset.symbol, Asset.sector).where(Asset.symbol.in_(symbols))
    rows = (await db.execute(stmt)).all()
    return {symbol: sector for symbol, sector in rows if sector is not None}


def _concentration(snap: PortfolioSnapshot) -> list[Shortcut]:
    if snap.total_value <= PORTFOLIO_FLOOR:
        return []
    out: list[Shortcut] = []
    for pos in snap.positions:
        weight = pos.market_value / snap.total_value
        if weight > CONCENTRATION_THRESHOLD:
            out.append(
                Shortcut.create(
                    text=f"Is having {_as_pct(weight)}% in {pos.symbol} too much?",
                    category="portfolio_state",
                    magnitude=float(weight),
                )
            )
    return out


def _allocation_drift(snap: PortfolioSnapshot) -> list[Shortcut]:
    if snap.total_value <= PORTFOLIO_FLOOR:
        return []
    by_sector: dict[str, Decimal] = {}
    for pos in snap.positions:
        if pos.sector is None:
            continue
        by_sector[pos.sector] = by_sector.get(pos.sector, Decimal("0")) + pos.market_value
    out: list[Shortcut] = []
    for sector, market_value in by_sector.items():
        weight = market_value / snap.total_value
        if weight > SECTOR_THRESHOLD:
            out.append(
                Shortcut.create(
                    text=f"Why is my {sector} allocation so high?",
                    category="portfolio_state",
                    magnitude=float(weight),
                )
            )
    return out


def _idle_cash(snap: PortfolioSnapshot) -> list[Shortcut]:
    if snap.cash <= MIN_IDLE_CASH or snap.total_value <= 0:
        return []
    ratio = snap.cash / snap.total_value
    if ratio <= IDLE_CASH_RATIO:
        return []
    return [
        Shortcut.create(
            text="What should I do with my cash sitting in the account?",
            category="portfolio_state",
            magnitude=float(ratio),
        )
    ]


def _daily_recap(
    snap: PortfolioSnapshot, bucket: TimeBucket
) -> list[Shortcut]:
    if not snap.positions or bucket != TimeBucket.AFTER_MARKET:
        return []
    # Routine recap, not a risk signal: pin it behind any concentration /
    # drift / idle-cash prompt that also fired this bucket.
    return [
        Shortcut.create(
            text="How did my portfolio do today?",
            category="portfolio_state",
            magnitude=0.0,
        )
    ]


def _as_pct(weight: Decimal) -> int:
    return int((weight * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
