"""Handler for the ``transfer`` HIL action — runs a confirmed ACH transfer.

Reached only after the user taps Confirm on a ``transfer_operations`` proposal.
``execute`` wraps the existing ``FundingService.create_transfer`` and returns a
``resume_prompt`` describing the outcome; the confirm endpoint then drives a
full agent turn seeded with it, so the model narrates the result naturally and
may call further tools.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog

from app.ai.actions.base import ActionContext, ActionResult
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
        or "their bank"
    )
    mask = payload.get("bank_mask")
    return f"{name} ••{mask}" if mask else name


def _verb(operation: str) -> str:
    return "deposit" if operation == "deposit" else "withdrawal"


def _flow_phrase(operation: str, bank: str) -> str:
    return (
        f"into their Sevino account from {bank}"
        if operation == "deposit"
        else f"from their Sevino account to {bank}"
    )


def _alpaca_failure_reason(exc: AlpacaBrokerError) -> str:
    """Translate a known Alpaca rejection into an honest, user-safe reason.

    Matches on Alpaca's stable error code first, then message text. Unknown
    errors fall back to a generic line — raw upstream text is never surfaced
    (Section 7), but the common, non-sensitive cases get a truthful reason the
    model can relay instead of a vague "couldn't process it".
    """
    code = (exc.detail or {}).get("code")
    text = (exc.message or "").lower()

    # 40310000: withdrawal exceeds withdrawable cash — typically because a
    # recent ACH deposit hasn't settled yet.
    if code == 40310000 or "withdrawable" in text:
        return (
            "that's more than the balance available to withdraw right now — "
            "recently deposited funds aren't withdrawable until they settle, "
            "which takes about 1–3 business days."
        )
    # Alpaca de-dupes identical transfers submitted close together.
    if "duplicate" in text:
        return (
            "it looked like a duplicate of a transfer that was just made, so "
            "it wasn't submitted again."
        )
    return "the brokerage couldn't process it right now."


class TransferActionHandler:
    """Executes confirmed deposits/withdrawals and supplies the resume/reject
    prompts that seed the follow-up agent turn."""

    async def execute(
        self, payload: dict[str, Any], ctx: ActionContext
    ) -> ActionResult:
        direction = payload["direction"]
        operation = payload.get(
            "operation", "deposit" if direction == "INCOMING" else "withdraw"
        )
        amount = Decimal(payload["amount"])
        amount_str = f"${amount:,.2f}"
        bank = _bank_label(payload)
        verb = _verb(operation)
        flow = _flow_phrase(operation, bank)

        reason = await self._run_transfer(payload, ctx, amount, direction)
        if reason is None:
            return ActionResult(
                status="executed",
                resume_prompt=(
                    f"The {verb} the user authorized is already complete: "
                    f"{amount_str} {flow} went through and is on its way (ACH "
                    "transfers take 1–3 business days to settle). Your only job "
                    "now is to narrate this in one or two brief, friendly "
                    "sentences. Do NOT call the transfer tool again or propose "
                    "another transfer — the action is already final. Don't line "
                    "up a next step; wait for the user to ask."
                ),
                summary={"amount": str(amount), "direction": direction},
            )
        return ActionResult(
            status="failed",
            resume_prompt=(
                f"The {verb} the user authorized ({amount_str} {flow}) was "
                f"already attempted and could not be completed: {reason} Your "
                "only job now is to narrate this in one or two brief sentences: "
                "apologize and explain the reason in plain language. Do NOT call "
                "the transfer tool again or retry/propose the transfer yourself "
                "— if they want to try again, they can ask. Do not claim the "
                "transfer succeeded."
            ),
            summary={
                "error": reason,
                "amount": str(amount),
                "direction": direction,
            },
        )

    def reject_prompt(self, payload: dict[str, Any]) -> str:
        operation = payload.get(
            "operation",
            "deposit" if payload.get("direction") == "INCOMING" else "withdraw",
        )
        amount = Decimal(payload["amount"])
        return (
            f"The user declined the {_verb(operation)} you proposed "
            f"(${amount:,.2f} with {_bank_label(payload)}) — they tapped "
            "Cancel without confirming. Acknowledge briefly, don't be pushy, "
            "and don't re-propose it; let them know they can ask again whenever "
            "they're ready."
        )

    @staticmethod
    async def _run_transfer(
        payload: dict[str, Any],
        ctx: ActionContext,
        amount: Decimal,
        direction: str,
    ) -> str | None:
        """Run the transfer. Returns ``None`` on success, or a user-safe
        failure reason string. Raw upstream/network text is logged, never
        surfaced (Section 7)."""
        alpaca = ctx.http_clients.alpaca
        if alpaca is None:
            return "transfers are temporarily unavailable."
        try:
            async with ctx.db_factory() as db:
                await FundingService.create_transfer(
                    db,
                    alpaca=alpaca,
                    user_id=ctx.user_id,
                    relationship_pk=UUID(payload["relationship_pk"]),
                    amount=amount,
                    direction=direction,
                )
            return None
        except (ConflictError, NotFoundError) as exc:
            logger.warning(
                "transfer_action_rejected",
                user_id=str(ctx.user_id),
                direction=direction,
                code=getattr(exc, "code", None),
                exc_type=type(exc).__name__,
            )
            message = getattr(exc, "message", None)
            return message or "please try again shortly."
        except AlpacaBrokerUnavailableError as exc:
            logger.warning(
                "transfer_action_unavailable",
                user_id=str(ctx.user_id),
                direction=direction,
                error=str(exc),
            )
            return (
                "the brokerage is temporarily unreachable — please try again "
                "in a moment."
            )
        except AlpacaBrokerError as exc:
            logger.warning(
                "transfer_action_upstream_failed",
                user_id=str(ctx.user_id),
                direction=direction,
                status_code=exc.status_code,
                code=(exc.detail or {}).get("code"),
                error=str(exc),
            )
            return _alpaca_failure_reason(exc)
        except Exception:
            logger.exception(
                "transfer_action_unexpected_error",
                user_id=str(ctx.user_id),
                direction=direction,
            )
            return "something went wrong on our end."
