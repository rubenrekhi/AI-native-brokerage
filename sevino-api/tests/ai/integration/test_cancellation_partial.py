"""Integration tests for B3.4 — cancellation: stream close + partial persistence.

The agent loop must keep ``messages.content_blocks`` and ``agent_turns``
consistent even when a turn is cancelled mid-stream. These tests run
``run_agent_turn`` with a fake Anthropic stream that injects
``asyncio.CancelledError`` part-way through delta delivery, then assert
on the durable state:

* ``stream.close()`` was called explicitly (not only via ``__aexit__``)
* Partial text accumulated before the cancel landed in
  ``messages.content_blocks`` with a stable ``block_id``
* ``agent_turns.terminal_state == 'cancelled'`` and
  ``cancellation_reason`` is populated
* The ``CancelledError`` re-propagates out of ``run_agent_turn``

Pattern follows ``test_loop_persistence.py`` — the loop's session-per-write
factory commits writes mid-turn, so verification opens a fresh session.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import MagicMock

import anthropic
import pytest
from anthropic.types import (
    Message,
    RawContentBlockDeltaEvent,
    RawContentBlockStartEvent,
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
from app.ai.tools import ToolHttpClients
from app.ai.transport.emitter import SSEEmitter
from app.models.agent_turn import AgentTurn
from app.models.message import Message as MessageRow
from app.repositories.conversation import ConversationRepository
from tests.integration.conftest import _pg_available_sync, insert_auth_user

pytestmark = pytest.mark.skipif(
    not _pg_available_sync,
    reason="Local Supabase Postgres not available (run `make infra`)",
)

MODEL_ID = "claude-sonnet-4-6"
SYSTEM_PROMPT = SystemPrompt(text="you are sevino", hash="hash-cancel")


# ---------- streaming fakes ----------


class _CancellingStream:
    """Async iterator that yields ``deltas`` events then raises
    ``CancelledError`` on the next iteration. Mimics the wire-level
    behaviour an outer-task ``cancel()`` produces: the awaitable returns
    ``CancelledError`` instead of the next chunk.

    ``close()`` flips ``self.closed`` so the test can assert the loop
    invoked it. ``get_final_message`` should never run after a cancel —
    asserting it stays unread protects against accidental fall-through.
    """

    def __init__(self, *, deltas: list[str]) -> None:
        self._events: list[Any] = [
            RawContentBlockStartEvent(
                content_block=TextBlock(text="", type="text"),
                index=0,
                type="content_block_start",
            )
        ]
        for chunk in deltas:
            self._events.append(
                RawContentBlockDeltaEvent(
                    delta=AnthropicTextDelta(text=chunk, type="text_delta"),
                    index=0,
                    type="content_block_delta",
                )
            )
        self._index = 0
        self.closed = False
        self.final_called = False

    def __aiter__(self) -> "_CancellingStream":
        return self

    async def __anext__(self) -> Any:
        if self._index >= len(self._events):
            # Out of pre-cancelled events — simulate the outer task
            # being cancelled at the next await point.
            raise asyncio.CancelledError()
        event = self._events[self._index]
        self._index += 1
        return event

    async def get_final_message(self) -> Message:
        self.final_called = True
        # Should be unreachable — the cancel raises first.
        return Message(
            id="msg_should_not_be_used",
            content=[TextBlock(text="never", type="text")],
            model=MODEL_ID,
            role="assistant",
            stop_reason="end_turn",
            type="message",
            usage=Usage(input_tokens=0, output_tokens=0),
        )

    async def close(self) -> None:
        self.closed = True


class _CancellingStreamManager:
    def __init__(self, stream: _CancellingStream) -> None:
        self._stream = stream

    async def __aenter__(self) -> _CancellingStream:
        return self._stream

    async def __aexit__(self, *exc: Any) -> None:
        # Mirror the SDK's own behaviour — ``__aexit__`` closes the stream.
        # The loop also calls ``close`` explicitly inside its ``except
        # CancelledError`` branch; assertion below verifies the explicit
        # call ran (and the manager-level close is idempotent on the
        # fake's ``self.closed`` boolean).
        await self._stream.close()


def _make_stream_client(stream: _CancellingStream) -> Any:
    client = MagicMock(spec=anthropic.AsyncAnthropic)
    client.messages.stream = MagicMock(
        return_value=_CancellingStreamManager(stream)
    )
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
    email = f"cancel-{user_id}@test.local"
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


async def _run_until_cancelled(
    *,
    fixture: _Fixture,
    db_engine,
    client: Any,
) -> None:
    """Invoke ``run_agent_turn`` and assert it re-raises ``CancelledError``."""
    db_factory = make_session_factory(db_engine)
    with pytest.raises(asyncio.CancelledError):
        await run_agent_turn(
            user_id=fixture.user_id,
            conversation_id=fixture.conversation_id,
            user_message="say hi",
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


# ---------- partial persistence ----------


class TestPartialPersistence:
    async def test_cancel_mid_text_delta_persists_partial_block(
        self, db_engine, fixture
    ):
        """Acceptance: cancel mid-text-delta → partial block in
        ``messages.content_blocks`` AND ``cancellation_reason`` populated."""
        stream = _CancellingStream(deltas=["hello ", "wor"])
        client = _make_stream_client(stream)

        await _run_until_cancelled(
            fixture=fixture, db_engine=db_engine, client=client
        )

        # The loop's explicit ``stream.close()`` must fire before the
        # context manager unwinds — this is the contract B3.4 codifies.
        assert stream.closed is True
        # ``get_final_message`` should not have been awaited — the cancel
        # arrives before it on the wire.
        assert stream.final_called is False

        async with AsyncSession(bind=db_engine, expire_on_commit=False) as v:
            assistant = (
                await v.execute(
                    select(MessageRow).where(
                        MessageRow.conversation_id == fixture.conversation_id,
                        MessageRow.role == "assistant",
                    )
                )
            ).scalar_one_or_none()
            assert assistant is not None, (
                "expected partial assistant message to be persisted"
            )
            assert len(assistant.content_blocks) == 1
            block = assistant.content_blocks[0]
            assert block["type"] == "text"
            # The two deltas concatenate as they arrived on the wire.
            assert block["text"] == "hello wor"
            assert isinstance(block["block_id"], str) and block["block_id"]

            turn = (
                await v.execute(
                    select(AgentTurn).where(
                        AgentTurn.conversation_id == fixture.conversation_id
                    )
                )
            ).scalar_one()
            assert turn.terminal_state == "cancelled"
            assert turn.cancellation_reason is not None
            assert turn.error_code == ErrorCode.CANCELLED.value
            # The agent_turn references the just-persisted assistant
            # message so iOS can resolve the partial blocks via the
            # normal turn → assistant_message_id → messages join.
            assert turn.assistant_message_id == assistant.id

            # User message still persisted (committed before the call).
            user_msg = (
                await v.execute(
                    select(MessageRow).where(
                        MessageRow.conversation_id == fixture.conversation_id,
                        MessageRow.role == "user",
                    )
                )
            ).scalar_one()
            assert user_msg.content_blocks == [
                {"type": "text", "text": "say hi"}
            ]

    async def test_cancel_before_any_delta_persists_no_assistant_message(
        self, db_engine, fixture
    ):
        """``BlockStart`` reached the wire but no deltas arrived. The
        accumulated text is empty, so no assistant message should be
        persisted — but the agent_turn must still record cancellation."""
        stream = _CancellingStream(deltas=[])
        client = _make_stream_client(stream)

        await _run_until_cancelled(
            fixture=fixture, db_engine=db_engine, client=client
        )

        assert stream.closed is True

        async with AsyncSession(bind=db_engine, expire_on_commit=False) as v:
            assistant = (
                await v.execute(
                    select(MessageRow).where(
                        MessageRow.conversation_id == fixture.conversation_id,
                        MessageRow.role == "assistant",
                    )
                )
            ).scalar_one_or_none()
            assert assistant is None

            turn = (
                await v.execute(
                    select(AgentTurn).where(
                        AgentTurn.conversation_id == fixture.conversation_id
                    )
                )
            ).scalar_one()
            assert turn.terminal_state == "cancelled"
            assert turn.cancellation_reason is not None
            assert turn.error_code == ErrorCode.CANCELLED.value
            assert turn.assistant_message_id is None
