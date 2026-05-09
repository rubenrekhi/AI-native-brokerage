"""Integration tests for C1.2 — agent loop wires ``ToolContext`` into tools.

The loop must, on ``stop_reason == "tool_use"``:

* Look up the tool by name in the registry.
* Validate ``tool_use.input`` via ``tool.Input.model_validate``.
* Build a :class:`ToolContext` and call ``await tool.execute(input, ctx)``.
* Persist a ``tool_executions`` row with input/output/internal_trace/
  ui_blocks_emitted/status.
* Emit ``block_start`` / ``block_end`` for any UI block returned.
* Append a ``user`` message of ``tool_result`` blocks back to ``messages``.
* Continue the loop so iteration N+1 sees the tool output.

These tests run ``run_agent_turn`` against real local Postgres with a
mocked Anthropic client that scripts each iteration's response. We
assert on the persisted rows (not just on the in-memory Anthropic mock)
because the JSONB shape is the contract for iteration N+1's request and
for downstream observability.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, ClassVar
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
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.blocks import StatusBlock
from app.ai.observability.langfuse import _NoopLangfuse
from app.ai.prompts import SystemPrompt
from app.ai.runtime.caps import HardCaps
from app.ai.runtime.db import make_session_factory
from app.ai.runtime.errors import ErrorCode
from app.ai.runtime.loop import run_agent_turn
from app.ai.runtime.types import EMPTY_REGISTRY, ModelConfig
from app.ai.tools import (
    Tool,
    ToolContext,
    ToolHttpClients,
    ToolRegistry,
    ToolResult,
)
from app.ai.transport.emitter import SSEEmitter
from app.ai.transport.events import (
    BlockEnd,
    BlockStart,
    Error,
    Event,
    TextDelta,
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
SYSTEM_PROMPT = SystemPrompt(text="you are sevino", hash="hash-tool-use")


# ---------- fake tools ----------


class _EchoInput(BaseModel):
    message: str


class _EchoTool(Tool[_EchoInput]):
    name: ClassVar[str] = "echo"
    description: ClassVar[str] = "Echo the input message back to the model."
    Input: ClassVar[type[BaseModel]] = _EchoInput

    async def execute(
        self, input: _EchoInput, ctx: ToolContext
    ) -> ToolResult:
        return ToolResult(
            model_payload={"echoed": input.message},
            internal_trace={"received": input.message, "user_id": str(ctx.user_id)},
        )


class _StatusInput(BaseModel):
    label: str


class _StatusTool(Tool[_StatusInput]):
    """Returns a :class:`StatusBlock` so we can assert the loop emits
    ``block_start`` / ``block_end`` and persists the block in
    ``messages.content_blocks``."""

    name: ClassVar[str] = "status_emitter"
    description: ClassVar[str] = "Emit a status pill."
    Input: ClassVar[type[BaseModel]] = _StatusInput

    async def execute(
        self, input: _StatusInput, ctx: ToolContext
    ) -> ToolResult:
        return ToolResult(
            model_payload={"emitted": input.label},
            ui_block=StatusBlock(
                block_id="01STATUSBLOCK0000000000000",
                label=input.label,
                state="complete",
            ),
            internal_trace={"label": input.label},
        )


class _BoomInput(BaseModel):
    pass


class _BoomTool(Tool[_BoomInput]):
    name: ClassVar[str] = "boom"
    description: ClassVar[str] = "Always raises."
    Input: ClassVar[type[BaseModel]] = _BoomInput

    async def execute(self, input: _BoomInput, ctx: ToolContext) -> ToolResult:
        raise RuntimeError("kaboom")


# ---------- streaming fakes ----------


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
    """Build the start/delta/stop bracket the loop expects from a stream.

    Text blocks emit a ``text_delta`` with the full text so the loop's
    SSE TextDelta forwarding is exercised. Tool-use and other block
    types pass through with the start/stop bracket only — the loop only
    consumes the final message for those.
    """
    events: list[Any] = []
    for index, block in enumerate(message.content):
        if block.type == "text":
            start_block = AnthropicTextBlock(text="", type="text", citations=None)
        else:
            start_block = block
        events.append(
            RawContentBlockStartEvent(
                content_block=start_block,
                index=index,
                type="content_block_start",
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
    """Cycle ``messages.stream`` through ``responses`` — one stream
    manager per call. Tests with two-iteration turns hand two messages."""
    client = AsyncMock(spec=anthropic.AsyncAnthropic)
    managers = [
        _FakeStreamManager(_FakeStream(_events_for(r), r)) for r in responses
    ]
    client.messages.stream = MagicMock(side_effect=managers)
    return client


def _tool_use_response(
    *, tool_name: str, tool_use_id: str, tool_input: dict[str, Any]
) -> Message:
    return Message(
        id=f"msg_tool_use_{tool_use_id}",
        content=[
            ToolUseBlock(
                id=tool_use_id,
                name=tool_name,
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


def _text_response(
    *, text_value: str, stop_reason: str = "end_turn"
) -> Message:
    return Message(
        id=f"msg_text_{text_value[:6]}",
        content=[AnthropicTextBlock(text=text_value, type="text")],
        model=MODEL_ID,
        role="assistant",
        stop_reason=stop_reason,
        type="message",
        usage=Usage(input_tokens=30, output_tokens=12),
    )


# ---------- DB fixture ----------


class _Fixture:
    def __init__(
        self, *, user_id: uuid.UUID, conversation_id: uuid.UUID, engine
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
    email = f"tooluse-{user_id}@test.local"
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


async def _run(
    *,
    fixture: _Fixture,
    db_engine,
    client: AsyncMock,
    tool_registry,
    user_message: str = "do the thing",
) -> tuple[Any, list[Event]]:
    emitter = SSEEmitter()
    drain_task = asyncio.create_task(_drain(emitter))
    try:
        result = await run_agent_turn(
            user_id=fixture.user_id,
            conversation_id=fixture.conversation_id,
            user_message=user_message,
            anthropic_client=client,
            db_factory=make_session_factory(db_engine),
            tool_registry=tool_registry,
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
    return result, events


# ---------- happy path: echo tool roundtrip ----------


class TestEchoToolRoundtrip:
    async def test_tool_called_persisted_and_result_visible_to_followup_call(
        self, db_engine, fixture
    ):
        registry = ToolRegistry()
        registry.register(_EchoTool())

        iter_1 = _tool_use_response(
            tool_name="echo",
            tool_use_id="toolu_echo_001",
            tool_input={"message": "hi there"},
        )
        iter_2 = _text_response(text_value="I echoed it back")
        client = _stub_client([iter_1, iter_2])

        result, events = await _run(
            db_engine=db_engine,
            fixture=fixture,
            client=client,
            tool_registry=registry,
            user_message="please echo hi there",
        )

        # Two-iteration turn ends cleanly.
        assert result.terminal_state == "end_turn"
        assert result.iterations_count == 2
        assert client.messages.stream.call_count == 2

        # SSE envelope: text block from iter 2 only — the tool returns no
        # ui_block, so only iter 2 produces wire-level frames between
        # turn_started and turn_completed.
        assert [type(e) for e in events] == [
            TurnStarted,
            BlockStart,
            TextDelta,
            BlockEnd,
            TurnCompleted,
        ]
        completed = events[-1]
        assert isinstance(completed, TurnCompleted)
        assert completed.terminal_state == "end_turn"
        assert completed.iterations_count == 2

        # tool_executions row carries the full audit trail.
        async with AsyncSession(bind=db_engine, expire_on_commit=False) as v:
            execs = (
                await v.execute(
                    select(ToolExecution)
                    .join(
                        ModelInvocation,
                        ToolExecution.model_invocation_id == ModelInvocation.id,
                    )
                    .join(
                        AgentTurn,
                        ModelInvocation.agent_turn_id == AgentTurn.id,
                    )
                    .where(AgentTurn.conversation_id == fixture.conversation_id)
                )
            ).scalars().all()
            assert len(execs) == 1
            te = execs[0]
            assert te.tool_name == "echo"
            assert te.tool_use_id == "toolu_echo_001"
            assert te.input_payload == {"message": "hi there"}
            assert te.output_payload == {"echoed": "hi there"}
            assert te.status == "success"
            assert te.error_message is None
            # internal_trace round-trips verbatim — including the user_id
            # the tool read off ``ctx`` (proves the loop builds and passes
            # a real ToolContext).
            assert te.internal_trace == {
                "received": "hi there",
                "user_id": str(fixture.user_id),
            }
            assert te.ui_blocks_emitted is None
            assert te.completed_at is not None
            assert te.latency_ms is not None and te.latency_ms >= 0

            # The tool_execution is FK-bound to iteration 0's
            # model_invocation row, not iteration 1's — that's the
            # invocation that actually emitted the tool_use block.
            invs = (
                await v.execute(
                    select(ModelInvocation)
                    .join(AgentTurn, ModelInvocation.agent_turn_id == AgentTurn.id)
                    .where(AgentTurn.conversation_id == fixture.conversation_id)
                    .order_by(ModelInvocation.iteration_index.asc())
                )
            ).scalars().all()
            assert len(invs) == 2
            assert te.model_invocation_id == invs[0].id

            # Iteration 1's request_messages is the contract for what
            # Anthropic sees on the follow-up call: the original user
            # message, the assistant tool_use turn, and the user
            # tool_result turn. Persisting it as JSONB lets us assert on
            # the same source of truth that Anthropic would consume.
            iter_2_messages = invs[1].request_messages
            assert len(iter_2_messages) == 3
            assert iter_2_messages[0]["role"] == "user"
            assert iter_2_messages[1]["role"] == "assistant"
            assert any(
                b.get("type") == "tool_use"
                for b in iter_2_messages[1]["content"]
            )
            assert iter_2_messages[2]["role"] == "user"
            tool_result_blocks = [
                b
                for b in iter_2_messages[2]["content"]
                if b.get("type") == "tool_result"
            ]
            assert len(tool_result_blocks) == 1
            tr = tool_result_blocks[0]
            assert tr["tool_use_id"] == "toolu_echo_001"
            # Content is the JSON-serialised ``model_payload``, so a
            # follow-up Anthropic call sees the exact bytes we emit.
            assert json.loads(tr["content"]) == {"echoed": "hi there"}

            # Final assistant message persists only the iter-2 text block;
            # the tool's model_payload is intentionally not user-facing.
            msgs = (
                await v.execute(
                    select(MessageRow)
                    .where(
                        MessageRow.conversation_id == fixture.conversation_id
                    )
                    .order_by(MessageRow.created_at.asc(), MessageRow.id.asc())
                )
            ).scalars().all()
            assert [m.role for m in msgs] == ["user", "assistant"]
            assistant_blocks = msgs[1].content_blocks
            assert len(assistant_blocks) == 1
            assert assistant_blocks[0]["type"] == "text"
            assert assistant_blocks[0]["text"] == "I echoed it back"


# ---------- ui_block surfaces on wire + persistence ----------


class TestToolEmitsUiBlock:
    async def test_status_block_emitted_and_persisted(self, db_engine, fixture):
        registry = ToolRegistry()
        registry.register(_StatusTool())

        iter_1 = _tool_use_response(
            tool_name="status_emitter",
            tool_use_id="toolu_status_001",
            tool_input={"label": "Looking it up"},
        )
        iter_2 = _text_response(text_value="done")
        client = _stub_client([iter_1, iter_2])

        result, events = await _run(
            db_engine=db_engine,
            fixture=fixture,
            client=client,
            tool_registry=registry,
        )

        assert result.terminal_state == "end_turn"

        # Wire envelope: turn_started → status block start/end (from the
        # tool's ui_block) → text block start/delta/end (iter 2) →
        # turn_completed. The ui block bracket lands BEFORE the text
        # because the loop emits it after iter 1's stream completes,
        # before iter 2 begins.
        assert [type(e) for e in events] == [
            TurnStarted,
            BlockStart,
            BlockEnd,
            BlockStart,
            TextDelta,
            BlockEnd,
            TurnCompleted,
        ]
        status_start = events[1]
        status_end = events[2]
        assert isinstance(status_start, BlockStart)
        assert isinstance(status_end, BlockEnd)
        assert status_start.block["type"] == "status"
        assert status_start.block["block_id"] == "01STATUSBLOCK0000000000000"
        assert status_start.block["label"] == "Looking it up"
        assert status_start.block["state"] == "complete"
        assert status_end.block_id == "01STATUSBLOCK0000000000000"

        # Persisted assistant message includes BOTH the status block
        # and the iteration-2 text block, in the order they were
        # surfaced on the wire.
        async with AsyncSession(bind=db_engine, expire_on_commit=False) as v:
            assistant = (
                await v.execute(
                    select(MessageRow).where(
                        MessageRow.conversation_id == fixture.conversation_id,
                        MessageRow.role == "assistant",
                    )
                )
            ).scalar_one()
            assert len(assistant.content_blocks) == 2
            assert assistant.content_blocks[0]["type"] == "status"
            assert (
                assistant.content_blocks[0]["block_id"]
                == "01STATUSBLOCK0000000000000"
            )
            assert assistant.content_blocks[1]["type"] == "text"

            te = (
                await v.execute(
                    select(ToolExecution)
                    .join(
                        ModelInvocation,
                        ToolExecution.model_invocation_id == ModelInvocation.id,
                    )
                    .join(
                        AgentTurn,
                        ModelInvocation.agent_turn_id == AgentTurn.id,
                    )
                    .where(AgentTurn.conversation_id == fixture.conversation_id)
                )
            ).scalar_one()
            # ui_blocks_emitted captures the JSON block dump for the
            # Block discriminated-union round-trip.
            assert te.ui_blocks_emitted is not None
            assert len(te.ui_blocks_emitted) == 1
            assert te.ui_blocks_emitted[0]["type"] == "status"
            assert (
                te.ui_blocks_emitted[0]["block_id"]
                == "01STATUSBLOCK0000000000000"
            )


# ---------- validation error path ----------


class TestValidationError:
    async def test_invalid_input_emits_validation_error_and_persists_audit_row(
        self, db_engine, fixture
    ):
        registry = ToolRegistry()
        registry.register(_EchoTool())

        # Echo expects ``message: str``; sending an int makes
        # ``Input.model_validate`` raise.
        iter_1 = _tool_use_response(
            tool_name="echo",
            tool_use_id="toolu_validate_001",
            tool_input={"message": 42},
        )
        client = _stub_client([iter_1])

        result, events = await _run(
            db_engine=db_engine,
            fixture=fixture,
            client=client,
            tool_registry=registry,
        )

        assert result.terminal_state == "error"
        assert [type(e) for e in events] == [TurnStarted, Error]
        err = events[1]
        assert isinstance(err, Error)
        assert err.code == ErrorCode.VALIDATION_ERROR

        # The loop must not have called Anthropic again — a validation
        # error short-circuits before the tool runs and before we'd ask
        # Claude for a follow-up turn.
        assert client.messages.stream.call_count == 1

        async with AsyncSession(bind=db_engine, expire_on_commit=False) as v:
            te = (
                await v.execute(
                    select(ToolExecution)
                    .join(
                        ModelInvocation,
                        ToolExecution.model_invocation_id == ModelInvocation.id,
                    )
                    .join(
                        AgentTurn,
                        ModelInvocation.agent_turn_id == AgentTurn.id,
                    )
                    .where(AgentTurn.conversation_id == fixture.conversation_id)
                )
            ).scalar_one()
            assert te.status == "error"
            assert te.error_message is not None
            assert te.output_payload is None
            assert te.completed_at is not None

            turn = (
                await v.execute(
                    select(AgentTurn).where(
                        AgentTurn.conversation_id == fixture.conversation_id
                    )
                )
            ).scalar_one()
            assert turn.terminal_state == "error"
            assert turn.error_code == "validation_error"


# ---------- tool execute exception path ----------


class TestToolExecuteException:
    async def test_tool_raises_emits_tool_error_and_persists_row(
        self, db_engine, fixture
    ):
        registry = ToolRegistry()
        registry.register(_BoomTool())

        iter_1 = _tool_use_response(
            tool_name="boom",
            tool_use_id="toolu_boom_001",
            tool_input={},
        )
        client = _stub_client([iter_1])

        result, events = await _run(
            db_engine=db_engine,
            fixture=fixture,
            client=client,
            tool_registry=registry,
        )

        assert result.terminal_state == "error"
        assert [type(e) for e in events] == [TurnStarted, Error]
        err = events[1]
        assert isinstance(err, Error)
        assert err.code == ErrorCode.TOOL_ERROR

        async with AsyncSession(bind=db_engine, expire_on_commit=False) as v:
            te = (
                await v.execute(
                    select(ToolExecution)
                    .join(
                        ModelInvocation,
                        ToolExecution.model_invocation_id == ModelInvocation.id,
                    )
                    .join(
                        AgentTurn,
                        ModelInvocation.agent_turn_id == AgentTurn.id,
                    )
                    .where(AgentTurn.conversation_id == fixture.conversation_id)
                )
            ).scalar_one()
            assert te.status == "error"
            assert te.error_message is not None
            assert "kaboom" in te.error_message
            assert te.output_payload is None


# ---------- unknown tool name ----------


class TestUnknownToolName:
    async def test_unknown_tool_name_maps_to_internal_error(
        self, db_engine, fixture
    ):
        # Empty registry — any tool_use the model produces is, by
        # construction, unknown to us.
        iter_1 = _tool_use_response(
            tool_name="not_registered",
            tool_use_id="toolu_unknown_001",
            tool_input={"x": 1},
        )
        client = _stub_client([iter_1])

        result, events = await _run(
            db_engine=db_engine,
            fixture=fixture,
            client=client,
            tool_registry=EMPTY_REGISTRY,
        )

        assert result.terminal_state == "error"
        assert [type(e) for e in events] == [TurnStarted, Error]
        err = events[1]
        assert isinstance(err, Error)
        # Anthropic emitting a tool_use we never advertised is a
        # framework-level misconfig, so it lands in INTERNAL_ERROR
        # rather than TOOL_ERROR (which is reserved for tool-side
        # failures during execute).
        assert err.code == ErrorCode.INTERNAL_ERROR

        async with AsyncSession(bind=db_engine, expire_on_commit=False) as v:
            te = (
                await v.execute(
                    select(ToolExecution)
                    .join(
                        ModelInvocation,
                        ToolExecution.model_invocation_id == ModelInvocation.id,
                    )
                    .join(
                        AgentTurn,
                        ModelInvocation.agent_turn_id == AgentTurn.id,
                    )
                    .where(AgentTurn.conversation_id == fixture.conversation_id)
                )
            ).scalar_one()
            assert te.tool_name == "not_registered"
            assert te.status == "error"
            assert te.error_message is not None
            assert "unknown tool" in te.error_message


# ---------- defensive: malformed tool_use response ----------


class TestEmptyToolUseStopReason:
    async def test_tool_use_stop_reason_with_no_blocks_marks_internal_error(
        self, db_engine, fixture
    ):
        # Pathological: Anthropic emits ``stop_reason="tool_use"`` with a
        # text-only content array (no actual tool_use block). Without a
        # guard the loop would append an empty ``user`` content list to
        # ``messages`` and then 400 the next iteration; we want a clean
        # INTERNAL_ERROR instead.
        malformed = Message(
            id="msg_no_tools",
            content=[AnthropicTextBlock(text="oops", type="text")],
            model=MODEL_ID,
            role="assistant",
            stop_reason="tool_use",
            type="message",
            usage=Usage(input_tokens=8, output_tokens=4),
        )
        client = _stub_client([malformed])

        result, events = await _run(
            db_engine=db_engine,
            fixture=fixture,
            client=client,
            tool_registry=EMPTY_REGISTRY,
        )

        assert result.terminal_state == "error"
        # Only one Anthropic call — the loop didn't spin until cap.
        assert client.messages.stream.call_count == 1
        err_events = [e for e in events if isinstance(e, Error)]
        assert len(err_events) == 1
        assert err_events[0].code == ErrorCode.INTERNAL_ERROR


# ---------- cross-turn: persisted ui_blocks must not break follow-up turns ----------


class TestUiBlockNotResentToAnthropic:
    async def test_persisted_ui_block_dropped_from_followup_turn_request(
        self, db_engine, fixture
    ):
        """A ui_block (StatusBlock) persisted by turn 1 must NOT appear in
        the next turn's Anthropic request — Anthropic only accepts
        ``text`` / ``image`` / ``tool_use`` / ``tool_result`` /
        ``thinking`` content types and would 400 on ``status``.
        ``messages.content_blocks`` is the persisted source of truth for
        UI rendering; the loop's history-loading path is responsible for
        filtering UI-only artifacts before they re-enter the model."""
        # Turn 1: tool returns a StatusBlock + plain text response.
        registry = ToolRegistry()
        registry.register(_StatusTool())
        turn_1_iter_1 = _tool_use_response(
            tool_name="status_emitter",
            tool_use_id="toolu_status_xt_001",
            tool_input={"label": "First turn"},
        )
        turn_1_iter_2 = _text_response(text_value="first turn done")
        client = _stub_client([turn_1_iter_1, turn_1_iter_2])

        result, _events = await _run(
            db_engine=db_engine,
            fixture=fixture,
            client=client,
            tool_registry=registry,
            user_message="run the first turn",
        )
        assert result.terminal_state == "end_turn"

        # Sanity: turn 1 persisted both the status block and the text
        # block on the assistant message.
        async with AsyncSession(bind=db_engine, expire_on_commit=False) as v:
            assistant = (
                await v.execute(
                    select(MessageRow).where(
                        MessageRow.conversation_id == fixture.conversation_id,
                        MessageRow.role == "assistant",
                    )
                )
            ).scalar_one()
            assert {b["type"] for b in assistant.content_blocks} == {
                "status",
                "text",
            }

        # Turn 2: a fresh empty registry (the tool isn't called again).
        # The loop loads turn 1's persisted blocks via ``load_history``;
        # the Anthropic request the loop assembles must omit the status
        # block. We assert on ``model_invocations.request_messages``
        # because it is the JSONB source of truth for what was sent.
        turn_2_response = _text_response(text_value="second turn done")
        client_turn_2 = _stub_client([turn_2_response])
        result_2, _events_2 = await _run(
            db_engine=db_engine,
            fixture=fixture,
            client=client_turn_2,
            tool_registry=EMPTY_REGISTRY,
            user_message="follow up",
        )
        assert result_2.terminal_state == "end_turn"

        async with AsyncSession(bind=db_engine, expire_on_commit=False) as v:
            invs = (
                await v.execute(
                    select(ModelInvocation)
                    .join(
                        AgentTurn,
                        ModelInvocation.agent_turn_id == AgentTurn.id,
                    )
                    .where(AgentTurn.conversation_id == fixture.conversation_id)
                    .order_by(ModelInvocation.created_at.asc())
                )
            ).scalars().all()
            # Three invocations across two turns: turn-1 iter-0, turn-1
            # iter-1, turn-2 iter-0.
            assert len(invs) == 3
            turn_2_request = invs[2].request_messages

            # Turn 2 sees: turn-1 user, turn-1 assistant (text-only —
            # status dropped), turn-2 user.
            assert [m["role"] for m in turn_2_request] == [
                "user",
                "assistant",
                "user",
            ]
            assistant_msg = turn_2_request[1]
            assistant_types = {
                b.get("type") for b in assistant_msg["content"]
            }
            assert "status" not in assistant_types
            assert assistant_types == {"text"}
