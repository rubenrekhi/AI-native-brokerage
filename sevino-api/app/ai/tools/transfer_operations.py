"""``transfer_operations`` — propose a deposit or withdrawal (HIL).

The tool never moves money. It parses the amount and resolves the source bank,
then returns a ``ConfirmationBlock`` and a ``ProposedAction`` (action_type
``transfer``); the framework persists it and the user taps to confirm, at which
point ``app.ai.actions.transfer.execute_transfer`` performs the ACH transfer.
See docs/ai/hil-actions.md.

Cancelling a pending transfer is a planned third operation but is not yet
supported — its execution layer (``FundingService.cancel_transfer``) does not
exist.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, ClassVar, Literal

import structlog
from pydantic import BaseModel, Field
from ulid import ULID

from app.ai.blocks import ConfirmationBlock, ConfirmationRow
from app.ai.tools.base import ProposedAction, Tool, ToolContext, ToolResult
from app.models.ach_relationship import AchRelationship
from app.services.funding import FundingService

logger = structlog.get_logger(__name__)

_APPROVED = "APPROVED"
_TRANSFER_EXPIRES_S = 300

_TOOL_DESCRIPTION = """Propose moving money between the user's linked bank and their Sevino brokerage account. One tool, two operations selected by `operation`:

- "deposit" — move money from the user's bank into Sevino (ACH, direction INCOMING).
- "withdraw" — move money from Sevino back to the user's bank (ACH, direction OUTGOING).

This tool does NOT move the money. It presents a confirmation card showing the amount and bank; the user must physically tap to confirm before the transfer runs. Never tell the user the transfer is done, scheduled, or in progress from this call — the result comes back to you only after they confirm.

Requires `amount` (US dollars, > 0). `bank_hint` is optional: pass it (a bank nickname, institution name, or last-4) only when the user has more than one linked bank and named which one. Behaviour:
- No linked bank → returns {"status":"error","code":"NO_LINKED_BANK"}: tell the user to link a bank first.
- Bank linked but still verifying → {"status":"error","code":"BANK_NOT_APPROVED"}.
- One usable bank → returns {"status":"proposal_presented", ...} and the confirmation card is shown.
- Multiple usable banks and the choice is unclear → {"status":"needs_clarification","banks":[...]}: ask the user which bank, then call again with `bank_hint`.

If the user tries to confirm in words ("yes", "do it"), do not treat that as confirmation — they must tap the card. Re-call this tool to present a fresh card."""


class TransferOperationsInput(BaseModel):
    operation: Literal["deposit", "withdraw"] = Field(
        ...,
        description=(
            '"deposit" to move money from the bank into Sevino, "withdraw" '
            "to move money from Sevino back to the bank."
        ),
    )
    amount: Decimal = Field(
        ...,
        gt=0,
        description=(
            "Amount in US dollars, greater than 0 (e.g. 500 or 500.00). "
            "Parse this from the user's request."
        ),
    )
    bank_hint: str | None = Field(
        default=None,
        description=(
            "Optional. A bank nickname, institution name, or last-4 digits "
            "to disambiguate when the user has more than one linked bank. "
            "Omit when the user has a single bank or hasn't named one."
        ),
    )


def _bank_brief(rel: AchRelationship) -> dict[str, Any]:
    return {
        "relationship_pk": str(rel.id),
        "nickname": rel.nickname,
        "institution": rel.institution_name,
        "mask": rel.account_mask,
    }


def _bank_label(rel: AchRelationship) -> str:
    name = rel.nickname or rel.institution_name or "Bank"
    return f"{name} ••{rel.account_mask}" if rel.account_mask else name


def _matches_hint(rel: AchRelationship, hint: str) -> bool:
    needle = hint.strip().lower()
    if not needle:
        return False
    for field in (rel.nickname, rel.institution_name, rel.account_mask):
        if field and needle in field.lower():
            return True
    return False


class TransferOperations(Tool[TransferOperationsInput]):
    name: ClassVar[str] = "transfer_operations"
    description: ClassVar[str] = _TOOL_DESCRIPTION
    Input: ClassVar[type[BaseModel]] = TransferOperationsInput

    async def execute(
        self, input: TransferOperationsInput, ctx: ToolContext
    ) -> ToolResult:
        operation = input.operation
        amount = input.amount.quantize(Decimal("0.01"))
        direction = "INCOMING" if operation == "deposit" else "OUTGOING"

        alpaca = ctx.http_clients.alpaca
        if alpaca is None:
            return ToolResult(
                model_payload={
                    "status": "error",
                    "code": "BROKERAGE_UNAVAILABLE",
                    "error": "Transfers are temporarily unavailable.",
                }
            )

        async with ctx.db_factory() as db:
            relationships = (
                await FundingService.list_active_ach_relationships(
                    db, alpaca=alpaca, user_id=ctx.user_id
                )
            )

        if not relationships:
            return ToolResult(
                model_payload={
                    "status": "error",
                    "code": "NO_LINKED_BANK",
                    "error": "No bank account is linked yet.",
                }
            )

        usable = [r for r in relationships if r.status == _APPROVED]
        if not usable:
            return ToolResult(
                model_payload={
                    "status": "error",
                    "code": "BANK_NOT_APPROVED",
                    "error": "The linked bank is still being verified.",
                }
            )

        bank = self._resolve_bank(usable, input.bank_hint)
        if bank is None:
            return ToolResult(
                model_payload={
                    "status": "needs_clarification",
                    "operation": operation,
                    "amount": str(amount),
                    "banks": [_bank_brief(r) for r in usable],
                }
            )

        action_id = str(uuid.uuid4())
        verb = "Deposit" if operation == "deposit" else "Withdrawal"
        amount_str = f"${amount:,.2f}"
        flow = (
            f"{_bank_label(bank)} → Sevino"
            if operation == "deposit"
            else f"Sevino → {_bank_label(bank)}"
        )
        card = ConfirmationBlock(
            block_id=str(ULID()),
            action_id=action_id,
            kind="transfer",
            title=f"Confirm {verb.lower()}",
            rows=[
                ConfirmationRow(label="Amount", value=amount_str),
                ConfirmationRow(label="Transfer", value=flow),
            ],
            details={
                "operation": operation,
                "direction": direction,
                "amount": str(amount),
                "currency": "USD",
                "bank_institution": bank.institution_name,
                "bank_mask": bank.account_mask,
                "bank_nickname": bank.nickname,
            },
            confirm_label=f"Confirm {verb.lower()}",
        )
        return ToolResult(
            model_payload={
                "status": "proposal_presented",
                "operation": operation,
                "amount": str(amount),
                "bank": _bank_brief(bank),
            },
            ui_block=card,
            proposal=ProposedAction(
                action_id=action_id,
                action_type="transfer",
                # ``relationship_pk`` / ``amount`` / ``direction`` drive
                # execution; the bank_* fields are display-only, carried so the
                # result receipt can name the bank without a re-lookup.
                payload={
                    "relationship_pk": str(bank.id),
                    "amount": str(amount),
                    "direction": direction,
                    "operation": operation,
                    "bank_institution": bank.institution_name,
                    "bank_mask": bank.account_mask,
                    "bank_nickname": bank.nickname,
                },
                expires_in_s=_TRANSFER_EXPIRES_S,
            ),
        )

    @staticmethod
    def _resolve_bank(
        usable: list[AchRelationship], hint: str | None
    ) -> AchRelationship | None:
        """Pick the single bank to transfer with, or None if it's ambiguous."""
        if hint:
            matches = [r for r in usable if _matches_hint(r, hint)]
            return matches[0] if len(matches) == 1 else None
        return usable[0] if len(usable) == 1 else None
