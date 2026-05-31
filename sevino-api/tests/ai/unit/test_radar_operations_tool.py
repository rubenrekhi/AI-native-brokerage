"""Unit tests for ``app.ai.tools.radar_operations`` (``radar_operations`` tool).

Covers all three operations and every terminal state the tool reports so the
agent loop never crashes on a radar interaction:

* get — lists items with human/ai source and the AI-pick reason; empty radar;
  works without market data; pill "Looking at your Radar".
* add happy path — pill active → complete, status "added", starred.
* add duplicate — ``RADAR_DUPLICATE_SYMBOL`` is a soft success ("already_on_radar").
* add not tradeable — ``SYMBOL_NOT_TRADEABLE`` fails the pill with the message.
* remove happy path / absent — "removed" / "not_on_radar", pill complete.
* missing symbol on add/remove — clean error, no pill.
* infra failure — any other exception → "temporarily unavailable", pill failed,
  and the exception escalates to Sentry (ConflictError does not).
* input validation — bad operation / empty / oversize symbol; get needs no symbol.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.ai.blocks import StatusBlock
from app.ai.tools import ToolContext, ToolHttpClients
from app.ai.tools.radar_operations import RadarOperations, RadarOperationsInput
from app.ai.transport.events import BlockData, BlockStart, Event
from app.exceptions import ConflictError


class _RecordingEmitter:
    """Test double for ``SSEEmitter`` — appends every event to a list."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    async def emit(self, event: Event) -> None:
        self.events.append(event)


def _make_ctx(
    *, market_data: Any | None = None
) -> tuple[ToolContext, _RecordingEmitter]:
    emitter = _RecordingEmitter()

    @asynccontextmanager
    async def db_factory():
        # RadarService is patched in each test, so the session is never used.
        yield MagicMock()

    ctx = ToolContext(
        user_id=uuid4(),
        db_factory=db_factory,
        sse_emitter=emitter,  # type: ignore[arg-type]
        http_clients=ToolHttpClients(market_data=market_data),
    )
    return ctx, emitter


def _patch_service(
    monkeypatch,
    *,
    add_return: Any = None,
    add_exc: Exception | None = None,
    remove_return: bool | None = None,
    remove_exc: Exception | None = None,
    list_return: list | None = None,
    list_exc: Exception | None = None,
) -> dict:
    """Replace ``radar_operations.RadarService`` with a fake that records its
    construction args and returns/raises whatever the test wants."""
    calls: dict = {}

    class FakeRadarService:
        def __init__(self, market_data, db):
            calls["market_data"] = market_data
            calls["db"] = db

        async def add_user_item(self, user_id, symbol):
            calls["add"] = (user_id, symbol)
            if add_exc is not None:
                raise add_exc
            return add_return

        async def remove_user_item_by_symbol(self, user_id, symbol):
            calls["remove"] = (user_id, symbol)
            if remove_exc is not None:
                raise remove_exc
            return remove_return

        async def list_items(self, user_id):
            calls["list"] = user_id
            if list_exc is not None:
                raise list_exc
            return list_return or []

    monkeypatch.setattr(
        "app.ai.tools.radar_operations.RadarService", FakeRadarService
    )
    return calls


def _item(company_name: str = "Apple Inc.", is_favorited: bool = True):
    return SimpleNamespace(
        company_name=company_name, is_favorited=is_favorited
    )


def _row(symbol: str, *, source: str, company_name: str = "Co.", reason=None):
    return SimpleNamespace(
        symbol=symbol,
        company_name=company_name,
        source=source,
        context_blurb=reason,
    )


class TestGet:
    async def test_lists_items_with_source_and_reason(self, monkeypatch):
        calls = _patch_service(
            monkeypatch,
            list_return=[
                _row("AAPL", source="user_added", company_name="Apple Inc."),
                _row(
                    "NVDA",
                    source="ai_generated",
                    company_name="NVIDIA Corp",
                    reason="Leading AI-chip maker riding datacenter demand",
                ),
            ],
        )
        ctx, emitter = _make_ctx()

        result = await RadarOperations().execute(
            RadarOperationsInput(operation="get"), ctx
        )

        assert calls["list"] == ctx.user_id
        assert result.model_payload == {
            "operation": "get",
            "count": 2,
            "items": [
                {
                    "symbol": "AAPL",
                    "company_name": "Apple Inc.",
                    "added_by": "human",
                },
                {
                    "symbol": "NVDA",
                    "company_name": "NVIDIA Corp",
                    "added_by": "ai",
                    "reason": "Leading AI-chip maker riding datacenter demand",
                },
            ],
        }
        # Human rows carry no "reason" key; AI rows do.
        assert "reason" not in result.model_payload["items"][0]
        assert isinstance(result.ui_block, StatusBlock)
        assert result.ui_block.state == "complete"
        assert result.ui_block.label == "Looking at your Radar"

    async def test_empty_radar_returns_zero_count(self, monkeypatch):
        _patch_service(monkeypatch, list_return=[])
        ctx, emitter = _make_ctx()

        result = await RadarOperations().execute(
            RadarOperationsInput(operation="get"), ctx
        )

        assert result.model_payload == {
            "operation": "get",
            "count": 0,
            "items": [],
        }
        assert result.ui_block is not None
        assert result.ui_block.state == "complete"

    async def test_emits_active_then_complete_pill(self, monkeypatch):
        _patch_service(monkeypatch, list_return=[])
        ctx, emitter = _make_ctx()

        await RadarOperations().execute(
            RadarOperationsInput(operation="get"), ctx
        )

        assert len(emitter.events) == 2
        start, patch = emitter.events
        assert isinstance(start, BlockStart)
        assert start.block["state"] == "active"
        assert start.block["label"] == "Looking at your Radar"
        assert isinstance(patch, BlockData)
        assert patch.block_id == start.block["block_id"]
        assert patch.data["state"] == "complete"

    async def test_works_without_market_data(self, monkeypatch):
        calls = _patch_service(
            monkeypatch, list_return=[_row("AAPL", source="user_added")]
        )
        ctx, _ = _make_ctx(market_data=None)

        result = await RadarOperations().execute(
            RadarOperationsInput(operation="get"), ctx
        )

        assert calls["market_data"] is None
        assert result.model_payload["count"] == 1

    async def test_infra_error_returns_temporary_failure(self, monkeypatch):
        _patch_service(monkeypatch, list_exc=RuntimeError("db down"))
        ctx, emitter = _make_ctx()

        result = await RadarOperations().execute(
            RadarOperationsInput(operation="get"), ctx
        )

        assert result.model_payload["status"] == "error"
        assert result.model_payload["error"] == (
            "Your radar is temporarily unavailable."
        )
        assert result.ui_block is not None
        assert result.ui_block.state == "failed"


class TestAdd:
    async def test_happy_path_adds_starred_and_completes_pill(self, monkeypatch):
        calls = _patch_service(monkeypatch, add_return=_item())
        ctx, emitter = _make_ctx()

        result = await RadarOperations().execute(
            RadarOperationsInput(operation="add", symbol="aapl"), ctx
        )

        assert calls["add"] == (ctx.user_id, "AAPL")
        assert result.model_payload == {
            "operation": "add",
            "symbol": "AAPL",
            "status": "added",
            "company_name": "Apple Inc.",
            "starred": True,
        }
        assert isinstance(result.ui_block, StatusBlock)
        assert result.ui_block.state == "complete"
        assert result.ui_block.label == "Adding $AAPL to your radar"

    async def test_emits_active_then_complete_with_same_block_id(
        self, monkeypatch
    ):
        _patch_service(monkeypatch, add_return=_item())
        ctx, emitter = _make_ctx()

        result = await RadarOperations().execute(
            RadarOperationsInput(operation="add", symbol="AAPL"), ctx
        )

        assert len(emitter.events) == 2
        start, patch = emitter.events
        assert isinstance(start, BlockStart)
        assert start.block["state"] == "active"
        assert start.block["label"] == "Adding $AAPL to your radar"
        assert isinstance(patch, BlockData)
        assert patch.block_id == start.block["block_id"]
        assert patch.data["state"] == "complete"
        assert result.ui_block is not None
        assert result.ui_block.block_id == start.block["block_id"]

    async def test_duplicate_is_soft_success(self, monkeypatch):
        _patch_service(
            monkeypatch,
            add_exc=ConflictError(
                "AAPL is already on your radar.",
                code="RADAR_DUPLICATE_SYMBOL",
                detail={"symbol": "AAPL"},
            ),
        )
        ctx, emitter = _make_ctx()

        result = await RadarOperations().execute(
            RadarOperationsInput(operation="add", symbol="AAPL"), ctx
        )

        assert result.model_payload == {
            "operation": "add",
            "symbol": "AAPL",
            "status": "already_on_radar",
        }
        assert result.ui_block is not None
        assert result.ui_block.state == "complete"
        assert emitter.events[-1].data["state"] == "complete"

    async def test_not_tradeable_fails_pill_with_message(self, monkeypatch):
        _patch_service(
            monkeypatch,
            add_exc=ConflictError(
                "ZZZZ is not available for trading.",
                code="SYMBOL_NOT_TRADEABLE",
                detail={"symbol": "ZZZZ"},
            ),
        )
        ctx, emitter = _make_ctx()

        result = await RadarOperations().execute(
            RadarOperationsInput(operation="add", symbol="ZZZZ"), ctx
        )

        assert result.model_payload == {
            "operation": "add",
            "symbol": "ZZZZ",
            "status": "error",
            "error": "ZZZZ is not available for trading.",
        }
        assert result.ui_block is not None
        assert result.ui_block.state == "failed"
        assert emitter.events[-1].data["state"] == "failed"

    async def test_infra_error_returns_temporary_failure(self, monkeypatch):
        _patch_service(monkeypatch, add_exc=RuntimeError("db down"))
        ctx, emitter = _make_ctx()

        result = await RadarOperations().execute(
            RadarOperationsInput(operation="add", symbol="AAPL"), ctx
        )

        assert result.model_payload == {
            "operation": "add",
            "symbol": "AAPL",
            "status": "error",
            "error": "Your radar is temporarily unavailable.",
        }
        assert result.ui_block is not None
        assert result.ui_block.state == "failed"

    async def test_unexpected_error_escalates_to_sentry(self, monkeypatch):
        boom = RuntimeError("db down")
        _patch_service(monkeypatch, add_exc=boom)
        captured: list[BaseException] = []
        monkeypatch.setattr(
            "app.ai.tools.radar_operations.sentry_sdk.capture_exception",
            captured.append,
        )
        ctx, _ = _make_ctx()

        result = await RadarOperations().execute(
            RadarOperationsInput(operation="add", symbol="AAPL"), ctx
        )

        assert captured == [boom]
        assert result.ui_block is not None
        assert result.ui_block.state == "failed"

    async def test_conflict_error_does_not_escalate_to_sentry(self, monkeypatch):
        _patch_service(
            monkeypatch,
            add_exc=ConflictError(
                "ZZZZ is not available for trading.",
                code="SYMBOL_NOT_TRADEABLE",
                detail={"symbol": "ZZZZ"},
            ),
        )
        captured: list[BaseException] = []
        monkeypatch.setattr(
            "app.ai.tools.radar_operations.sentry_sdk.capture_exception",
            captured.append,
        )
        ctx, _ = _make_ctx()

        await RadarOperations().execute(
            RadarOperationsInput(operation="add", symbol="ZZZZ"), ctx
        )

        assert captured == []

    async def test_works_without_market_data(self, monkeypatch):
        calls = _patch_service(monkeypatch, add_return=_item())
        ctx, _ = _make_ctx(market_data=None)

        result = await RadarOperations().execute(
            RadarOperationsInput(operation="add", symbol="AAPL"), ctx
        )

        assert calls["market_data"] is None
        assert result.model_payload["status"] == "added"

    async def test_missing_symbol_errors_without_pill(self, monkeypatch):
        calls = _patch_service(monkeypatch, add_return=_item())
        ctx, emitter = _make_ctx()

        result = await RadarOperations().execute(
            RadarOperationsInput(operation="add"), ctx
        )

        assert result.model_payload == {
            "operation": "add",
            "status": "error",
            "error": (
                "A ticker symbol is required to add or remove a radar item."
            ),
        }
        assert result.ui_block is None
        assert emitter.events == []
        assert "add" not in calls  # service never touched


class TestRemove:
    async def test_happy_path_removes_and_completes_pill(self, monkeypatch):
        calls = _patch_service(monkeypatch, remove_return=True)
        ctx, emitter = _make_ctx()

        result = await RadarOperations().execute(
            RadarOperationsInput(operation="remove", symbol="tsla"), ctx
        )

        assert calls["remove"] == (ctx.user_id, "TSLA")
        assert result.model_payload == {
            "operation": "remove",
            "symbol": "TSLA",
            "status": "removed",
        }
        assert isinstance(result.ui_block, StatusBlock)
        assert result.ui_block.state == "complete"
        assert result.ui_block.label == "Removing $TSLA from your radar"

    async def test_absent_symbol_reports_not_on_radar(self, monkeypatch):
        _patch_service(monkeypatch, remove_return=False)
        ctx, emitter = _make_ctx()

        result = await RadarOperations().execute(
            RadarOperationsInput(operation="remove", symbol="TSLA"), ctx
        )

        assert result.model_payload == {
            "operation": "remove",
            "symbol": "TSLA",
            "status": "not_on_radar",
        }
        # Idempotent — the absence the user wanted holds, so it's not an error.
        assert result.ui_block is not None
        assert result.ui_block.state == "complete"

    async def test_infra_error_returns_temporary_failure(self, monkeypatch):
        _patch_service(monkeypatch, remove_exc=RuntimeError("db down"))
        ctx, emitter = _make_ctx()

        result = await RadarOperations().execute(
            RadarOperationsInput(operation="remove", symbol="TSLA"), ctx
        )

        assert result.model_payload["status"] == "error"
        assert result.ui_block is not None
        assert result.ui_block.state == "failed"

    async def test_missing_symbol_errors_without_pill(self, monkeypatch):
        calls = _patch_service(monkeypatch, remove_return=True)
        ctx, emitter = _make_ctx()

        result = await RadarOperations().execute(
            RadarOperationsInput(operation="remove"), ctx
        )

        assert result.model_payload["status"] == "error"
        assert result.ui_block is None
        assert emitter.events == []
        assert "remove" not in calls


class TestInputValidation:
    def test_invalid_operation_rejected(self):
        with pytest.raises(ValidationError):
            RadarOperationsInput(operation="toggle", symbol="AAPL")

    def test_empty_symbol_rejected(self):
        with pytest.raises(ValidationError):
            RadarOperationsInput(operation="add", symbol="")

    def test_oversize_symbol_rejected(self):
        with pytest.raises(ValidationError):
            RadarOperationsInput(operation="add", symbol="AAAAAAAAAAA")

    def test_get_without_symbol_is_valid(self):
        validated = RadarOperationsInput(operation="get")
        assert validated.symbol is None

    def test_lowercase_symbol_accepted_and_preserved(self):
        validated = RadarOperationsInput(operation="add", symbol="aapl")
        assert validated.symbol == "aapl"
