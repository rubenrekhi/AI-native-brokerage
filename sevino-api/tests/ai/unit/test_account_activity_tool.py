"""Unit tests for ``app.ai.tools.account_activity`` (``get_account_activity``).

Covers the pill lifecycle and every terminal state so the agent loop never
crashes on an activity lookup:

* happy path — active → complete pill; the service payload is the model payload.
* symbol is upper-cased before reaching the service.
* alpaca client absent — soft error, pill failed, service never called.
* no brokerage account (``NotFoundError``) — soft error, pill failed.
* upstream down (``AlpacaBrokerUnavailableError``) — "temporarily unavailable".
* unexpected error — "temporarily unavailable", pill failed, escalates to Sentry.
* input validation — types/symbol/limit bounds.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

import app.ai.tools.account_activity as tool_mod
from app.ai.blocks import StatusBlock
from app.ai.tools import ToolContext, ToolHttpClients
from app.ai.tools.account_activity import (
    AccountActivityInput,
    GetAccountActivity,
)
from app.ai.transport.events import BlockData, BlockStart, Event
from app.exceptions import NotFoundError
from app.services.alpaca_broker import AlpacaBrokerUnavailableError

_LABEL = "Looking at your account activity"


class _RecordingEmitter:
    def __init__(self) -> None:
        self.events: list[Event] = []

    async def emit(self, event: Event) -> None:
        self.events.append(event)


def _make_ctx(
    *, alpaca: Any | None = SimpleNamespace()
) -> tuple[ToolContext, _RecordingEmitter]:
    emitter = _RecordingEmitter()

    @asynccontextmanager
    async def db_factory():
        # ActivityService is patched in each test, so the session is unused.
        yield MagicMock()

    ctx = ToolContext(
        user_id=uuid4(),
        db_factory=db_factory,
        sse_emitter=emitter,  # type: ignore[arg-type]
        http_clients=ToolHttpClients(alpaca=alpaca),
    )
    return ctx, emitter


def _patch_service(monkeypatch, *, return_value=None, side_effect=None) -> AsyncMock:
    mock = AsyncMock(return_value=return_value, side_effect=side_effect)
    monkeypatch.setattr(tool_mod.ActivityService, "get_activity", mock)
    return mock


class TestHappyPath:
    async def test_returns_service_payload_and_completes_pill(self, monkeypatch):
        payload = {
            "count": 1,
            "totals": {"executed_trades": 1, "open_orders": 0},
            "activities": [{"type": "trade"}],
        }
        _patch_service(monkeypatch, return_value=payload)
        ctx, emitter = _make_ctx()

        result = await GetAccountActivity().execute(
            AccountActivityInput(activity_types=["trade"]), ctx
        )

        assert result.model_payload == payload
        assert isinstance(result.ui_block, StatusBlock)
        assert result.ui_block.state == "complete"
        assert result.ui_block.label == _LABEL

    async def test_emits_active_then_complete_same_block_id(self, monkeypatch):
        _patch_service(monkeypatch, return_value={"count": 0})
        ctx, emitter = _make_ctx()

        result = await GetAccountActivity().execute(AccountActivityInput(), ctx)

        assert len(emitter.events) == 2
        start, patch = emitter.events
        assert isinstance(start, BlockStart)
        assert start.block["state"] == "active"
        assert start.block["label"] == _LABEL
        assert isinstance(patch, BlockData)
        assert patch.block_id == start.block["block_id"]
        assert patch.data["state"] == "complete"
        assert result.ui_block is not None
        assert result.ui_block.block_id == start.block["block_id"]

    async def test_symbol_upper_cased_and_args_forwarded(self, monkeypatch):
        mock = _patch_service(monkeypatch, return_value={"count": 0})
        ctx, _ = _make_ctx()

        await GetAccountActivity().execute(
            AccountActivityInput(
                symbol="aapl",
                activity_types=["dividend"],
                after="2026-05-01",
                until="2026-05-31",
                include_canceled=True,
                limit=25,
            ),
            ctx,
        )

        kwargs = mock.await_args.kwargs
        assert kwargs["symbol"] == "AAPL"
        assert kwargs["types"] == ["dividend"]
        assert kwargs["after"] == "2026-05-01"
        assert kwargs["until"] == "2026-05-31"
        assert kwargs["include_canceled"] is True
        assert kwargs["limit"] == 25
        assert kwargs["user_id"] == ctx.user_id


class TestErrorPaths:
    async def test_missing_alpaca_client_soft_errors_without_calling_service(
        self, monkeypatch
    ):
        mock = _patch_service(monkeypatch, return_value={"count": 0})
        ctx, emitter = _make_ctx(alpaca=None)

        result = await GetAccountActivity().execute(AccountActivityInput(), ctx)

        assert "error" in result.model_payload
        assert result.ui_block is not None
        assert result.ui_block.state == "failed"
        mock.assert_not_awaited()

    async def test_no_brokerage_account_soft_errors(self, monkeypatch):
        _patch_service(monkeypatch, side_effect=NotFoundError("no account"))
        ctx, emitter = _make_ctx()

        result = await GetAccountActivity().execute(AccountActivityInput(), ctx)

        assert "brokerage account" in result.model_payload["error"]
        assert result.ui_block is not None
        assert result.ui_block.state == "failed"
        assert emitter.events[-1].data["state"] == "failed"

    async def test_upstream_unavailable_returns_temporary_failure(self, monkeypatch):
        _patch_service(
            monkeypatch, side_effect=AlpacaBrokerUnavailableError("down")
        )
        ctx, _ = _make_ctx()

        result = await GetAccountActivity().execute(AccountActivityInput(), ctx)

        assert result.model_payload["error"] == (
            "Your account activity is temporarily unavailable."
        )
        assert result.ui_block is not None
        assert result.ui_block.state == "failed"

    async def test_unexpected_error_escalates_to_sentry(self, monkeypatch):
        boom = RuntimeError("kaboom")
        _patch_service(monkeypatch, side_effect=boom)
        captured: list[BaseException] = []
        monkeypatch.setattr(
            tool_mod.sentry_sdk, "capture_exception", captured.append
        )
        ctx, _ = _make_ctx()

        result = await GetAccountActivity().execute(AccountActivityInput(), ctx)

        assert captured == [boom]
        assert result.ui_block is not None
        assert result.ui_block.state == "failed"
        assert result.model_payload["error"] == (
            "Your account activity is temporarily unavailable."
        )


class TestInputValidation:
    def test_defaults_are_all_none_and_limit_50(self):
        validated = AccountActivityInput()
        assert validated.activity_types is None
        assert validated.symbol is None
        assert validated.include_canceled is False
        assert validated.limit == 50

    def test_invalid_activity_type_rejected(self):
        with pytest.raises(ValidationError):
            AccountActivityInput(activity_types=["fee"])

    def test_limit_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            AccountActivityInput(limit=0)
        with pytest.raises(ValidationError):
            AccountActivityInput(limit=201)

    def test_oversize_symbol_rejected(self):
        with pytest.raises(ValidationError):
            AccountActivityInput(symbol="AAAAAAAAAAA")

    def test_lowercase_symbol_accepted_and_preserved(self):
        validated = AccountActivityInput(symbol="aapl")
        assert validated.symbol == "aapl"
