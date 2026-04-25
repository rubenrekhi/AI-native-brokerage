"""Brokerage service: read-only views over Alpaca trading data (orders, positions)."""

import uuid
from typing import Any, Literal, TypeVar

import structlog
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError
from app.repositories.brokerage_account import (
    STATUS_ACCOUNT_CLOSED,
    BrokerageAccountRepository,
)
from app.schemas.brokerage import (
    OrderListResponse,
    OrderResponse,
    PositionListResponse,
    PositionResponse,
)
from app.services.alpaca_broker import AlpacaBrokerService

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


class BrokerageService:
    @staticmethod
    async def list_orders(
        db: AsyncSession,
        *,
        alpaca: AlpacaBrokerService,
        user_id: uuid.UUID,
        status: Literal["open", "closed", "all"] | None = None,
        side: Literal["buy", "sell"] | None = None,
        symbols: str | None = None,
        after: str | None = None,
        until: str | None = None,
        limit: int | None = None,
    ) -> OrderListResponse:
        brokerage = await _require_brokerage(db, user_id)

        # Default to "all" to surface the full history (filled + open + canceled
        # + rejected). Without this, Alpaca defaults to "open" only and the
        # trade-history screen looks empty for users with no live working orders.
        effective_status = status or "all"

        raw = await alpaca.list_orders(
            brokerage.alpaca_account_id,
            status=effective_status,
            side=side,
            symbols=symbols,
            after=after,
            until=until,
            limit=limit,
            direction="desc",
        )

        orders = _project(raw, OrderResponse, log_event="alpaca_order_malformed", user_id=user_id)
        return OrderListResponse(orders=orders)

    @staticmethod
    async def list_positions(
        db: AsyncSession,
        *,
        alpaca: AlpacaBrokerService,
        user_id: uuid.UUID,
    ) -> PositionListResponse:
        brokerage = await _require_brokerage(db, user_id)

        raw = await alpaca.list_positions(brokerage.alpaca_account_id)
        positions = _project(
            raw, PositionResponse, log_event="alpaca_position_malformed", user_id=user_id
        )
        return PositionListResponse(positions=positions)


async def _require_brokerage(db: AsyncSession, user_id: uuid.UUID):
    """Brokerage gate for read-only views.

    Mirrors `SettingsService.get_account_value` rather than the funding
    gate: any non-closed brokerage row with an Alpaca account id can be
    queried for orders/positions, even if local `account_status` is still
    `APPROVED` / `SUBMITTED` / etc. Only `ACCOUNT_CLOSED` and a missing row
    are 404'd — closed accounts have no trade data to show.
    """
    brokerage = await BrokerageAccountRepository.get_by_user_id(db, user_id)
    if brokerage is None or brokerage.account_status == STATUS_ACCOUNT_CLOSED:
        raise NotFoundError(
            "Brokerage account not found",
            resource="brokerage_account",
        )
    return brokerage


def _project(
    raw: list[dict[str, Any]],
    model: type[T],
    *,
    log_event: str,
    user_id: uuid.UUID,
) -> list[T]:
    """Validate each Alpaca record into `model`, skipping malformed entries.

    Mirrors the pattern in SettingsService.list_documents — Alpaca occasionally
    drifts shape on individual records and we'd rather drop one row than 5xx
    the whole list.
    """
    out: list[T] = []
    for item in raw:
        try:
            out.append(model.model_validate(item))
        except ValidationError as exc:
            # Log shape (keys) only, not values — keeps the diagnostic useful
            # if Alpaca's response shape ever grows fields we shouldn't log.
            logger.warning(
                log_event,
                user_id=str(user_id),
                raw_keys=list(item.keys()) if isinstance(item, dict) else None,
                error=str(exc),
            )
    # Aggregate signal when every record drops — a single 50/50 failure is a
    # likely schema drift on Alpaca's side, and we want one error-level log
    # (not fifty warnings) so it surfaces clearly in Sentry/operations.
    if raw and not out:
        logger.error(
            f"{log_event}_all_dropped",
            user_id=str(user_id),
            raw_count=len(raw),
        )
    return out
