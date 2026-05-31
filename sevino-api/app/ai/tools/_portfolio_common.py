"""Shared scaffolding for the portfolio read tools.

``get_portfolio`` and ``get_portfolio_performance`` both open a
``PortfolioService`` against the user's active brokerage account and surface
expected failures (no active account, brokerage down, deps missing) as an
``{"error", "code"}`` payload rather than raising, so they never end the
agent turn. This module holds that shared account/service setup, the error
payloads, and the status-pill lifecycle.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ulid import ULID

from app.ai.blocks import StatusBlock
from app.ai.tools.base import ToolContext, ToolResult
from app.ai.transport.events import BlockData, BlockStart
from app.dependencies.portfolio import AlpacaAccountContext
from app.repositories.brokerage_account import (
    STATUS_ACTIVE,
    BrokerageAccountRepository,
)
from app.services.portfolio import PortfolioService

CONFIG_ERROR: dict[str, Any] = {
    "error": "Portfolio data is not available in this environment.",
    "code": "PORTFOLIO_UNAVAILABLE",
}
UPSTREAM_ERROR: dict[str, Any] = {
    "error": "The brokerage is temporarily unavailable. Try again shortly.",
    "code": "BROKERAGE_UNAVAILABLE",
}


class AccountUnavailable(Exception):
    """Raised inside the session block to short-circuit to an error payload."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        super().__init__(payload.get("code"))


async def open_service(
    ctx: ToolContext, db: Any
) -> tuple[AlpacaAccountContext, PortfolioService]:
    account = await BrokerageAccountRepository.get_by_user_id(db, ctx.user_id)
    if account is None or account.account_status != STATUS_ACTIVE:
        raise AccountUnavailable(_no_active_account(account))
    acct_ctx = AlpacaAccountContext(
        user_id=ctx.user_id,
        alpaca_account_id=account.alpaca_account_id,
        account_status=account.account_status,
    )
    service = PortfolioService(
        ctx.http_clients.alpaca, ctx.http_clients.redis, db
    )
    return acct_ctx, service


def _no_active_account(account: Any) -> dict[str, Any]:
    return {
        "error": (
            "The user does not have an active brokerage account, so "
            "portfolio data is unavailable."
        ),
        "code": "ACCOUNT_NOT_ACTIVE",
        "account_status": account.account_status if account is not None else None,
    }


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def emit_active(ctx: ToolContext, label: str) -> str:
    block_id = str(ULID())
    pill = StatusBlock(block_id=block_id, label=label, state="active")
    await ctx.sse_emitter.emit(BlockStart(block=pill.model_dump(mode="json")))
    return block_id


async def complete(
    ctx: ToolContext,
    block_id: str,
    label: str,
    payload: dict[str, Any],
    internal_trace: dict[str, Any] | None = None,
) -> ToolResult:
    pill = StatusBlock(block_id=block_id, label=label, state="complete")
    await ctx.sse_emitter.emit(
        BlockData(block_id=block_id, data=pill.model_dump(mode="json"))
    )
    return ToolResult(
        model_payload=payload, ui_block=pill, internal_trace=internal_trace
    )


async def fail(
    ctx: ToolContext,
    block_id: str,
    label: str,
    payload: dict[str, Any],
) -> ToolResult:
    pill = StatusBlock(block_id=block_id, label=label, state="failed")
    await ctx.sse_emitter.emit(
        BlockData(block_id=block_id, data=pill.model_dump(mode="json"))
    )
    return ToolResult(model_payload=payload, ui_block=pill)
