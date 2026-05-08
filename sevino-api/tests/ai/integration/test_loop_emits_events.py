"""Integration tests for B2.4 — agent loop emits SSE events against real Postgres.

The loop now drives the wire envelope (``turn_started`` →
``block_start`` / ``text_delta`` / ``block_end`` → terminal frame) and
must keep ``messages.content_blocks`` in sync with the streamed
``block_id``. These tests run ``run_agent_turn`` with mocked Anthropic
streaming and a real local Postgres, then assert on:

* The exact event sequence drained from the emitter
* The persisted ``messages.content_blocks`` JSONB content (block_id
  matches the streamed envelope)
* Terminal ``error`` event on cap breach with the right error code

Pattern follows ``test_loop_persistence.py`` — the loop's session-per-write
factory commits writes mid-turn, so we open a fresh session after the
loop returns to verify durable rows.
"""

from __future__ import annotations

import asyncio
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
    TextBlock,
    TextDelta as AnthropicTextDelta,
    Usage,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.observability.langfuse import _NoopLangfuse
from app.ai.prompts import SystemPrompt
from app.ai.runtime.caps import HardCaps
from app.ai.runtime.db import make_session_factory
from app.ai.runtime.errors import ErrorCode
from app.ai.runtime.loop import run_agent_turn
from app.ai.runtime.types import EMPTY_REGISTRY, ModelConfig
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
from app.models.message import Message as MessageRow
from app.repositories.conversation import ConversationRepository
from tests.integration.conftest import _pg_available_sync, insert_auth_user

pytestmark = pytest.mark.skipif(
    not _pg_available_sync,
    reason="Local Supabase Postgres not available (run `make infra`)",
)

MODEL_ID = "claude-sonnet-4-6"
SYSTEM_PROMPT = SystemPrompt(text="you are sevino", hash="hash-emit")


# ---------- streaming fakes ----------


class _FakeStream:
    """Async iterator + ``get_final_message()`` mimicking
    ``anthropic.AsyncMessageStream``. Only the surface ``run_agent_turn``
    uses is implemented."""

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


def _make_message(text_value: str, *, stop_reason: str = "end_turn") -> Message:
    return Message(
        id="msg_emit_1",
        content=[TextBlock(text=text_value, type="text")],
        model=MODEL_ID,
        role="assistant",
        stop_reason=stop_reason,
        type="message",
        usage=Usage(input_tokens=8, output_tokens=4),
    )


def _stream_events(
    chunks: list[str], *, stop_reason: str = "end_turn"
) -> tuple[list[Any], Message]:
    """Build a stream of raw events covering one text block delivered as
    ``len(chunks)`` deltas. Returns the events list plus the accumulated
    final ``Message`` so test fakes can hand both to the loop."""
    full_text = "".join(chunks)
    final = _make_message(full_text, stop_reason=stop_reason)
    events: list[Any] = [
        RawContentBlockStartEvent(
            content_block=TextBlock(text="", type="text"),
            index=0,
            type="content_block_start",
        )
    ]
    for chunk in chunks:
        events.append(
            RawContentBlockDeltaEvent(
                delta=AnthropicTextDelta(text=chunk, type="text_delta"),
                index=0,
                type="content_block_delta",
            )
        )
    events.append(
        RawContentBlockStopEvent(index=0, type="content_block_stop")
    )
    return events, final


def _stub_streaming_client(events: list[Any], final: Message) -> AsyncMock:
    client = AsyncMock(spec=anthropic.AsyncAnthropic)
    client.messages.stream = MagicMock(
        return_value=_FakeStreamManager(_FakeStream(events, final))
    )
    return client


def _stub_raising_client(exc: BaseException) -> AsyncMock:
    """Stream manager that raises in ``__aenter__`` — models an Anthropic
    failure surfacing before any wire event is received."""

    class _RaisingManager:
        async def __aenter__(self) -> Any:
            raise exc

        async def __aexit__(self, *exc_info: Any) -> None:
            return None

    client = AsyncMock(spec=anthropic.AsyncAnthropic)
    client.messages.stream = MagicMock(return_value=_RaisingManager())
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
    email = f"emit-{user_id}@test.local"
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


async def _run_with_emitter(
    *,
    fixture: _Fixture,
    db_engine,
    client: AsyncMock,
    user_message: str = "hello",
    hard_caps: HardCaps | None = None,
) -> tuple[Any, list[Event]]:
    """Run the loop with a fresh emitter and drain events concurrently."""
    emitter = SSEEmitter()
    drain_task = asyncio.create_task(_drain(emitter))
    try:
        result = await run_agent_turn(
            user_id=fixture.user_id,
            conversation_id=fixture.conversation_id,
            user_message=user_message,
            anthropic_client=client,
            db_factory=make_session_factory(db_engine),
            tool_registry=EMPTY_REGISTRY,
            system_prompt=SYSTEM_PROMPT,
            model_config=ModelConfig(model_id=MODEL_ID),
            hard_caps=hard_caps or HardCaps(),
            langfuse=_NoopLangfuse(),
            environment="test",
            sse_emitter=emitter,
        )
    finally:
        await emitter.close()
    events = await drain_task
    return result, events


# ---------- happy path ----------


class TestEventSequenceMatchesModelOutput:
    async def test_single_text_block_emits_full_envelope(
        self, db_engine, fixture
    ):
        # Two text deltas to prove the loop forwards each Anthropic chunk
        # as its own ``text_delta`` frame in arrival order.
        events, final = _stream_events(["hel", "lo world"])
        client = _stub_streaming_client(events, final)

        result, wire_events = await _run_with_emitter(
            db_engine=db_engine,
            fixture=fixture,
            client=client,
            user_message="say hi",
        )

        # turn_started → block_start → text_delta × 2 → block_end → turn_completed
        assert [type(e) for e in wire_events] == [
            TurnStarted,
            BlockStart,
            TextDelta,
            TextDelta,
            BlockEnd,
            TurnCompleted,
        ]

        started = wire_events[0]
        assert isinstance(started, TurnStarted)
        assert started.conversation_id == fixture.conversation_id

        block_start = wire_events[1]
        assert isinstance(block_start, BlockStart)
        assert block_start.block["type"] == "text"
        assert block_start.block["text"] == ""
        block_id = block_start.block["block_id"]

        deltas = [e for e in wire_events if isinstance(e, TextDelta)]
        assert [d.text for d in deltas] == ["hel", "lo world"]
        assert all(d.block_id == block_id for d in deltas)

        block_end = wire_events[4]
        assert isinstance(block_end, BlockEnd)
        assert block_end.block_id == block_id

        completed = wire_events[5]
        assert isinstance(completed, TurnCompleted)
        assert completed.terminal_state == "end_turn"
        assert completed.iterations_count == 1
        assert completed.turn_id == started.turn_id
        assert completed.total_cost_usd_micros == result.total_cost_usd_micros

        # Acceptance: messages.content_blocks row populated after success,
        # matching the wire envelope's block_id.
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
            assert assistant.content_blocks == [
                {
                    "type": "text",
                    "block_id": block_id,
                    "text": "hello world",
                }
            ]


# ---------- cap breach ----------


class TestCapBreachEmitsError:
    async def test_iteration_limit_emits_error_event_with_correct_code(
        self, db_engine, fixture
    ):
        # ``max_iterations=0`` short-circuits before any Anthropic call —
        # the loop should still emit ``turn_started`` (the row is open) and
        # then an ``error`` frame mapped to ``TURN_ITERATION_LIMIT``.
        # Provide a non-empty stub so a regression that *did* call stream()
        # would still produce well-formed events; ``assert_not_called``
        # below catches the regression itself.
        events, final = _stream_events(["unused"])
        client = _stub_streaming_client(events, final)

        _result, wire_events = await _run_with_emitter(
            db_engine=db_engine,
            fixture=fixture,
            client=client,
            hard_caps=HardCaps(max_iterations=0),
        )

        assert [type(e) for e in wire_events] == [TurnStarted, Error]
        err = wire_events[1]
        assert isinstance(err, Error)
        assert err.code == ErrorCode.TURN_ITERATION_LIMIT
        assert err.message == "terminal_state=iteration_limit"
        client.messages.stream.assert_not_called()

        # No assistant message persisted — only the user turn.
        async with AsyncSession(bind=db_engine, expire_on_commit=False) as v:
            roles = (
                await v.execute(
                    select(MessageRow.role).where(
                        MessageRow.conversation_id == fixture.conversation_id
                    )
                )
            ).scalars().all()
            assert list(roles) == ["user"]


# ---------- anthropic exception ----------


class TestAnthropicExceptionEmitsError:
    async def test_rate_limit_after_turn_started_emits_error(
        self, db_engine, fixture
    ):
        import httpx

        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        response = httpx.Response(429, request=request)
        exc = anthropic.RateLimitError(
            "rate limited", response=response, body=None
        )
        client = _stub_raising_client(exc)

        result, wire_events = await _run_with_emitter(
            db_engine=db_engine,
            fixture=fixture,
            client=client,
        )

        # The Anthropic call fails before any block events stream — so the
        # envelope is just turn_started → error.
        assert [type(e) for e in wire_events] == [TurnStarted, Error]
        err = wire_events[1]
        assert isinstance(err, Error)
        assert err.code == ErrorCode.MODEL_RATE_LIMIT
        assert result.terminal_state == "error"
