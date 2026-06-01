"""Integration test: ``get_account_activity`` through the real agent loop.

Drives ``run_agent_turn`` against real local Postgres with a mocked Anthropic
client scripting a two-iteration tool-use turn (tool_use → tool_result →
end_turn) and a mocked Alpaca broker. Exercises what the unit tests can't:

* ``require_brokerage`` resolves the real ``brokerage_accounts`` row and the
  resolved ``alpaca_account_id`` reaches the broker calls.
* The normalized payload is persisted to ``tool_executions.output_payload`` and
  fed back to Anthropic as the next iteration's ``tool_result`` content.
* The status pill surfaces on the SSE wire through the real dispatch path.
* A missing brokerage account degrades to a soft error, and the loop still
  ends cleanly.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import anthropic
import pytest
from anthropic.types import (
    Message,
    RawContentBlockDeltaEvent,
    RawContentBlockStartEvent,
    RawContentBlockStopEvent,
    TextBlock as AnthropicTextBlock,
    TextDelta as AnthropicTextDelta,
    ToolUseBlock,
    Usage,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.observability.langfuse import _NoopLangfuse
from app.ai.prompts import SystemPrompt
from app.ai.runtime.caps import HardCaps
from app.ai.runtime.db import make_session_factory
from app.ai.runtime.loop import run_agent_turn
from app.ai.runtime.types import ModelConfig
from app.ai.tools import ToolHttpClients, ToolRegistry
from app.ai.tools.account_activity import GetAccountActivity
from app.ai.transport.emitter import SSEEmitter
from app.ai.transport.events import BlockData, BlockStart, Event, TextDelta
from app.models.agent_turn import AgentTurn
from app.models.model_invocation import ModelInvocation
from app.models.tool_execution import ToolExecution
from app.repositories.conversation import ConversationRepository
from tests.integration.conftest import _pg_available_sync, insert_auth_user

pytestmark = pytest.mark.skipif(
    not _pg_available_sync,
    reason="Local Supabase Postgres not available (run `make infra`)",
)

MODEL_ID = "claude-sonnet-4-6"
SYSTEM_PROMPT = SystemPrompt(text="you are sevino", hash="hash-activity")
TOOL_USE_ID = "toolu_activity_001"
PILL_LABEL = "Looking at your account activity"


# ---------- Alpaca broker mock ----------


def _mock_alpaca() -> MagicMock:
    """Broker stub returning one in-window record per activity type, plus two
    records that must be filtered out (a canceled order and a withholding)."""
    alpaca = MagicMock()
    alpaca.list_orders = AsyncMock(
        return_value=[
            {
                "id": "o_buy",
                "symbol": "AAPL",
                "side": "buy",
                "status": "filled",
                "filled_qty": "3",
                "filled_avg_price": "180.0700",
                "filled_at": "2026-05-20T14:31:00Z",
            },
            {
                "id": "o_sell",
                "symbol": "TSLA",
                "side": "sell",
                "status": "filled",
                "filled_qty": "2",
                "filled_avg_price": "250.00",
                "filled_at": "2026-05-10T15:00:00Z",
            },
            {
                "id": "o_canceled",
                "symbol": "NVDA",
                "side": "buy",
                "status": "canceled",
                "filled_qty": "0",
                "submitted_at": "2026-05-09T15:00:00Z",
            },
        ]
    )
    alpaca.list_transfers = AsyncMock(
        return_value=[
            {
                "id": "tr_in",
                "direction": "INCOMING",
                "amount": "200.00",
                "status": "COMPLETE",
                "created_at": "2026-05-18T00:00:00Z",
            },
            {
                "id": "tr_out",
                "direction": "OUTGOING",
                "amount": "50.00",
                "status": "COMPLETE",
                "created_at": "2026-05-19T00:00:00Z",
            },
        ]
    )
    alpaca.get_dividend_activities = AsyncMock(
        return_value=[
            {
                "id": "div_pay",
                "symbol": "MSFT",
                "net_amount": "3.12",
                "status": "executed",
                "created_at": "2026-05-15T00:00:00Z",
            },
            {
                "id": "div_withholding",
                "symbol": "MSFT",
                "net_amount": "-0.47",
                "status": "executed",
                "created_at": "2026-05-15T00:00:00Z",
            },
        ]
    )
    alpaca.get_interest_activities = AsyncMock(
        return_value=[
            {
                "id": "int_sweep",
                "symbol": "SWEEPFDIC",
                "net_amount": "1.05",
                "status": "executed",
                "date": "2026-05-31",
                "description": "May Sweep",
            },
        ]
    )
    return alpaca


# ---------- Anthropic stub ----------


class _FakeStream:
    def __init__(self, events: list[Any], final: Message) -> None:
        self._events = events
        self._index = 0
        self._final = final

    def __aiter__(self) -> "_FakeStream":
        return self

    async def __anext__(self) -> Any:
        if self._index >= len(self._events):
            raise StopAsyncIteration
        event = self._events[self._index]
        self._index += 1
        return event

    async def get_final_message(self) -> Message:
        return self._final

    async def close(self) -> None:
        return None


class _FakeStreamManager:
    def __init__(self, stream: _FakeStream) -> None:
        self._stream = stream

    async def __aenter__(self) -> _FakeStream:
        return self._stream

    async def __aexit__(self, *exc: Any) -> None:
        await self._stream.close()


def _events_for(message: Message) -> list[Any]:
    events: list[Any] = []
    for index, block in enumerate(message.content):
        if block.type == "text":
            start_block: Any = AnthropicTextBlock(
                text="", type="text", citations=None
            )
        else:
            start_block = block
        events.append(
            RawContentBlockStartEvent(
                content_block=start_block, index=index, type="content_block_start"
            )
        )
        if block.type == "text" and block.text:
            events.append(
                RawContentBlockDeltaEvent(
                    delta=AnthropicTextDelta(text=block.text, type="text_delta"),
                    index=index,
                    type="content_block_delta",
                )
            )
        events.append(
            RawContentBlockStopEvent(index=index, type="content_block_stop")
        )
    return events


def _stub_client(responses: list[Message]) -> AsyncMock:
    client = AsyncMock(spec=anthropic.AsyncAnthropic)
    managers = [
        _FakeStreamManager(_FakeStream(_events_for(r), r)) for r in responses
    ]
    client.messages.stream = MagicMock(side_effect=managers)
    return client


def _tool_use_response(tool_input: dict[str, Any]) -> Message:
    return Message(
        id="msg_tool_use",
        content=[
            ToolUseBlock(
                id=TOOL_USE_ID,
                name="get_account_activity",
                input=tool_input,
                type="tool_use",
            )
        ],
        model=MODEL_ID,
        role="assistant",
        stop_reason="tool_use",
        type="message",
        usage=Usage(input_tokens=20, output_tokens=8),
    )


def _text_response(text_value: str) -> Message:
    return Message(
        id="msg_text",
        content=[AnthropicTextBlock(text=text_value, type="text")],
        model=MODEL_ID,
        role="assistant",
        stop_reason="end_turn",
        type="message",
        usage=Usage(input_tokens=30, output_tokens=12),
    )


# ---------- DB fixture (auto-cleans the turn graph) ----------


class _Fixture:
    def __init__(
        self,
        *,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        engine,
        alpaca_account_id: str | None,
    ) -> None:
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.engine = engine
        self.alpaca_account_id = alpaca_account_id

    async def cleanup(self) -> None:
        async with AsyncSession(
            bind=self.engine, expire_on_commit=False
        ) as cleanup:
            await cleanup.execute(
                text(
                    "DELETE FROM tool_executions WHERE model_invocation_id IN ("
                    "SELECT id FROM model_invocations WHERE agent_turn_id IN ("
                    "SELECT id FROM agent_turns WHERE conversation_id = :id))"
                ),
                {"id": self.conversation_id},
            )
            await cleanup.execute(
                text(
                    "DELETE FROM model_invocations WHERE agent_turn_id IN ("
                    "SELECT id FROM agent_turns WHERE conversation_id = :id)"
                ),
                {"id": self.conversation_id},
            )
            await cleanup.execute(
                text("DELETE FROM agent_turns WHERE conversation_id = :id"),
                {"id": self.conversation_id},
            )
            await cleanup.execute(
                text("DELETE FROM messages WHERE conversation_id = :id"),
                {"id": self.conversation_id},
            )
            await cleanup.execute(
                text("DELETE FROM conversations WHERE id = :id"),
                {"id": self.conversation_id},
            )
            await cleanup.execute(
                text("DELETE FROM brokerage_accounts WHERE user_id = :id"),
                {"id": self.user_id},
            )
            await cleanup.execute(
                text("DELETE FROM user_profiles WHERE id = :id"),
                {"id": self.user_id},
            )
            await cleanup.execute(
                text("DELETE FROM auth.users WHERE id = :id"),
                {"id": self.user_id},
            )
            await cleanup.commit()


async def _setup_fixture(db_engine, *, with_brokerage: bool) -> _Fixture:
    user_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    alpaca_account_id = f"alpaca_{uuid.uuid4()}" if with_brokerage else None
    async with AsyncSession(bind=db_engine, expire_on_commit=False) as setup:
        await insert_auth_user(
            setup, user_id=user_id, email=f"activity-{user_id}@test.local"
        )
        await ConversationRepository.create_conversation(
            setup, conversation_id=conversation_id, user_id=user_id
        )
        if with_brokerage:
            await setup.execute(
                text(
                    """
                    INSERT INTO brokerage_accounts (
                        id, user_id, alpaca_account_id, account_status,
                        kyc_submitted_at, activated_at
                    ) VALUES (
                        :id, :user_id, :alpaca_id, 'ACTIVE', now(), now()
                    )
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "user_id": user_id,
                    "alpaca_id": alpaca_account_id,
                },
            )
        await setup.commit()
    return _Fixture(
        user_id=user_id,
        conversation_id=conversation_id,
        engine=db_engine,
        alpaca_account_id=alpaca_account_id,
    )


@pytest.fixture
async def fixture(db_engine):
    fix = await _setup_fixture(db_engine, with_brokerage=True)
    try:
        yield fix
    finally:
        await fix.cleanup()


@pytest.fixture
async def fixture_no_brokerage(db_engine):
    fix = await _setup_fixture(db_engine, with_brokerage=False)
    try:
        yield fix
    finally:
        await fix.cleanup()


# ---------- helpers ----------


async def _drain(emitter: SSEEmitter) -> list[Event]:
    events: list[Event] = []
    async for event in emitter.iter_events():
        events.append(event)
    return events


async def _run(
    *, fixture: _Fixture, alpaca, tool_input: dict[str, Any], user_message: str
) -> tuple[Any, list[Event]]:
    registry = ToolRegistry()
    registry.register(GetAccountActivity())
    client = _stub_client(
        [_tool_use_response(tool_input), _text_response("Here's your activity.")]
    )
    emitter = SSEEmitter()
    drain_task = asyncio.create_task(_drain(emitter))
    try:
        result = await run_agent_turn(
            user_id=fixture.user_id,
            conversation_id=fixture.conversation_id,
            user_message=user_message,
            anthropic_client=client,
            db_factory=make_session_factory(fixture.engine),
            tool_registry=registry,
            http_clients=ToolHttpClients(alpaca=alpaca),
            system_prompt=SYSTEM_PROMPT,
            model_config=ModelConfig(model_id=MODEL_ID),
            hard_caps=HardCaps(),
            langfuse=_NoopLangfuse(),
            environment="test",
            sse_emitter=emitter,
        )
    finally:
        await emitter.close()
    events = await drain_task
    return result, events


async def _tool_execution(db_engine, conversation_id: uuid.UUID) -> ToolExecution:
    async with AsyncSession(bind=db_engine, expire_on_commit=False) as v:
        execs = (
            await v.execute(
                select(ToolExecution)
                .join(
                    ModelInvocation,
                    ToolExecution.model_invocation_id == ModelInvocation.id,
                )
                .join(AgentTurn, ModelInvocation.agent_turn_id == AgentTurn.id)
                .where(AgentTurn.conversation_id == conversation_id)
            )
        ).scalars().all()
    assert len(execs) == 1
    return execs[0]


async def _iter2_tool_result(db_engine, conversation_id: uuid.UUID) -> dict[str, Any]:
    async with AsyncSession(bind=db_engine, expire_on_commit=False) as v:
        invs = (
            await v.execute(
                select(ModelInvocation)
                .join(AgentTurn, ModelInvocation.agent_turn_id == AgentTurn.id)
                .where(AgentTurn.conversation_id == conversation_id)
                .order_by(ModelInvocation.iteration_index.asc())
            )
        ).scalars().all()
    assert len(invs) == 2
    tool_results = [
        b
        for b in invs[1].request_messages[-1]["content"]
        if b.get("type") == "tool_result"
    ]
    assert len(tool_results) == 1
    return tool_results[0]


# ---------- full roundtrip ----------


class TestAccountActivityRoundtrip:
    async def test_resolves_account_normalizes_and_feeds_back(
        self, db_engine, fixture
    ):
        alpaca = _mock_alpaca()

        result, events = await _run(
            fixture=fixture,
            alpaca=alpaca,
            tool_input={"after": "2026-05-01", "until": "2026-05-31"},
            user_message="what did I do this month?",
        )

        assert result.terminal_state == "end_turn"
        assert result.iterations_count == 2

        # The real brokerage row resolved → its alpaca_account_id reached the
        # broker (proves require_brokerage ran against Postgres, not a mock).
        assert alpaca.list_orders.await_args.args[0] == fixture.alpaca_account_id
        assert (
            alpaca.get_dividend_activities.await_args.kwargs["account_id"]
            == fixture.alpaca_account_id
        )

        te = await _tool_execution(db_engine, fixture.conversation_id)
        assert te.tool_name == "get_account_activity"
        assert te.tool_use_id == TOOL_USE_ID
        assert te.status == "success"
        assert te.input_payload == {"after": "2026-05-01", "until": "2026-05-31"}

        payload = te.output_payload
        assert payload["count"] == 6  # 2 trades + 2 transfers + 1 div + 1 int
        assert payload["totals"] == {
            "deposited": "200.00",
            "withdrawn": "50.00",
            "dividends": "3.12",
            "interest": "1.05",
            "executed_trades": 2,
            "open_orders": 0,
        }
        # Canceled order and the negative withholding were filtered out.
        assert {a["type"] for a in payload["activities"]} == {
            "trade",
            "deposit",
            "withdrawal",
            "dividend",
            "interest",
        }
        trades = {a["symbol"]: a for a in payload["activities"] if a["type"] == "trade"}
        assert trades["AAPL"]["amount"] == "-540.21"
        assert trades["TSLA"]["amount"] == "500.00"

        # The exact bytes Anthropic sees on iteration 2 are the normalized
        # payload — the model can answer from them.
        tr = await _iter2_tool_result(db_engine, fixture.conversation_id)
        assert tr["tool_use_id"] == TOOL_USE_ID
        assert json.loads(tr["content"]) == payload

        # The status pill surfaced on the wire: active → complete.
        status_starts = [
            e
            for e in events
            if isinstance(e, BlockStart) and e.block.get("type") == "status"
        ]
        status_data = [
            e
            for e in events
            if isinstance(e, BlockData) and e.data.get("type") == "status"
        ]
        assert len(status_starts) == 1
        assert status_starts[0].block["state"] == "active"
        assert status_starts[0].block["label"] == PILL_LABEL
        assert status_data[-1].data["state"] == "complete"
        assert te.ui_blocks_emitted is not None
        assert te.ui_blocks_emitted[0]["state"] == "complete"

        # Final assistant text streamed through.
        assert any(
            isinstance(e, TextDelta) and e.text == "Here's your activity."
            for e in events
        )

    async def test_type_filter_only_calls_requested_source(
        self, db_engine, fixture
    ):
        alpaca = _mock_alpaca()

        result, _ = await _run(
            fixture=fixture,
            alpaca=alpaca,
            tool_input={"activity_types": ["deposit"]},
            user_message="how much have I deposited?",
        )

        assert result.terminal_state == "end_turn"
        alpaca.list_transfers.assert_awaited_once()
        alpaca.list_orders.assert_not_awaited()
        alpaca.get_dividend_activities.assert_not_awaited()
        alpaca.get_interest_activities.assert_not_awaited()

        te = await _tool_execution(db_engine, fixture.conversation_id)
        assert set(te.output_payload["totals"]) == {"deposited", "withdrawn"}
        assert {a["type"] for a in te.output_payload["activities"]} == {"deposit"}


# ---------- pending in by default, canceled opt-in ----------


def _orders_with_status_mix() -> list[dict[str, Any]]:
    return [
        {
            "id": "o_filled",
            "symbol": "AAPL",
            "side": "buy",
            "status": "filled",
            "order_type": "market",
            "qty": "3",
            "filled_qty": "3",
            "filled_avg_price": "180.07",
            "filled_at": "2026-05-20T14:31:00Z",
        },
        {
            "id": "o_pending",
            "symbol": "TSLA",
            "side": "buy",
            "status": "new",
            "order_type": "limit",
            "qty": "2",
            "filled_qty": "0",
            "limit_price": "180.00",
            "submitted_at": "2026-05-21T10:00:00Z",
        },
        {
            "id": "o_canceled",
            "symbol": "NVDA",
            "side": "buy",
            "status": "canceled",
            "order_type": "market",
            "qty": "1",
            "filled_qty": "0",
            "submitted_at": "2026-05-19T10:00:00Z",
        },
    ]


class TestOrderStatusInclusion:
    async def test_pending_included_canceled_excluded_by_default(
        self, db_engine, fixture
    ):
        alpaca = _mock_alpaca()
        alpaca.list_orders = AsyncMock(return_value=_orders_with_status_mix())

        result, _ = await _run(
            fixture=fixture,
            alpaca=alpaca,
            tool_input={"activity_types": ["trade"]},
            user_message="what's the status of my orders?",
        )

        assert result.terminal_state == "end_turn"
        te = await _tool_execution(db_engine, fixture.conversation_id)
        statuses = {a["status"] for a in te.output_payload["activities"]}
        assert statuses == {"filled", "new"}  # canceled dropped
        assert te.output_payload["totals"]["executed_trades"] == 1
        assert te.output_payload["totals"]["open_orders"] == 1  # the pending one

    async def test_include_canceled_surfaces_terminal_orders(
        self, db_engine, fixture
    ):
        alpaca = _mock_alpaca()
        alpaca.list_orders = AsyncMock(return_value=_orders_with_status_mix())

        result, _ = await _run(
            fixture=fixture,
            alpaca=alpaca,
            tool_input={"activity_types": ["trade"], "include_canceled": True},
            user_message="did any of my orders get canceled?",
        )

        assert result.terminal_state == "end_turn"
        te = await _tool_execution(db_engine, fixture.conversation_id)
        statuses = {a["status"] for a in te.output_payload["activities"]}
        assert statuses == {"filled", "new", "canceled"}
        assert te.output_payload["totals"]["executed_trades"] == 1
        assert te.output_payload["totals"]["open_orders"] == 1  # canceled counts in neither


# ---------- no brokerage account → soft error ----------


class TestNoBrokerageAccount:
    async def test_soft_errors_and_turn_completes(
        self, db_engine, fixture_no_brokerage
    ):
        alpaca = _mock_alpaca()

        result, events = await _run(
            fixture=fixture_no_brokerage,
            alpaca=alpaca,
            tool_input={},
            user_message="what trades did I make?",
        )

        assert result.terminal_state == "end_turn"
        # require_brokerage 404'd before any broker call.
        alpaca.list_orders.assert_not_awaited()

        te = await _tool_execution(db_engine, fixture_no_brokerage.conversation_id)
        # The tool caught NotFoundError and returned a ToolResult, so the audit
        # row is a success carrying an error payload — not a dispatch failure.
        assert te.status == "success"
        assert "brokerage account" in te.output_payload["error"]

        status_data = [
            e
            for e in events
            if isinstance(e, BlockData) and e.data.get("type") == "status"
        ]
        assert status_data[-1].data["state"] == "failed"
