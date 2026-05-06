"""FastAPI router for /v1/brokerage/* — read-only views over Alpaca trading data."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.schemas.brokerage import OrderListResponse, PositionListResponse
from app.schemas.cash_interest import CashInterestResponse
from app.services.alpaca_broker import AlpacaBrokerService
from app.services.brokerage import BrokerageService
from app.services.cash_interest import CashInterestService

router = APIRouter()


def get_alpaca(request: Request) -> AlpacaBrokerService:
    return request.app.state.alpaca


@router.get("/orders", response_model=OrderListResponse)
async def list_orders(
    status: Literal["open", "closed", "all"] | None = None,
    side: Literal["buy", "sell"] | None = None,
    symbols: str | None = Query(
        None, max_length=200, description="Comma-separated symbol filter"
    ),
    after: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(100, ge=1, le=500),
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    alpaca: AlpacaBrokerService = Depends(get_alpaca),
) -> OrderListResponse:
    """List orders for the authenticated user's brokerage account.

    When `status` is omitted, defaults to all statuses (filled, open, canceled,
    rejected) so the trade-history screen surfaces the full history rather than
    Alpaca's open-only default.
    """
    return await BrokerageService.list_orders(
        db,
        alpaca=alpaca,
        user_id=uuid.UUID(user_id),
        status=status,
        side=side,
        symbols=symbols,
        after=after.isoformat() if after else None,
        until=until.isoformat() if until else None,
        limit=limit,
    )


@router.get("/positions", response_model=PositionListResponse)
async def list_positions(
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    alpaca: AlpacaBrokerService = Depends(get_alpaca),
) -> PositionListResponse:
    """List open positions for the authenticated user's brokerage account."""
    return await BrokerageService.list_positions(
        db, alpaca=alpaca, user_id=uuid.UUID(user_id)
    )


@router.get("/cash-interest", response_model=CashInterestResponse)
async def get_cash_interest(
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    alpaca: AlpacaBrokerService = Depends(get_alpaca),
) -> CashInterestResponse:
    """Aggregated cash sweep snapshot: balance, APY, accrued and realized interest."""
    return await CashInterestService.get_cash_interest(
        db, alpaca=alpaca, user_id=uuid.UUID(user_id)
    )
