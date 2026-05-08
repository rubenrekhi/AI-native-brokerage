"""Integration tests for C1.4 — tool execution emits SSE block events.

Per AI v0 plan C1.4 (sevino-api/docs/ai-v0-plan.md). When a tool's
``execute()`` returns a ``ui_block``, the agent loop emits the matching
``block_start`` / ``block_data`` / ``block_end`` envelope on the SSE
stream. ``block_data`` patches are tool-driven via ``ctx.sse_emitter``;
``block_end`` is loop-driven (after ``execute()`` returns) so the wire
always closes the bracket even if a tool forgets to.

These tests run ``run_agent_turn`` with a real local Postgres, mocked
Anthropic streaming, and a fake tool that emits 3 incremental
``block_data`` patches via ``ctx.sse_emitter``. The test asserts:

* The SSE stream contains the patches in order (relative to
  ``block_start`` / ``block_end``)
* ``messages.content_blocks`` reflects the merged final state of the
  ``StockCardBlock``
* ``tool_executions.ui_blocks_emitted`` is populated with the final
  block

Pattern follows ``test_loop_emits_events.py`` — the loop's session-per-
write factory commits writes mid-turn, so a fresh session after the
loop returns is enough to verify durability.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, ClassVar
from unittest.mock import AsyncMock, MagicMock

import anthropic
import pytest
from anthropic.types import (
    Message as AnthropicMessage,
    RawContentBlockStartEvent,
    RawContentBlockStopEvent,
    TextBlock,
    ToolUseBlock,
    Usage,
)
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.ai.blocks import Bar, StockCardBlock
from app.ai.observability.langfuse import _NoopLangfuse
from app.ai.prompts import SystemPrompt
from app.ai.runtime.caps import HardCaps
from app.ai.runtime.db import make_session_factory
from app.ai.runtime.errors import ErrorCode
from app.ai.runtime.loop import run_agent_turn
from app.ai.runtime.types import ModelConfig
from app.ai.tools import (
    Tool,
    ToolContext,
    ToolHttpClients,
    ToolRegistry,
    ToolResult,
)
from app.ai.transport.emitter import SSEEmitter
from app.ai.transport.events import (
    BlockData,
    BlockEnd,
    BlockStart,
    Error,
    Event,
    TurnCompleted,
    TurnStarted,
)
from app.models.agent_turn import AgentTurn
from app.models.message import Message as MessageRow
from app.models.model_invocation import ModelInvocation
from app.models.tool_execution import ToolExecution
from app.repositories.conversation import ConversationRepository
from tests.integration.conftest import _pg_available_sync, insert_auth_user

pytestmark = pytest.mark.skipif(
    not _pg_available_sync,
    reason="Local Supabase Postgres not available (run `make infra`)",
)

MODEL_ID = "claude-sonnet-4-6"
SYSTEM_PROMPT = SystemPrompt(text="you are sevino", hash="hash-stream")


# ---------- fake tool ----------


class _StockInput(BaseModel):
    symbol: str


class _IncrementalStockTool(Tool[_StockInput]):
    """Test tool that emits ``BlockStart`` + 3 ``BlockData`` patches.

    Mirrors the production ``get_stock_info`` shape sketched in C2.4:
    price arrives first (synthetic ``BlockStart`` with the partial
    block), then change values, then bars, then the tool returns the
    final merged ``StockCardBlock``. The wire-emitted ``block_id`` and
    the returned block's ``block_id`` are the same value so the loop's
    ``block_end`` frame correlates with the tool's ``block_start``.
    """

    name: ClassVar[str] = "get_stock_info"
    description: ClassVar[str] = "Fake stock info."
    Input: ClassVar[type[BaseModel]] = _StockInput

    async def execute(
        self, input: _StockInput, ctx: ToolContext
    ) -> ToolResult:
        block_id = str(ULID())
        # Initial partial block — minimum required fields. The loop
        # records this BlockStart so it knows not to emit its own.
        await ctx.sse_emitter.emit(
            BlockStart(
                block={
                    "type": "stock_card",
                    "block_id": block_id,
                    "symbol": input.symbol,
                    "company_name": f"{input.symbol} Inc",
                    "logo_url": None,
                    "price": 100.0,
                    "change_abs": 0.0,
                    "change_pct": 0.0,
                    "color_state": "neutral",
                    "bars": [],
                    "range": "1D",
                    "range_options": [
                        "1D",
                        "1W",
                        "1M",
                        "3M",
                        "6M",
                        "1Y",
                        "ALL",
                    ],
                }
            )
        )
        # Patch 1: price update.
        await ctx.sse_emitter.emit(
            BlockData(block_id=block_id, data={"price": 101.5})
        )
        # Patch 2: change values + colour.
        await ctx.sse_emitter.emit(
            BlockData(
                block_id=block_id,
                data={
                    "change_abs": 1.5,
                    "change_pct": 0.015,
                    "color_state": "positive",
                },
            )
        )
        # Patch 3: bars (this is the slow upstream call in real life).
        await ctx.sse_emitter.emit(
            BlockData(
                block_id=block_id,
                data={
                    "bars": [
                        {"t": "2026-01-01T15:00:00Z", "c": 100.0},
                        {"t": "2026-01-01T15:30:00Z", "c": 100.8},
                        {"t": "2026-01-01T16:00:00Z", "c": 101.5},
                    ]
                },
            )
        )

        final_block = StockCardBlock(
            block_id=block_id,
            symbol=input.symbol,
            company_name=f"{input.symbol} Inc",
            logo_url=None,
            price=101.5,
            change_abs=1.5,
            change_pct=0.015,
            color_state="positive",
            bars=[
                Bar(t="2026-01-01T15:00:00Z", c=100.0),
                Bar(t="2026-01-01T15:30:00Z", c=100.8),
                Bar(t="2026-01-01T16:00:00Z", c=101.5),
            ],
            range="1D",
            range_options=["1D", "1W", "1M", "3M", "6M", "1Y", "ALL"],
        )
        return ToolResult(
            model_payload={"price": 101.5, "change_pct": 0.015},
            ui_block=final_block,
            internal_trace={"upstream": "synthetic"},
        )


# ---------- Anthropic stream fakes ----------


class _FakeStream:
    def __init__(self, events: list[Any], final: AnthropicMessage) -> None:
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

    async def get_final_message(self) -> AnthropicMessage:
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


def _events_for(message: AnthropicMessage) -> list[Any]:
    """Bracket each content block with start/stop raw events.

    No body deltas — we don't need them for tool_use (input arrives
    on ``get_final_message``) and the text iteration in these tests
    is short enough that it's fine to deliver the whole block on
    ``content_block_stop``.
    """
    events: list[Any] = []
    for index, block in enumerate(message.content):
        if block.type == "text":
            start_block: Any = TextBlock(text="", type="text", citations=None)
        else:
            start_block = block
        events.append(
            RawContentBlockStartEvent(
                content_block=start_block,
                index=index,
                type="content_block_start",
            )
        )
        events.append(
            RawContentBlockStopEvent(
                index=index, type="content_block_stop"
            )
        )
    return events


def _stub_client(responses: list[AnthropicMessage]) -> AsyncMock:
    client = AsyncMock(spec=anthropic.AsyncAnthropic)
    managers = [
        _FakeStreamManager(_FakeStream(_events_for(r), r)) for r in responses
    ]
    client.messages.stream = MagicMock(side_effect=managers)
    return client


# ---------- DB fixture ----------


class _Fixture:
    def __init__(
        self,
        *,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        engine,
    ) -> None:
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.engine = engine

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
                text("DELETE FROM user_profiles WHERE id = :id"),
                {"id": self.user_id},
            )
            await cleanup.execute(
                text("DELETE FROM auth.users WHERE id = :id"),
                {"id": self.user_id},
            )
            await cleanup.commit()


@pytest.fixture
async def fixture(db_engine):
    user_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    email = f"stream-{user_id}@test.local"
    async with AsyncSession(bind=db_engine, expire_on_commit=False) as setup:
        await insert_auth_user(setup, user_id=user_id, email=email)
        await ConversationRepository.create_conversation(
            setup, conversation_id=conversation_id, user_id=user_id
        )
        await setup.commit()

    fix = _Fixture(
        user_id=user_id, conversation_id=conversation_id, engine=db_engine
    )
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


def _build_tool_use_response(
    *, tool_use_id: str, symbol: str
) -> AnthropicMessage:
    return AnthropicMessage(
        id="msg_iter_1",
        content=[
            ToolUseBlock(
                id=tool_use_id,
                name="get_stock_info",
                input={"symbol": symbol},
                type="tool_use",
            )
        ],
        model=MODEL_ID,
        role="assistant",
        stop_reason="tool_use",
        type="message",
        usage=Usage(input_tokens=120, output_tokens=40),
    )


def _build_text_response(text_value: str) -> AnthropicMessage:
    return AnthropicMessage(
        id="msg_iter_2",
        content=[TextBlock(text=text_value, type="text", citations=None)],
        model=MODEL_ID,
        role="assistant",
        stop_reason="end_turn",
        type="message",
        usage=Usage(input_tokens=180, output_tokens=20),
    )


# ---------- tests ----------


class TestIncrementalBlockStreaming:
    async def test_block_data_patches_arrive_in_order(self, db_engine, fixture):
        """SEV-497 acceptance: 3 ``block_data`` patches stream in order."""
        registry = ToolRegistry()
        registry.register(_IncrementalStockTool())

        client = _stub_client(
            [
                _build_tool_use_response(
                    tool_use_id="toolu_amd_01", symbol="AMD"
                ),
                _build_text_response("AMD is up 1.5%."),
            ]
        )
        emitter = SSEEmitter()
        drain_task = asyncio.create_task(_drain(emitter))

        try:
            result = await run_agent_turn(
                user_id=fixture.user_id,
                conversation_id=fixture.conversation_id,
                user_message="how is AMD",
                anthropic_client=client,
                db_factory=make_session_factory(db_engine),
                tool_registry=registry,
                http_clients=ToolHttpClients(),
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

        assert result.terminal_state == "end_turn"
        assert result.iterations_count == 2

        # The wire envelope, in order:
        # turn_started → (tool iteration: BlockStart, BlockData × 3,
        # BlockEnd) → (text iteration: BlockStart text, BlockEnd) →
        # turn_completed.
        types = [type(e) for e in events]
        assert types[0] is TurnStarted
        assert types[-1] is TurnCompleted

        # Find the stock_card BlockStart
        block_starts = [e for e in events if isinstance(e, BlockStart)]
        stock_starts = [
            e for e in block_starts if e.block.get("type") == "stock_card"
        ]
        assert len(stock_starts) == 1
        stock_block_id = stock_starts[0].block["block_id"]

        # All three BlockData patches reference the same block_id, in order.
        block_datas = [e for e in events if isinstance(e, BlockData)]
        assert [d.block_id for d in block_datas] == [stock_block_id] * 3
        assert block_datas[0].data == {"price": 101.5}
        assert block_datas[1].data == {
            "change_abs": 1.5,
            "change_pct": 0.015,
            "color_state": "positive",
        }
        assert block_datas[2].data == {
            "bars": [
                {"t": "2026-01-01T15:00:00Z", "c": 100.0},
                {"t": "2026-01-01T15:30:00Z", "c": 100.8},
                {"t": "2026-01-01T16:00:00Z", "c": 101.5},
            ]
        }

        # The matching BlockEnd for the stock_card block exists, and comes
        # after all three patches but before the text BlockStart.
        stock_end_index = next(
            i
            for i, e in enumerate(events)
            if isinstance(e, BlockEnd) and e.block_id == stock_block_id
        )
        last_data_index = max(
            i for i, e in enumerate(events) if isinstance(e, BlockData)
        )
        assert last_data_index < stock_end_index

    async def test_messages_content_blocks_reflects_merged_final_state(
        self, db_engine, fixture
    ):
        """SEV-497 acceptance: persisted ``content_blocks`` carry the
        full merged ``StockCardBlock`` (text iteration's text block too)."""
        registry = ToolRegistry()
        registry.register(_IncrementalStockTool())

        client = _stub_client(
            [
                _build_tool_use_response(
                    tool_use_id="toolu_amd_02", symbol="AMD"
                ),
                _build_text_response("AMD is up 1.5%."),
            ]
        )

        await run_agent_turn(
            user_id=fixture.user_id,
            conversation_id=fixture.conversation_id,
            user_message="how is AMD",
            anthropic_client=client,
            db_factory=make_session_factory(db_engine),
            tool_registry=registry,
            http_clients=ToolHttpClients(),
            system_prompt=SYSTEM_PROMPT,
            model_config=ModelConfig(model_id=MODEL_ID),
            hard_caps=HardCaps(),
            langfuse=_NoopLangfuse(),
            environment="test",
            sse_emitter=SSEEmitter(),
        )

        async with AsyncSession(bind=db_engine, expire_on_commit=False) as v:
            assistant = (
                await v.execute(
                    select(MessageRow)
                    .where(
                        MessageRow.conversation_id == fixture.conversation_id,
                        MessageRow.role == "assistant",
                    )
                )
            ).scalar_one()
            blocks = assistant.content_blocks
            stock_blocks = [
                b for b in blocks if b.get("type") == "stock_card"
            ]
            assert len(stock_blocks) == 1
            stock_block = stock_blocks[0]
            # Merged final state — the values returned by execute(), not
            # the partial ones streamed in BlockStart.
            assert stock_block["price"] == 101.5
            assert stock_block["change_abs"] == 1.5
            assert stock_block["change_pct"] == 0.015
            assert stock_block["color_state"] == "positive"
            assert stock_block["bars"] == [
                {"t": "2026-01-01T15:00:00Z", "c": 100.0},
                {"t": "2026-01-01T15:30:00Z", "c": 100.8},
                {"t": "2026-01-01T16:00:00Z", "c": 101.5},
            ]

            # The text iteration's response also lands in the same
            # assistant message — proves the second-iteration text block
            # joins the same persisted row rather than silently dropping.
            text_blocks = [b for b in blocks if b.get("type") == "text"]
            assert len(text_blocks) == 1
            assert text_blocks[0]["text"] == "AMD is up 1.5%."

    async def test_tool_executions_row_records_ui_blocks_emitted(
        self, db_engine, fixture
    ):
        """SEV-497 acceptance: ``tool_executions.ui_blocks_emitted`` is
        the merged final block, not a per-patch log."""
        registry = ToolRegistry()
        registry.register(_IncrementalStockTool())

        client = _stub_client(
            [
                _build_tool_use_response(
                    tool_use_id="toolu_amd_03", symbol="AMD"
                ),
                _build_text_response("AMD is up 1.5%."),
            ]
        )

        await run_agent_turn(
            user_id=fixture.user_id,
            conversation_id=fixture.conversation_id,
            user_message="how is AMD",
            anthropic_client=client,
            db_factory=make_session_factory(db_engine),
            tool_registry=registry,
            http_clients=ToolHttpClients(),
            system_prompt=SYSTEM_PROMPT,
            model_config=ModelConfig(model_id=MODEL_ID),
            hard_caps=HardCaps(),
            langfuse=_NoopLangfuse(),
            environment="test",
            sse_emitter=SSEEmitter(),
        )

        async with AsyncSession(bind=db_engine, expire_on_commit=False) as v:
            tool_exec = (
                await v.execute(
                    select(ToolExecution)
                    .join(
                        ModelInvocation,
                        ToolExecution.model_invocation_id
                        == ModelInvocation.id,
                    )
                    .join(
                        AgentTurn,
                        ModelInvocation.agent_turn_id == AgentTurn.id,
                    )
                    .where(AgentTurn.conversation_id == fixture.conversation_id)
                )
            ).scalar_one()

            assert tool_exec.tool_name == "get_stock_info"
            assert tool_exec.tool_use_id == "toolu_amd_03"
            assert tool_exec.status == "success"
            assert tool_exec.input_payload == {"symbol": "AMD"}
            assert tool_exec.output_payload == {
                "price": 101.5,
                "change_pct": 0.015,
            }
            assert tool_exec.internal_trace == {"upstream": "synthetic"}
            assert tool_exec.latency_ms is not None and tool_exec.latency_ms >= 0

            assert tool_exec.ui_blocks_emitted is not None
            assert len(tool_exec.ui_blocks_emitted) == 1
            recorded = tool_exec.ui_blocks_emitted[0]
            assert recorded["type"] == "stock_card"
            assert recorded["price"] == 101.5
            assert recorded["change_pct"] == 0.015
            assert len(recorded["bars"]) == 3


class TestToolErrorPaths:
    async def test_validation_error_terminates_turn_with_validation_error(
        self, db_engine, fixture
    ):
        """C1.2 acceptance: input that fails ``Tool.Input.model_validate``
        terminates the turn with an ``Error`` frame whose ``code`` is
        ``validation_error``, and persists a tool_executions row marked
        ``status='error'`` for the audit trail."""
        registry = ToolRegistry()
        registry.register(_IncrementalStockTool())

        # The tool input requires ``symbol: str``; sending ``{}`` triggers
        # ``ValidationError``. The model would never normally do this in
        # production — we're protecting the loop against tool-spec drift.
        bad_response = AnthropicMessage(
            id="msg_bad",
            content=[
                ToolUseBlock(
                    id="toolu_bad_01",
                    name="get_stock_info",
                    input={},
                    type="tool_use",
                )
            ],
            model=MODEL_ID,
            role="assistant",
            stop_reason="tool_use",
            type="message",
            usage=Usage(input_tokens=80, output_tokens=20),
        )
        client = _stub_client([bad_response])

        emitter = SSEEmitter()
        drain_task = asyncio.create_task(_drain(emitter))
        try:
            result = await run_agent_turn(
                user_id=fixture.user_id,
                conversation_id=fixture.conversation_id,
                user_message="how is AMD",
                anthropic_client=client,
                db_factory=make_session_factory(db_engine),
                tool_registry=registry,
                http_clients=ToolHttpClients(),
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

        assert result.terminal_state == "error"
        terminal = events[-1]
        assert isinstance(terminal, Error)
        assert terminal.code == ErrorCode.VALIDATION_ERROR

        async with AsyncSession(bind=db_engine, expire_on_commit=False) as v:
            tool_exec = (
                await v.execute(
                    select(ToolExecution)
                    .join(
                        ModelInvocation,
                        ToolExecution.model_invocation_id
                        == ModelInvocation.id,
                    )
                    .join(
                        AgentTurn,
                        ModelInvocation.agent_turn_id == AgentTurn.id,
                    )
                    .where(
                        AgentTurn.conversation_id == fixture.conversation_id
                    )
                )
            ).scalar_one()
            assert tool_exec.status == "error"
            assert tool_exec.tool_use_id == "toolu_bad_01"
            assert tool_exec.error_message
            assert "symbol" in tool_exec.error_message.lower()
