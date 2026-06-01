import uuid

import structlog
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.schemas.recurring_investment import (
    RecurringInvestmentCreate,
    RecurringInvestmentListResponse,
    RecurringInvestmentRead,
    RecurringInvestmentUpdate,
)
from app.services.alpaca_broker import AlpacaBrokerService
from app.services.recurring_investment import RecurringInvestmentService

logger = structlog.get_logger(__name__)

router = APIRouter()


def get_alpaca(request: Request) -> AlpacaBrokerService:
    return request.app.state.alpaca


@router.post(
    "",
    response_model=RecurringInvestmentRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_recurring_investment(
    body: RecurringInvestmentCreate,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    alpaca: AlpacaBrokerService = Depends(get_alpaca),
) -> RecurringInvestmentRead:
    item = await RecurringInvestmentService.create(
        db,
        alpaca=alpaca,
        user_id=uuid.UUID(user_id),
        data=body,
    )
    return RecurringInvestmentRead.model_validate(item)


@router.get("", response_model=RecurringInvestmentListResponse)
async def list_recurring_investments(
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RecurringInvestmentListResponse:
    items = await RecurringInvestmentService.list_for_user(
        db, user_id=uuid.UUID(user_id)
    )
    return RecurringInvestmentListResponse(
        recurring_investments=[
            RecurringInvestmentRead.model_validate(item) for item in items
        ]
    )


@router.patch(
    "/{recurring_investment_id}", response_model=RecurringInvestmentRead
)
async def update_recurring_investment(
    recurring_investment_id: uuid.UUID,
    body: RecurringInvestmentUpdate,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RecurringInvestmentRead:
    if body.action == "pause":
        item = await RecurringInvestmentService.pause(
            db,
            user_id=uuid.UUID(user_id),
            recurring_investment_id=recurring_investment_id,
        )
    else:
        item = await RecurringInvestmentService.resume(
            db,
            user_id=uuid.UUID(user_id),
            recurring_investment_id=recurring_investment_id,
        )
    return RecurringInvestmentRead.model_validate(item)


@router.delete(
    "/{recurring_investment_id}", response_model=RecurringInvestmentRead
)
async def cancel_recurring_investment(
    recurring_investment_id: uuid.UUID,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RecurringInvestmentRead:
    item = await RecurringInvestmentService.cancel(
        db,
        user_id=uuid.UUID(user_id),
        recurring_investment_id=recurring_investment_id,
    )
    return RecurringInvestmentRead.model_validate(item)
