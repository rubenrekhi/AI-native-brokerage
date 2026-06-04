"""Unit tests for the ``transfer`` action handler."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.ai.actions.base import ActionContext
from app.ai.actions.transfer import TransferActionHandler
from app.ai.tools.base import ToolHttpClients
from app.exceptions import ConflictError
from app.services.alpaca_broker import (
    AlpacaBrokerError,
    AlpacaBrokerUnavailableError,
)

_PAYLOAD = {
    "relationship_pk": str(uuid4()),
    "amount": "500.00",
    "direction": "INCOMING",
    "operation": "deposit",
    "bank_institution": "Chase",
    "bank_mask": "1234",
    "bank_nickname": "Checking",
}


def _ctx(*, alpaca=MagicMock()):
    @asynccontextmanager
    async def db_factory():
        yield MagicMock()

    return ActionContext(
        user_id=uuid4(),
        db_factory=db_factory,
        http_clients=ToolHttpClients(alpaca=alpaca),
    )


def _patch_create(monkeypatch, *, return_value=None, side_effect=None):
    monkeypatch.setattr(
        "app.ai.actions.transfer.FundingService.create_transfer",
        AsyncMock(return_value=return_value, side_effect=side_effect),
    )


async def test_execute_success_returns_executed_resume_prompt(monkeypatch):
    _patch_create(
        monkeypatch, return_value={"id": "xfer_1", "status": "QUEUED"}
    )
    result = await TransferActionHandler().execute(_PAYLOAD, _ctx())
    assert result.status == "executed"
    assert "$500.00" in result.resume_prompt
    # The seed instructs the model to narrate success (not assert it itself).
    assert "went through" in result.resume_prompt
    # Bug A regression: the seed must not invite re-proposing on the resume turn.
    assert "do not call the transfer tool again" in result.resume_prompt.lower()
    assert result.summary == {"amount": "500.00", "direction": "INCOMING"}


async def test_execute_business_error_uses_curated_reason(monkeypatch):
    _patch_create(
        monkeypatch,
        side_effect=ConflictError(
            "This bank is still being verified.",
            code="RELATIONSHIP_NOT_APPROVED",
        ),
    )
    result = await TransferActionHandler().execute(_PAYLOAD, _ctx())
    assert result.status == "failed"
    assert "still being verified" in result.resume_prompt
    assert "do not claim the transfer succeeded".lower() in result.resume_prompt.lower()
    assert "do not call the transfer tool again" in result.resume_prompt.lower()


async def test_execute_alpaca_error_does_not_leak_raw_text(monkeypatch):
    _patch_create(
        monkeypatch,
        side_effect=AlpacaBrokerError(422, "internal alpaca phrasing xyz"),
    )
    result = await TransferActionHandler().execute(_PAYLOAD, _ctx())
    assert result.status == "failed"
    assert "xyz" not in result.resume_prompt


async def test_execute_insufficient_withdrawable_explains_settlement(monkeypatch):
    _patch_create(
        monkeypatch,
        side_effect=AlpacaBrokerError(
            403,
            "transfer amount must be less than or equal to withdrawable cash",
            detail={
                "code": 40310000,
                "message": "transfer amount must be less than or equal to withdrawable cash",
            },
        ),
    )
    result = await TransferActionHandler().execute(
        {**_PAYLOAD, "direction": "OUTGOING", "operation": "withdraw"}, _ctx()
    )
    assert result.status == "failed"
    reason = result.resume_prompt.lower()
    assert "settle" in reason and "withdraw" in reason
    # The curated reason explains the cause without echoing raw Alpaca phrasing.
    assert "withdrawable cash" not in result.resume_prompt


async def test_execute_duplicate_transfer_is_explained(monkeypatch):
    _patch_create(
        monkeypatch,
        side_effect=AlpacaBrokerError(
            422,
            "duplicate transfer request",
            detail={"message": "duplicate transfer request"},
        ),
    )
    result = await TransferActionHandler().execute(_PAYLOAD, _ctx())
    assert result.status == "failed"
    assert "duplicate" in result.resume_prompt.lower()


async def test_execute_unavailable_does_not_leak(monkeypatch):
    _patch_create(
        monkeypatch,
        side_effect=AlpacaBrokerUnavailableError("Connection timeout to host"),
    )
    result = await TransferActionHandler().execute(_PAYLOAD, _ctx())
    assert result.status == "failed"
    assert "Connection timeout" not in result.resume_prompt


async def test_execute_unexpected_error_degrades(monkeypatch):
    _patch_create(monkeypatch, side_effect=RuntimeError("db exploded"))
    result = await TransferActionHandler().execute(_PAYLOAD, _ctx())
    assert result.status == "failed"
    assert "db exploded" not in result.resume_prompt


async def test_execute_without_alpaca_fails():
    result = await TransferActionHandler().execute(
        _PAYLOAD, _ctx(alpaca=None)
    )
    assert result.status == "failed"


def test_reject_prompt_is_per_type():
    rp = TransferActionHandler().reject_prompt(_PAYLOAD)
    assert "declined" in rp
    assert "deposit" in rp
    assert "$500.00" in rp
