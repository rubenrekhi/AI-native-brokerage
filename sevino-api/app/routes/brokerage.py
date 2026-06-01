"""FastAPI router for /v1/brokerage/* — read-only views over Alpaca trading data."""

import uuid
from datetime import datetime, timezone
from typing import Literal

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.exceptions import ConflictError
from app.repositories.brokerage_account import (
    STATUS_ACTIVE,
    SWEEP_STATUS_ACTIVE,
    SWEEP_STATUS_PENDING_CHANGE,
    BrokerageAccountRepository,
)
from app.schemas.brokerage import (
    DividendListResponse,
    OrderListResponse,
    PositionListResponse,
)
from app.schemas.cash_interest import CashInterestResponse
from app.services.alpaca_broker import AlpacaBrokerService
from app.services.brokerage import BrokerageService, require_brokerage
from app.services.cash_interest import CashInterestService

router = APIRouter()


def get_alpaca(request: Request) -> AlpacaBrokerService:
    return request.app.state.alpaca


def get_arq(request: Request) -> ArqRedis:
    return request.app.state.arq


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


@router.post(
    "/cash-interest/enroll",
    response_model=CashInterestResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def enroll_cash_interest_endpoint(
    response: Response,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    alpaca: AlpacaBrokerService = Depends(get_alpaca),
    arq: ArqRedis = Depends(get_arq),
) -> CashInterestResponse:
    """Enroll (or re-enroll) the user's account in the FDIC cash sweep (SEV-655).

    Idempotent: returns 200 when the sweep is already ACTIVE, and 202 (without
    enqueuing a second job) when enrollment is already PENDING_CHANGE.
    Otherwise flips the sweep to PENDING_CHANGE and enqueues the background
    enrollment task, returning 202 with the updated snapshot so the client sees
    the pending state in one round-trip.
    """
    uid = uuid.UUID(user_id)
    brokerage = await require_brokerage(db, uid)

    if brokerage.account_status != STATUS_ACTIVE:
        raise ConflictError(
            "Brokerage account is not active yet",
            code="ACCOUNT_NOT_ACTIVE",
            detail={"account_status": brokerage.account_status},
        )

    if brokerage.sweep_status == SWEEP_STATUS_ACTIVE:
        response.status_code = status.HTTP_200_OK
        return await CashInterestService.get_cash_interest(
            db, alpaca=alpaca, user_id=uid
        )

    if brokerage.sweep_status == SWEEP_STATUS_PENDING_CHANGE:
        # A job is already in flight; re-enrolling would enqueue a duplicate.
        # Return the pending snapshot without touching state or the queue.
        return await CashInterestService.get_cash_interest(
            db, alpaca=alpaca, user_id=uid
        )

    if not settings.alpaca_apr_tier_name:
        # The enrollment task no-ops without a configured tier, so flipping to
        # PENDING_CHANGE here would strand the row with no job to clear it.
        raise ConflictError(
            "FDIC cash sweep is not available yet",
            code="CASH_INTEREST_UNAVAILABLE",
        )

    await BrokerageAccountRepository.update_status(
        db,
        brokerage.id,
        sweep_status=SWEEP_STATUS_PENDING_CHANGE,
        sweep_enrolled_at=datetime.now(timezone.utc),
    )
    # Enqueue before building the response so a Redis failure propagates and
    # get_db rolls back the PENDING_CHANGE flip — no stuck status without a job.
    # The reverse isn't atomic (commit can still fail after a successful
    # enqueue); the task re-reads by id and the idempotent PATCH absorbs it.
    await arq.enqueue_job("enroll_cash_interest", str(brokerage.id))

    return await CashInterestService.get_cash_interest(
        db, alpaca=alpaca, user_id=uid
    )


@router.get("/dividends", response_model=DividendListResponse)
async def list_dividends(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    alpaca: AlpacaBrokerService = Depends(get_alpaca),
) -> DividendListResponse:
    """List dividend payments for the authenticated user's brokerage account.

    Filters Alpaca's DIV activity bucket to positive-amount payments —
    excludes withholdings (DIVNRA/DIVTAX) and ADR pass-through fees (DIVFEE).
    Status is raw from Alpaca; iOS buckets it.
    """
    return await BrokerageService.list_dividends(
        db,
        alpaca=alpaca,
        user_id=uuid.UUID(user_id),
        limit=limit,
        offset=offset,
    )
