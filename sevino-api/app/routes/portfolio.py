"""FastAPI router for /v1/portfolio/*.

Backs the iOS home screen: snapshot summary, holdings list, and the
range-selectable performance chart. Auth-gated; rate-limited via the
global per-user default. The `get_alpaca_account_context` dep enforces
that the caller has an ACTIVE brokerage account before any handler
runs, so handlers trust `ctx.account_status == "ACTIVE"`.
"""

from fastapi import APIRouter, Depends, Request

import redis.asyncio as aioredis

from app.dependencies import get_redis
from app.dependencies.portfolio import (
    AlpacaAccountContext,
    get_alpaca_account_context,
)
from app.schemas.portfolio import PortfolioSnapshotResponse
from app.services.alpaca_broker import AlpacaBrokerService
from app.services.portfolio import PortfolioService

router = APIRouter()


def get_alpaca(request: Request) -> AlpacaBrokerService:
    return request.app.state.alpaca


def _portfolio_service(
    alpaca: AlpacaBrokerService = Depends(get_alpaca),
    redis: aioredis.Redis = Depends(get_redis),
) -> PortfolioService:
    return PortfolioService(alpaca, redis)


@router.get("/snapshot", response_model=PortfolioSnapshotResponse)
async def get_snapshot(
    ctx: AlpacaAccountContext = Depends(get_alpaca_account_context),
    service: PortfolioService = Depends(_portfolio_service),
) -> PortfolioSnapshotResponse:
    return await service.get_snapshot(ctx)
