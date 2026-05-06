import uuid

import structlog
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.schemas.trading import (
    OrderDetailResponse,
    PlaceOrderRequest,
    PlaceOrderResponse,
)
from app.services.alpaca_broker import AlpacaBrokerService
from app.services.trading import TradingService

logger = structlog.get_logger(__name__)

router = APIRouter()


def get_alpaca(request: Request) -> AlpacaBrokerService:
    return request.app.state.alpaca


@router.post(
    "/orders",
    response_model=PlaceOrderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def place_order(
    body: PlaceOrderRequest,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    alpaca: AlpacaBrokerService = Depends(get_alpaca),
) -> PlaceOrderResponse:
    order = await TradingService.place_order(
        db,
        alpaca=alpaca,
        user_id=uuid.UUID(user_id),
        data=body,
    )
    return PlaceOrderResponse.model_validate(order)


@router.get("/orders/{order_id}", response_model=OrderDetailResponse)
async def get_order(
    order_id: uuid.UUID,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrderDetailResponse:
    order = await TradingService.get_order(
        db,
        user_id=uuid.UUID(user_id),
        order_id=order_id,
    )
    return OrderDetailResponse.model_validate(order)


@router.delete("/orders/{order_id}", response_model=OrderDetailResponse)
async def cancel_order(
    order_id: uuid.UUID,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    alpaca: AlpacaBrokerService = Depends(get_alpaca),
) -> OrderDetailResponse:
    order = await TradingService.cancel_order(
        db,
        alpaca=alpaca,
        user_id=uuid.UUID(user_id),
        order_id=order_id,
    )
    return OrderDetailResponse.model_validate(order)
