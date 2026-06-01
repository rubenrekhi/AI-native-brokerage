"""Unit tests for the ``transfer`` action executor."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.ai.actions.base import ActionContext
from app.ai.actions.transfer import execute_transfer
from app.ai.blocks import ConfirmationBlock
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


async def test_execute_success_returns_executed_receipt(monkeypatch):
    _patch_create(
        monkeypatch,
        return_value={
            "id": "xfer_1",
            "status": "QUEUED",
            "amount": "500.00",
            "direction": "INCOMING",
        },
    )
    result = await execute_transfer(_PAYLOAD, _ctx())
    assert result.status == "executed"
    assert result.summary["transfer_id"] == "xfer_1"
    assert isinstance(result.result_block, ConfirmationBlock)
    assert result.result_block.status == "executed"
    assert result.result_block.hold_to_confirm is False
    assert "500.00" in result.narration


async def test_execute_business_error_returns_failed(monkeypatch):
    _patch_create(
        monkeypatch,
        side_effect=ConflictError(
            "The linked bank is still being verified.",
            code="RELATIONSHIP_NOT_APPROVED",
        ),
    )
    result = await execute_transfer(_PAYLOAD, _ctx())
    assert result.status == "failed"
    assert result.result_block.status == "failed"
    assert "still being verified" in result.narration
    assert "error" in result.summary


async def test_upstream_error_uses_generic_reason_not_raw_text(monkeypatch):
    _patch_create(
        monkeypatch,
        side_effect=AlpacaBrokerUnavailableError("Connection timeout to host"),
    )
    result = await execute_transfer(_PAYLOAD, _ctx())
    assert result.status == "failed"
    # Raw upstream/network text must not leak to the user.
    assert "Connection timeout" not in result.narration
    assert "brokerage" in result.narration.lower()


async def test_alpaca_4xx_does_not_leak_upstream_message(monkeypatch):
    _patch_create(
        monkeypatch,
        side_effect=AlpacaBrokerError(422, "internal alpaca phrasing xyz"),
    )
    result = await execute_transfer(_PAYLOAD, _ctx())
    assert result.status == "failed"
    assert "xyz" not in result.narration


async def test_unexpected_exception_degrades_to_failed_receipt(monkeypatch):
    _patch_create(monkeypatch, side_effect=RuntimeError("db exploded"))
    result = await execute_transfer(_PAYLOAD, _ctx())
    assert result.status == "failed"
    assert result.result_block is not None
    assert "db exploded" not in result.narration


async def test_execute_without_alpaca_fails_gracefully():
    result = await execute_transfer(_PAYLOAD, _ctx(alpaca=None))
    assert result.status == "failed"
    assert result.result_block is not None
