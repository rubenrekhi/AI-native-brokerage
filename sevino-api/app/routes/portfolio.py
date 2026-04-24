"""FastAPI router for /v1/portfolio/*.

Backs the iOS home screen: snapshot summary, holdings list, and the
range-selectable performance chart. Auth-gated; rate-limited via the
global per-user default. The `get_alpaca_account_context` dep enforces
that the caller has an ACTIVE brokerage account before any handler
runs, so handlers trust `ctx.account_status == "ACTIVE"`.
"""

from fastapi import APIRouter, Depends, Request

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_redis
from app.dependencies.portfolio import (
    AlpacaAccountContext,
    get_alpaca_account_context,
)
from app.schemas.portfolio import HoldingsResponse, PortfolioSnapshotResponse
from app.services.alpaca_broker import AlpacaBrokerService
from app.services.portfolio import PortfolioService

router = APIRouter()


def get_alpaca(request: Request) -> AlpacaBrokerService:
    return request.app.state.alpaca


def _portfolio_service(
    alpaca: AlpacaBrokerService = Depends(get_alpaca),
    redis: aioredis.Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
) -> PortfolioService:
    return PortfolioService(alpaca, redis, db)


@router.get("/snapshot", response_model=PortfolioSnapshotResponse)
async def get_snapshot(
    ctx: AlpacaAccountContext = Depends(get_alpaca_account_context),
    service: PortfolioService = Depends(_portfolio_service),
) -> PortfolioSnapshotResponse:
    """Equity, cash, buying power, and daily change for the home screen."""
    return await service.get_snapshot(ctx)


@router.get("/holdings", response_model=HoldingsResponse)
async def get_holdings(
    ctx: AlpacaAccountContext = Depends(get_alpaca_account_context),
    service: PortfolioService = Depends(_portfolio_service),
) -> HoldingsResponse:
    """Per-symbol positions joined with names, sorted by market value."""
    return await service.get_holdings(ctx)
