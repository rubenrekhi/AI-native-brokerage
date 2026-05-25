import uuid

import structlog
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.ach_relationship import AchRelationship
from app.repositories.plaid_item import STATUS_REQUIRES_REAUTH
from app.schemas.funding import (
    AchRelationshipListResponse,
    AchRelationshipResponse,
    LinkBankRequest,
    LinkTokenResponse,
    TransferListResponse,
    TransferRequest,
    TransferResponse,
)
from app.services.alpaca_broker import AlpacaBrokerService
from app.services.funding import FundingService
from app.services.plaid import PlaidService

logger = structlog.get_logger(__name__)

router = APIRouter()


def get_alpaca(request: Request) -> AlpacaBrokerService:
    return request.app.state.alpaca


def get_plaid(request: Request) -> PlaidService:
    return request.app.state.plaid


def _build_relationship_response(
    rel: AchRelationship,
) -> AchRelationshipResponse:
    """Reads `rel.plaid_item.status` directly — caller must eager-load it."""
    response = AchRelationshipResponse.model_validate(rel)
    response.requires_reauth = (
        rel.plaid_item is not None
        and rel.plaid_item.status == STATUS_REQUIRES_REAUTH
    )
    return response


@router.post("/link-token", response_model=LinkTokenResponse)
async def create_link_token(
    user_id: str = Depends(get_current_user),
    plaid: PlaidService = Depends(get_plaid),
) -> LinkTokenResponse:
    token = await FundingService.create_link_token(
        plaid=plaid, user_id=uuid.UUID(user_id)
    )
    return LinkTokenResponse(link_token=token)


@router.post("/link-bank", response_model=AchRelationshipResponse)
async def link_bank(
    body: LinkBankRequest,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    plaid: PlaidService = Depends(get_plaid),
    alpaca: AlpacaBrokerService = Depends(get_alpaca),
) -> AchRelationshipResponse:
    relationship = await FundingService.link_bank(
        db,
        plaid=plaid,
        alpaca=alpaca,
        user_id=uuid.UUID(user_id),
        public_token=body.public_token,
        account_id=body.account_id,
        institution_name=body.institution_name,
        account_mask=body.account_mask,
        account_name=body.account_name,
        nickname=body.nickname,
    )
    return AchRelationshipResponse.model_validate(relationship)


@router.get("/ach-relationships", response_model=AchRelationshipListResponse)
async def list_ach_relationships(
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    alpaca: AlpacaBrokerService = Depends(get_alpaca),
) -> AchRelationshipListResponse:
    relationships = await FundingService.list_active_ach_relationships(
        db, alpaca=alpaca, user_id=uuid.UUID(user_id)
    )
    return AchRelationshipListResponse(
        relationships=[_build_relationship_response(r) for r in relationships]
    )


@router.delete("/ach-relationships/{relationship_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ach_relationship(
    relationship_id: uuid.UUID,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    alpaca: AlpacaBrokerService = Depends(get_alpaca),
) -> None:
    await FundingService.unlink_bank(
        db,
        alpaca=alpaca,
        user_id=uuid.UUID(user_id),
        relationship_pk=relationship_id,
    )


@router.post("/transfers", response_model=TransferResponse)
async def create_transfer(
    body: TransferRequest,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    alpaca: AlpacaBrokerService = Depends(get_alpaca),
) -> TransferResponse:
    transfer = await FundingService.create_transfer(
        db,
        alpaca=alpaca,
        user_id=uuid.UUID(user_id),
        relationship_pk=body.relationship_id,
        amount=body.amount,
        direction=body.direction,
    )
    return TransferResponse.model_validate(transfer)


@router.get("/transfers", response_model=TransferListResponse)
async def list_transfers(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    alpaca: AlpacaBrokerService = Depends(get_alpaca),
) -> TransferListResponse:
    transfers = await FundingService.list_transfers(
        db,
        alpaca=alpaca,
        user_id=uuid.UUID(user_id),
        limit=limit,
        offset=offset,
    )
    return TransferListResponse(
        transfers=[TransferResponse.model_validate(t) for t in transfers]
    )
