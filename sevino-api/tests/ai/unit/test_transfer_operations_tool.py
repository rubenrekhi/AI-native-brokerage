"""Unit tests for the ``transfer_operations`` propose tool."""

from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.ai.blocks import ConfirmationBlock
from app.ai.tools.base import ToolContext, ToolHttpClients
from app.ai.tools.transfer_operations import (
    TransferOperations,
    TransferOperationsInput,
)


def _rel(
    *,
    status="APPROVED",
    nickname=None,
    institution="Chase",
    mask="1234",
):
    return SimpleNamespace(
        id=uuid4(),
        status=status,
        institution_name=institution,
        account_mask=mask,
        nickname=nickname,
        account_type="CHECKING",
    )


def _make_ctx(*, alpaca=MagicMock()):
    @asynccontextmanager
    async def db_factory():
        yield MagicMock()

    ctx = ToolContext(
        user_id=uuid4(),
        db_factory=db_factory,
        sse_emitter=MagicMock(),
        http_clients=ToolHttpClients(alpaca=alpaca),
    )
    return ctx


def _patch_list(monkeypatch, rels):
    monkeypatch.setattr(
        "app.ai.tools.transfer_operations.FundingService."
        "list_active_ach_relationships",
        AsyncMock(return_value=rels),
    )


async def _run(monkeypatch, rels, **input_kwargs):
    _patch_list(monkeypatch, rels)
    return await TransferOperations().execute(
        TransferOperationsInput(**input_kwargs), _make_ctx()
    )


async def test_deposit_happy_proposes_incoming(monkeypatch):
    bank = _rel(nickname="Checking")
    result = await _run(
        monkeypatch, [bank], operation="deposit", amount=Decimal("500")
    )
    assert result.model_payload["status"] == "proposal_presented"
    assert result.proposal is not None
    assert result.proposal.action_type == "transfer"
    assert result.proposal.payload["relationship_pk"] == str(bank.id)
    assert result.proposal.payload["direction"] == "INCOMING"
    assert result.proposal.payload["amount"] == "500.00"
    assert isinstance(result.ui_block, ConfirmationBlock)
    assert result.ui_block.kind == "transfer"
    assert result.ui_block.action_id == result.proposal.action_id
    assert result.ui_block.details["direction"] == "INCOMING"


async def test_withdraw_proposes_outgoing(monkeypatch):
    result = await _run(
        monkeypatch, [_rel()], operation="withdraw", amount=Decimal("200.5")
    )
    assert result.proposal.payload["direction"] == "OUTGOING"
    assert result.proposal.payload["amount"] == "200.50"


async def test_no_linked_bank_returns_error_without_proposal(monkeypatch):
    result = await _run(
        monkeypatch, [], operation="deposit", amount=Decimal("100")
    )
    assert result.proposal is None
    assert result.ui_block is None
    assert result.model_payload["code"] == "NO_LINKED_BANK"


async def test_bank_not_approved_blocks_proposal(monkeypatch):
    result = await _run(
        monkeypatch,
        [_rel(status="QUEUED")],
        operation="deposit",
        amount=Decimal("100"),
    )
    assert result.proposal is None
    assert result.model_payload["code"] == "BANK_NOT_APPROVED"


async def test_multiple_banks_no_hint_needs_clarification(monkeypatch):
    rels = [_rel(nickname="Checking"), _rel(nickname="Savings")]
    result = await _run(
        monkeypatch, rels, operation="deposit", amount=Decimal("100")
    )
    assert result.proposal is None
    assert result.model_payload["status"] == "needs_clarification"
    assert len(result.model_payload["banks"]) == 2


async def test_hint_resolves_single_bank(monkeypatch):
    checking = _rel(nickname="Checking", mask="1111")
    savings = _rel(nickname="Savings", mask="2222")
    result = await _run(
        monkeypatch,
        [checking, savings],
        operation="deposit",
        amount=Decimal("100"),
        bank_hint="savings",
    )
    assert result.proposal is not None
    assert result.proposal.payload["relationship_pk"] == str(savings.id)


async def test_hint_matching_multiple_is_ambiguous(monkeypatch):
    # Both share the institution name "Chase" → hint matches both.
    rels = [_rel(nickname="A", mask="1111"), _rel(nickname="B", mask="2222")]
    result = await _run(
        monkeypatch,
        rels,
        operation="deposit",
        amount=Decimal("100"),
        bank_hint="chase",
    )
    assert result.proposal is None
    assert result.model_payload["status"] == "needs_clarification"


async def test_hint_matching_no_bank_needs_clarification(monkeypatch):
    rels = [_rel(nickname="Checking", mask="1111"), _rel(nickname="Savings")]
    result = await _run(
        monkeypatch,
        rels,
        operation="deposit",
        amount=Decimal("100"),
        bank_hint="nonexistent-bank",
    )
    assert result.proposal is None
    assert result.model_payload["status"] == "needs_clarification"


async def test_brokerage_unavailable_when_no_alpaca():
    ctx = _make_ctx(alpaca=None)
    result = await TransferOperations().execute(
        TransferOperationsInput(operation="deposit", amount=Decimal("100")),
        ctx,
    )
    assert result.proposal is None
    assert result.model_payload["code"] == "BROKERAGE_UNAVAILABLE"
