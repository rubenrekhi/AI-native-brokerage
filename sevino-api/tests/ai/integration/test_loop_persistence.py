"""Integration tests for ``run_agent_turn`` against real local Postgres.

These tests use the real ``ConversationRepository`` and a real
``make_session_factory`` (decision D12) so the session-per-write contract
is exercised end-to-end. Anthropic is stubbed because v0 has no SSE yet
and we want deterministic tests.

Pattern follows ``tests/ai/integration/test_conversation_repo.py::
TestConcurrentWrites``: the loop commits its writes, so the rolling-back
``db_session`` fixture can't reach them. We use ``db_engine`` directly,
seed setup data in a committing session, run the loop, query in a fresh
session, then explicitly delete the rows we created.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock

import anthropic
import httpx
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
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.blocks import BlockListAdapter, TextBlock as SevinoTextBlock
from app.ai.observability.langfuse import _NoopLangfuse
from app.ai.prompts import SystemPrompt
from app.ai.runtime.caps import HardCaps
from app.ai.runtime.db import make_session_factory
from app.ai.runtime.loop import run_agent_turn
from app.ai.runtime.types import EMPTY_REGISTRY, ModelConfig
from app.ai.tools import ToolHttpClients
from app.ai.transport.emitter import SSEEmitter
from app.models.agent_turn import AgentTurn
from app.models.message import Message as MessageRow
from app.models.model_invocation import ModelInvocation
from app.repositories.conversation import ConversationRepository
from sqlalchemy import select
from tests.integration.conftest import _pg_available_sync, insert_auth_user

pytestmark = pytest.mark.skipif(
    not _pg_available_sync,
    reason="Local Supabase Postgres not available (run `make infra`)",
)

MODEL_ID = "claude-sonnet-4-6"
SYSTEM_PROMPT = SystemPrompt(text="you are sevino", hash="hash-int")


# ---------- helpers ----------


def _stub_response(
    *, text: str = "hi", stop_reason: str = "end_turn"
) -> Message:
    return Message(
        id="msg_int_1",
        content=[TextBlock(text=text, type="text")],
        model=MODEL_ID,
        role="assistant",
        stop_reason=stop_reason,
        type="message",
        usage=Usage(input_tokens=42, output_tokens=11),
    )


class _FakeStream:
    """Async iterable + ``get_final_message()`` mimicking ``AsyncMessageStream``."""

    def __init__(self, events: list[Any], final_message: Message) -> None:
        self._events = events
        self._index = 0
        self._final = final_message

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


class _RaisingStreamManager:
    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    async def __aenter__(self) -> Any:
        raise self._exc

    async def __aexit__(self, *exc: Any) -> None:
        return None


def _events_for_text(text_value: str) -> list[Any]:
    """Generate the minimal raw event sequence for a single text block."""
    return [
        RawContentBlockStartEvent(
            content_block=TextBlock(text="", type="text"),
            index=0,
            type="content_block_start",
        ),
        RawContentBlockDeltaEvent(
            delta=AnthropicTextDelta(text=text_value, type="text_delta"),
            index=0,
            type="content_block_delta",
        ),
        RawContentBlockStopEvent(index=0, type="content_block_stop"),
    ]


def _stub_client(response_or_exc: Any) -> Any:
    """Build a fake ``AsyncAnthropic`` whose ``messages.stream`` produces
    a context manager streaming events that accumulate to ``response_or_exc``
    (or raises in ``__aenter__`` if it's a ``BaseException``).

    ``messages.stream`` is replaced with a sync ``MagicMock`` (the SDK
    method is sync — only the manager it returns is awaitable) so tests
    can use ``.assert_not_called()`` / call-count assertions.
    """
    from unittest.mock import MagicMock

    client = AsyncMock(spec=anthropic.AsyncAnthropic)
    if isinstance(response_or_exc, BaseException):
        client.messages.stream = MagicMock(
            return_value=_RaisingStreamManager(response_or_exc)
        )
    else:
        events = _events_for_text(response_or_exc.content[0].text)
        client.messages.stream = MagicMock(
            return_value=_FakeStreamManager(
                _FakeStream(events, response_or_exc)
            )
        )
    return client


class _Fixture:
    """Convenience bag for a setup user + conversation that auto-cleans."""

    def __init__(
        self,
        *,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        engine,
    ):
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.engine = engine

    async def cleanup(self) -> None:
        async with AsyncSession(
            bind=self.engine, expire_on_commit=False
        ) as cleanup:
            # Delete in FK-safe order: tool_executions → model_invocations →
            # agent_turns → messages → conversations → user_profiles → auth.users
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
    """Insert a fresh user + conversation in a committing session, yield
    handles, then delete the entire turn graph at teardown."""
    user_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    email = f"loop-{user_id}@test.local"

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


# ---------- happy path persistence shape ----------


class TestHappyPathPersistence:
    async def test_full_persistence_after_single_iteration(
        self, db_engine, fixture
    ):
        client = _stub_client(_stub_response(text="hello world"))
        db_factory = make_session_factory(db_engine)

        result = await run_agent_turn(
            user_id=fixture.user_id,
            conversation_id=fixture.conversation_id,
            user_message="how is AMD",
            anthropic_client=client,
            db_factory=db_factory,
            tool_registry=EMPTY_REGISTRY,
            http_clients=ToolHttpClients(),
            system_prompt=SYSTEM_PROMPT,
            model_config=ModelConfig(model_id=MODEL_ID),
            hard_caps=HardCaps(),
            langfuse=_NoopLangfuse(),
            environment="test",
            sse_emitter=SSEEmitter(),
        )

        assert result.terminal_state == "end_turn"
        assert result.iterations_count == 1
        # B2.4: persisted assistant blocks include the server-assigned
        # block_id from the SSE wire envelope. Validate via the canonical
        # ``BlockListAdapter`` so any drift between the loop's persistence
        # shape and the ``Block`` discriminated union surfaces here.
        restored = BlockListAdapter.validate_python(
            result.assistant_message_blocks
        )
        assert len(restored) == 1
        assert isinstance(restored[0], SevinoTextBlock)
        assert restored[0].text == "hello world"
        persisted_block_id = restored[0].block_id
        assert persisted_block_id

        # Verify via a fresh session that everything was committed.
        async with AsyncSession(bind=db_engine, expire_on_commit=False) as v:
            msgs_q = await v.execute(
                select(MessageRow)
                .where(MessageRow.conversation_id == fixture.conversation_id)
                .order_by(MessageRow.created_at.asc(), MessageRow.id.asc())
            )
            msgs = list(msgs_q.scalars().all())
            assert len(msgs) == 2
            assert msgs[0].role == "user"
            # User text block carries a server-minted ``block_id`` (matches
            # assistant block shape so the iOS resume decoder can hydrate
            # the bubble). Don't pin the ULID, just verify shape + text.
            assert len(msgs[0].content_blocks) == 1
            user_block = msgs[0].content_blocks[0]
            assert user_block["type"] == "text"
            assert user_block["text"] == "how is AMD"
            assert isinstance(user_block["block_id"], str) and user_block["block_id"]
            assert msgs[1].role == "assistant"
            assert msgs[1].content_blocks == [
                {
                    "type": "text",
                    "block_id": persisted_block_id,
                    "text": "hello world",
                }
            ]

            turns_q = await v.execute(
                select(AgentTurn).where(
                    AgentTurn.conversation_id == fixture.conversation_id
                )
            )
            turns = list(turns_q.scalars().all())
            assert len(turns) == 1
            turn = turns[0]
            assert turn.terminal_state == "end_turn"
            assert turn.error_code is None
            assert turn.iterations_count == 1
            assert turn.prompt_hash == SYSTEM_PROMPT.hash
            assert turn.model_id == MODEL_ID
            assert turn.user_message_id == msgs[0].id
            assert turn.assistant_message_id == msgs[1].id
            assert turn.total_input_tokens == 42
            assert turn.total_output_tokens == 11
            assert turn.total_cost_usd_micros > 0

            invs_q = await v.execute(
                select(ModelInvocation)
                .where(ModelInvocation.agent_turn_id == turn.id)
                .order_by(ModelInvocation.iteration_index.asc())
            )
            invs = list(invs_q.scalars().all())
            assert len(invs) == 1
            inv = invs[0]
            assert inv.iteration_index == 0
            assert inv.model_id == MODEL_ID
            assert inv.stop_reason == "end_turn"
            # JSONB shape: full request/response captured for audit + the
            # next-turn thinking-signature roundtrip A1.7 will rely on. Per
            # A1.8 the system block is persisted with its cache_control
            # marker so the audit row matches what was actually sent.
            assert inv.request_system == [
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT.text,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
            assert inv.request_messages == [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "how is AMD"}],
                }
            ]
            assert inv.response_content == [
                {"citations": None, "text": "hello world", "type": "text"}
            ]
            assert inv.input_tokens == 42
            assert inv.output_tokens == 11
            assert inv.cost_usd_micros > 0
            assert inv.latency_ms is not None


# ---------- mid-turn durability ----------


class TestMidTurnDurability:
    async def test_model_invocation_visible_from_fresh_session(
        self, db_engine, fixture
    ):
        """Decision D12 says audit rows must be durable mid-turn. A fresh
        session opened *after* ``run_agent_turn`` returns must see the
        ``model_invocations`` row — proves the per-write factory committed
        rather than holding a single transaction across the turn."""
        client = _stub_client(_stub_response())
        db_factory = make_session_factory(db_engine)

        await run_agent_turn(
            user_id=fixture.user_id,
            conversation_id=fixture.conversation_id,
            user_message="hi",
            anthropic_client=client,
            db_factory=db_factory,
            tool_registry=EMPTY_REGISTRY,
            http_clients=ToolHttpClients(),
            system_prompt=SYSTEM_PROMPT,
            model_config=ModelConfig(model_id=MODEL_ID),
            hard_caps=HardCaps(),
            langfuse=_NoopLangfuse(),
            environment="test",
            sse_emitter=SSEEmitter(),
        )

        async with AsyncSession(bind=db_engine, expire_on_commit=False) as v:
            row = await v.execute(
                text(
                    "SELECT count(*) FROM model_invocations mi "
                    "JOIN agent_turns at ON mi.agent_turn_id = at.id "
                    "WHERE at.conversation_id = :id"
                ),
                {"id": fixture.conversation_id},
            )
            assert row.scalar_one() == 1


# ---------- error path ----------


class TestErrorPath:
    async def test_anthropic_exception_persists_error_state_and_no_assistant_msg(
        self, db_engine, fixture
    ):
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        response = httpx.Response(429, request=request)
        exc = anthropic.RateLimitError(
            "rate limited", response=response, body=None
        )
        client = _stub_client(exc)
        db_factory = make_session_factory(db_engine)

        result = await run_agent_turn(
            user_id=fixture.user_id,
            conversation_id=fixture.conversation_id,
            user_message="fail please",
            anthropic_client=client,
            db_factory=db_factory,
            tool_registry=EMPTY_REGISTRY,
            http_clients=ToolHttpClients(),
            system_prompt=SYSTEM_PROMPT,
            model_config=ModelConfig(model_id=MODEL_ID),
            hard_caps=HardCaps(),
            langfuse=_NoopLangfuse(),
            environment="test",
            sse_emitter=SSEEmitter(),
        )

        assert result.terminal_state == "error"
        assert result.iterations_count == 0
        assert result.assistant_message_blocks == []

        async with AsyncSession(bind=db_engine, expire_on_commit=False) as v:
            turns_q = await v.execute(
                select(AgentTurn).where(
                    AgentTurn.conversation_id == fixture.conversation_id
                )
            )
            turn = turns_q.scalar_one()
            assert turn.terminal_state == "error"
            assert turn.error_code == "model_rate_limit"
            assert turn.assistant_message_id is None
            assert turn.iterations_count == 0

            # User message still persisted (committed before the call).
            msgs_q = await v.execute(
                select(MessageRow).where(
                    MessageRow.conversation_id == fixture.conversation_id
                )
            )
            msgs = list(msgs_q.scalars().all())
            assert len(msgs) == 1
            assert msgs[0].role == "user"

            # No model_invocations because the call failed before we had a
            # response to record.
            invs_q = await v.execute(
                select(ModelInvocation).where(
                    ModelInvocation.agent_turn_id == turn.id
                )
            )
            assert list(invs_q.scalars().all()) == []


# ---------- cap breach persistence ----------


class TestCapBreachPersistence:
    async def test_iteration_cap_breach_persists_terminal_state(
        self, db_engine, fixture
    ):
        client = _stub_client(_stub_response())
        db_factory = make_session_factory(db_engine)

        result = await run_agent_turn(
            user_id=fixture.user_id,
            conversation_id=fixture.conversation_id,
            user_message="hi",
            anthropic_client=client,
            db_factory=db_factory,
            tool_registry=EMPTY_REGISTRY,
            http_clients=ToolHttpClients(),
            system_prompt=SYSTEM_PROMPT,
            model_config=ModelConfig(model_id=MODEL_ID),
            hard_caps=HardCaps(max_iterations=0),
            langfuse=_NoopLangfuse(),
            environment="test",
            sse_emitter=SSEEmitter(),
        )

        assert result.terminal_state == "iteration_limit"
        client.messages.stream.assert_not_called()

        async with AsyncSession(bind=db_engine, expire_on_commit=False) as v:
            turn = (
                await v.execute(
                    select(AgentTurn).where(
                        AgentTurn.conversation_id == fixture.conversation_id
                    )
                )
            ).scalar_one()
            assert turn.terminal_state == "iteration_limit"
            assert turn.error_code == "turn_iteration_limit"
            assert turn.assistant_message_id is None

            invs = (
                await v.execute(
                    select(ModelInvocation).where(
                        ModelInvocation.agent_turn_id == turn.id
                    )
                )
            ).scalars().all()
            assert list(invs) == []
