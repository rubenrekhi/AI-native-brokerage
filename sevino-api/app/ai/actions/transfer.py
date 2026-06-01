"""Executor for the ``transfer`` HIL action — runs a confirmed ACH transfer.

Reached only after the user taps Confirm on a ``transfer_operations`` proposal.
Wraps the existing ``FundingService.create_transfer``; the authoritative
result (transfer id + Alpaca status) renders in the receipt card, never from
model free-text.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog
from ulid import ULID

from app.ai.actions.base import ActionContext, ActionResult
from app.ai.blocks import ConfirmationBlock, ConfirmationRow
from app.exceptions import ConflictError, NotFoundError
from app.services.alpaca_broker import (
    AlpacaBrokerError,
    AlpacaBrokerUnavailableError,
)
from app.services.funding import FundingService

logger = structlog.get_logger(__name__)


def _bank_label(payload: dict[str, Any]) -> str:
    name = (
        payload.get("bank_nickname")
        or payload.get("bank_institution")
        or "your bank"
    )
    mask = payload.get("bank_mask")
    return f"{name} ••{mask}" if mask else name


def _flow(operation: str, bank: str) -> str:
    return (
        f"{bank} → Sevino"
        if operation == "deposit"
        else f"Sevino → {bank}"
    )


def _receipt(
    *,
    operation: str,
    direction: str,
    amount: Decimal,
    payload: dict[str, Any],
    status: str,
    rows: list[ConfirmationRow],
    extra_details: dict[str, Any],
) -> ConfirmationBlock:
    verb = "Deposit" if operation == "deposit" else "Withdrawal"
    title = (
        f"{verb} submitted"
        if status == "executed"
        else f"{verb} didn't go through"
    )
    return ConfirmationBlock(
        block_id=str(ULID()),
        action_id=str(ULID()),
        kind="transfer",
        title=title,
        rows=rows,
        details={
            "operation": operation,
            "direction": direction,
            "amount": str(amount),
            "currency": "USD",
            "bank_institution": payload.get("bank_institution"),
            "bank_mask": payload.get("bank_mask"),
            "bank_nickname": payload.get("bank_nickname"),
            **extra_details,
        },
        hold_to_confirm=False,
        status=status,
    )


async def execute_transfer(
    payload: dict[str, Any], ctx: ActionContext
) -> ActionResult:
    direction = payload["direction"]
    operation = payload.get(
        "operation", "deposit" if direction == "INCOMING" else "withdraw"
    )
    amount = Decimal(payload["amount"])
    bank = _bank_label(payload)
    verb = "deposit" if operation == "deposit" else "withdrawal"

    alpaca = ctx.http_clients.alpaca
    if alpaca is None:
        return _failed(operation, direction, amount, payload, "Transfers are temporarily unavailable.")

    try:
        async with ctx.db_factory() as db:
            res = await FundingService.create_transfer(
                db,
                alpaca=alpaca,
                user_id=ctx.user_id,
                relationship_pk=UUID(payload["relationship_pk"]),
                amount=amount,
                direction=direction,
            )
    except (ConflictError, NotFoundError) as exc:
        # These carry curated, user-safe messages (e.g. "still being verified").
        logger.warning(
            "transfer_action_rejected",
            user_id=str(ctx.user_id),
            direction=direction,
            code=getattr(exc, "code", None),
            exc_type=type(exc).__name__,
        )
        reason = getattr(exc, "message", None) or "Please try again shortly."
        return _failed(operation, direction, amount, payload, reason)
    except (AlpacaBrokerError, AlpacaBrokerUnavailableError) as exc:
        # ``.message`` here is raw upstream/network text — log it, but show the
        # user generic copy (Section 7: no internal details in the response).
        logger.warning(
            "transfer_action_upstream_failed",
            user_id=str(ctx.user_id),
            direction=direction,
            error=str(exc),
            exc_type=type(exc).__name__,
        )
        return _failed(
            operation,
            direction,
            amount,
            payload,
            "The brokerage couldn't process that right now. Please try "
            "again shortly.",
        )
    except Exception:
        # A money action must always end in a result card, never a bare stream
        # error — e.g. a commit/flush failure after the Alpaca POST.
        logger.exception(
            "transfer_action_unexpected_error",
            user_id=str(ctx.user_id),
            direction=direction,
        )
        return _failed(
            operation,
            direction,
            amount,
            payload,
            "Something went wrong. Please try again.",
        )

    transfer_status = res.get("status", "QUEUED")
    receipt = _receipt(
        operation=operation,
        direction=direction,
        amount=amount,
        payload=payload,
        status="executed",
        rows=[
            ConfirmationRow(label="Amount", value=f"${amount:,.2f}"),
            ConfirmationRow(label="Transfer", value=_flow(operation, bank)),
            ConfirmationRow(label="Status", value=transfer_status.title()),
        ],
        extra_details={
            "transfer_id": res.get("id"),
            "transfer_status": transfer_status,
        },
    )
    return ActionResult(
        status="executed",
        result_block=receipt,
        summary={
            "transfer_id": res.get("id"),
            "status": transfer_status,
            "amount": str(amount),
            "direction": direction,
        },
        narration=(
            f"Your {verb} of ${amount:,.2f} with {bank} is on its way. "
            "I'll keep an eye on it and let you know once it settles."
        ),
    )


def _failed(
    operation: str,
    direction: str,
    amount: Decimal,
    payload: dict[str, Any],
    reason: str,
) -> ActionResult:
    bank = _bank_label(payload)
    verb = "deposit" if operation == "deposit" else "withdrawal"
    receipt = _receipt(
        operation=operation,
        direction=direction,
        amount=amount,
        payload=payload,
        status="failed",
        rows=[
            ConfirmationRow(label="Amount", value=f"${amount:,.2f}"),
            ConfirmationRow(label="Transfer", value=_flow(operation, bank)),
            ConfirmationRow(label="Reason", value=reason),
        ],
        extra_details={"reason": reason},
    )
    return ActionResult(
        status="failed",
        result_block=receipt,
        summary={"error": reason, "amount": str(amount), "direction": direction},
        narration=f"I couldn't complete that {verb} — {reason}",
    )
