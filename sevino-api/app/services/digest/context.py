"""Gathers the per-user inputs the digest generators read.

Mirrors the radar orchestrator's context gather: portfolio comes from
Alpaca (live, only for ACTIVE accounts), the financial profile and
favorited radar symbols from the DB. Alpaca being unavailable degrades to
an empty portfolio rather than failing the whole run — a digest with
non-portfolio cards is still worth shipping.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.radar_item import RadarItem
from app.repositories.brokerage_account import (
    STATUS_ACTIVE,
    BrokerageAccountRepository,
)
from app.repositories.financial_profile import FinancialProfileRepository
from app.services.alpaca_broker import (
    AlpacaBrokerService,
    AlpacaBrokerUnavailableError,
)
from app.services.digest.types import DigestContext, MarketState

logger = structlog.get_logger(__name__)

ET = ZoneInfo("America/New_York")


async def build_context(
    user_id: uuid.UUID,
    db: AsyncSession,
    alpaca: AlpacaBrokerService,
) -> DigestContext:
    snapshot, holdings = await _portfolio_inputs(user_id, db, alpaca)
    financial = await FinancialProfileRepository.get_by_user_id(db, user_id)
    favorited = await _favorited_symbols(db, user_id)
    return DigestContext(
        user_id=user_id,
        portfolio_snapshot=snapshot,
        holdings=holdings,
        financial_profile=financial,
        favorited_radar_symbols=favorited,
        market_state=_market_state(datetime.now(timezone.utc)),
    )


async def _portfolio_inputs(
    user_id: uuid.UUID,
    db: AsyncSession,
    alpaca: AlpacaBrokerService,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    brokerage = await BrokerageAccountRepository.get_by_user_id(db, user_id)
    if brokerage is None or brokerage.account_status != STATUS_ACTIVE:
        return None, []
    try:
        snapshot = await alpaca.get_trading_account(brokerage.alpaca_account_id)
        holdings = await alpaca.list_positions(brokerage.alpaca_account_id)
    except AlpacaBrokerUnavailableError:
        logger.warning(
            "digest_context_portfolio_unavailable", user_id=str(user_id)
        )
        return None, []
    return snapshot, list(holdings)


async def _favorited_symbols(
    db: AsyncSession, user_id: uuid.UUID
) -> list[str]:
    result = await db.execute(
        select(RadarItem.symbol)
        .where(
            RadarItem.user_id == user_id,
            RadarItem.is_favorited.is_(True),
        )
        .order_by(RadarItem.symbol)
    )
    return list(result.scalars().all())


def _market_state(now_utc: datetime) -> MarketState:
    et = now_utc.astimezone(ET)
    minutes = et.hour * 60 + et.minute
    if et.weekday() >= 5:
        session = "closed"
    elif 4 * 60 <= minutes < 9 * 60 + 30:
        session = "pre"
    elif 9 * 60 + 30 <= minutes < 16 * 60:
        session = "open"
    elif 16 * 60 <= minutes < 20 * 60:
        session = "post"
    else:
        session = "closed"
    return MarketState(as_of=now_utc, session=session)
