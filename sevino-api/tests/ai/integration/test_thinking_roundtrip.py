"""Integration test for A1.7 — extended thinking + signature roundtripping.

Forces a multi-iteration turn (mocked tool-call scenario) by stubbing
Anthropic to return ``stop_reason="pause_turn"`` on iteration 1. The
loop continues per Anthropic's "continue verbatim" contract, calls
``messages.create`` again, and the second call's ``messages`` payload
must contain iteration 1's full response — including the signed
``thinking`` block — byte-for-byte (the R1 contract from the v0 plan).

The assertion is sourced from ``model_invocations.request_messages``
JSONB rather than the in-memory mock so we exercise the same source of
truth that production reads from on iteration N+1.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock

import anthropic
import pytest
from anthropic.types import (
    Message,
    RawContentBlockDeltaEvent,
    RawContentBlockStartEvent,
    RawContentBlockStopEvent,
    TextBlock,
    TextDelta as AnthropicTextDelta,
    ThinkingBlock,
    ThinkingDelta,
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
from app.ai.runtime.types import EMPTY_REGISTRY, ModelConfig
from app.ai.tools import ToolHttpClients
from app.ai.transport.emitter import SSEEmitter
from app.models.agent_turn import AgentTurn
from app.models.model_invocation import ModelInvocation
from app.repositories.conversation import ConversationRepository
from tests.integration.conftest import _pg_available_sync, insert_auth_user

pytestmark = pytest.mark.skipif(
    not _pg_available_sync,
    reason="Local Supabase Postgres not available (run `make infra`)",
)

MODEL_ID = "claude-sonnet-4-6"
SYSTEM_PROMPT = SystemPrompt(text="you are sevino", hash="hash-thinking")


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
    """Generate a raw event sequence accumulating to ``message``.

    Mirrors the SDK's bracket pattern (``content_block_start`` →
    body deltas → ``content_block_stop``) for text and thinking blocks;
    other block types pass through with the start/stop bracket only.
    """
    events: list[Any] = []
    for index, block in enumerate(message.content):
        if block.type == "text":
            start_block = TextBlock(text="", type="text", citations=None)
        elif block.type == "thinking":
            start_block = ThinkingBlock(
                thinking="", signature="", type="thinking"
            )
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
                    delta=AnthropicTextDelta(
                        text=block.text, type="text_delta"
                    ),
                    index=index,
                    type="content_block_delta",
                )
            )
        elif block.type == "thinking" and block.thinking:
            events.append(
                RawContentBlockDeltaEvent(
                    delta=ThinkingDelta(
                        thinking=block.thinking, type="thinking_delta"
                    ),
                    index=index,
                    type="content_block_delta",
                )
            )
        events.append(
            RawContentBlockStopEvent(
                index=index, type="content_block_stop"
            )
        )
    return events


def _stub_client(responses: list[Message]) -> AsyncMock:
    """Fake ``AsyncAnthropic`` whose ``messages.stream`` cycles through
    each entry in ``responses``, yielding one stream-manager per call."""
    from unittest.mock import MagicMock

    client = AsyncMock(spec=anthropic.AsyncAnthropic)
    managers = [
        _FakeStreamManager(_FakeStream(_events_for(r), r)) for r in responses
    ]
    client.messages.stream = MagicMock(side_effect=managers)
    return client


async def _setup_user_and_conversation(
    db_engine,
) -> tuple[uuid.UUID, uuid.UUID]:
    user_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    email = f"thinking-{user_id}@test.local"
    async with AsyncSession(bind=db_engine, expire_on_commit=False) as setup:
        await insert_auth_user(setup, user_id=user_id, email=email)
        await ConversationRepository.create_conversation(
            setup, conversation_id=conversation_id, user_id=user_id
        )
        await setup.commit()
    return user_id, conversation_id


async def _cleanup(db_engine, conversation_id: uuid.UUID, user_id: uuid.UUID) -> None:
    async with AsyncSession(bind=db_engine, expire_on_commit=False) as cleanup:
        await cleanup.execute(
            text(
                "DELETE FROM model_invocations WHERE agent_turn_id IN ("
                "SELECT id FROM agent_turns WHERE conversation_id = :id)"
            ),
            {"id": conversation_id},
        )
        await cleanup.execute(
            text("DELETE FROM agent_turns WHERE conversation_id = :id"),
            {"id": conversation_id},
        )
        await cleanup.execute(
            text("DELETE FROM messages WHERE conversation_id = :id"),
            {"id": conversation_id},
        )
        await cleanup.execute(
            text("DELETE FROM conversations WHERE id = :id"),
            {"id": conversation_id},
        )
        await cleanup.execute(
            text("DELETE FROM user_profiles WHERE id = :id"),
            {"id": user_id},
        )
        await cleanup.execute(
            text("DELETE FROM auth.users WHERE id = :id"),
            {"id": user_id},
        )
        await cleanup.commit()


async def test_iteration_two_request_messages_contain_iteration_one_signature(
    db_engine,
):
    """Iteration 2's ``request_messages`` JSONB must include iteration 1's
    full response content — thinking block + signature — verbatim. This is
    the only way Anthropic accepts a follow-up turn (it 400s on missing
    signatures), so the audit row is the durable source of truth."""
    iter_1_thinking = ThinkingBlock(
        thinking="The user asked about AMD; let me think through this carefully.",
        signature="sig_iteration_1_abcdef",
        type="thinking",
    )
    iter_1_tool_use = ToolUseBlock(
        id="toolu_01abc",
        name="get_stock_info",
        input={"symbol": "AMD"},
        type="tool_use",
    )
    iter_1 = Message(
        id="msg_iter_1",
        content=[iter_1_thinking, iter_1_tool_use],
        model=MODEL_ID,
        role="assistant",
        stop_reason="pause_turn",
        type="message",
        usage=Usage(input_tokens=120, output_tokens=80),
    )
    iter_2_thinking = ThinkingBlock(
        thinking="With the data in hand the answer is straightforward.",
        signature="sig_iteration_2_xyz",
        type="thinking",
    )
    iter_2 = Message(
        id="msg_iter_2",
        content=[iter_2_thinking, TextBlock(text="AMD is up 2%.", type="text")],
        model=MODEL_ID,
        role="assistant",
        stop_reason="end_turn",
        type="message",
        usage=Usage(input_tokens=200, output_tokens=40),
    )

    user_id, conversation_id = await _setup_user_and_conversation(db_engine)
    try:
        client = _stub_client([iter_1, iter_2])
        db_factory = make_session_factory(db_engine)

        result = await run_agent_turn(
            user_id=user_id,
            conversation_id=conversation_id,
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
        assert result.iterations_count == 2
        assert client.messages.stream.call_count == 2

        # Both stream() calls must carry the adaptive thinking config.
        for call in client.messages.stream.call_args_list:
            assert call.kwargs["thinking"] == {"type": "adaptive"}
            assert call.kwargs["output_config"] == {"effort": "high"}

        async with AsyncSession(bind=db_engine, expire_on_commit=False) as v:
            invs = (
                (
                    await v.execute(
                        select(ModelInvocation)
                        .join(AgentTurn, ModelInvocation.agent_turn_id == AgentTurn.id)
                        .where(AgentTurn.conversation_id == conversation_id)
                        .order_by(ModelInvocation.iteration_index.asc())
                    )
                )
                .scalars()
                .all()
            )
            assert len(invs) == 2

            iter_0_row, iter_1_row = invs

            # Iteration 0's response_content is the persisted source of
            # truth: thinking block with signature, plus the tool_use block.
            response_content = iter_0_row.response_content
            assert response_content is not None
            thinking_in_response = next(
                (b for b in response_content if b.get("type") == "thinking"),
                None,
            )
            assert thinking_in_response is not None
            assert thinking_in_response["signature"] == "sig_iteration_1_abcdef"
            assert (
                thinking_in_response["thinking"]
                == iter_1_thinking.thinking
            )

            # Iteration 1's request_messages must include iteration 0's
            # response verbatim as an assistant message.
            request_messages = iter_1_row.request_messages
            assistant_turns = [
                m for m in request_messages if m["role"] == "assistant"
            ]
            assert len(assistant_turns) == 1, (
                f"expected exactly one assistant turn in iteration 2's "
                f"request, got {len(assistant_turns)}"
            )
            roundtripped_content = assistant_turns[0]["content"]
            # Byte-for-byte equality: the JSONB row matches what the loop
            # appended from iteration 0's response_content.
            assert roundtripped_content == response_content

        # ``total_thinking_tokens`` sums the per-iteration heuristic.
        async with AsyncSession(bind=db_engine, expire_on_commit=False) as v:
            turn = (
                await v.execute(
                    select(AgentTurn).where(
                        AgentTurn.conversation_id == conversation_id
                    )
                )
            ).scalar_one()
            expected = (
                len(iter_1_thinking.thinking) // 4
                + len(iter_2_thinking.thinking) // 4
            )
            assert turn.total_thinking_tokens == expected
            # Sanity: the per-invocation column rolls up to the same total.
            per_iter_sum = sum(inv.thinking_tokens for inv in invs)
            assert per_iter_sum == expected
    finally:
        await _cleanup(db_engine, conversation_id, user_id)
