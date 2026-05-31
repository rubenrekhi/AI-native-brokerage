"""T7 (SEV-612): radar attached-context reaches the AI input stream.

Asserts the request → persistence → ``to_anthropic_content`` path lands the
modal context in ``model_invocations.request_messages`` (the JSONB audit of
what was sent to Anthropic) against real Postgres. One env-gated case
(``RUN_LIVE_LLM_TESTS=1``) makes a real call to confirm the model names a
radar ticker back.
"""

from __future__ import annotations

import asyncio
import json
import os
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

from app.ai.anthropic_client import create_anthropic_client
from app.ai.models import MODELS
from app.ai.observability.langfuse import _NoopLangfuse
from app.ai.prompts import SYSTEM_PROMPT_V1, SystemPrompt
from app.ai.runtime.caps import HardCaps
from app.ai.runtime.db import make_session_factory
from app.ai.runtime.loop import run_agent_turn
from app.ai.runtime.types import EMPTY_REGISTRY, ModelConfig
from app.ai.tools import ToolHttpClients
from app.ai.transport.emitter import SSEEmitter
from app.ai.transport.events import Event
from app.models.model_invocation import ModelInvocation
from app.repositories.conversation import ConversationRepository
from tests.integration.conftest import _pg_available_sync, insert_auth_user

pytestmark = pytest.mark.skipif(
    not _pg_available_sync,
    reason="Local Supabase Postgres not available (run `make infra`)",
)

MODEL_ID = "claude-sonnet-4-6"
SYSTEM_PROMPT = SystemPrompt(text="you are sevino", hash="hash-radar")

# Mirrors ``to_anthropic_content``'s injection wrapper verbatim. Drift here
# (or there) means the model stops recognising the payload as modal context.
_ATTACHED_CONTEXT_PREFIX = (
    "[Attached context from the user's open modal — "
    "use this data to inform your response]\n"
)

# Byte-for-byte the dict iOS builds in ``AttachedContext.swift`` for
# ``case .radar`` — decimal-as-string money/percent, bool ``is_positive``.
RADAR_CONTEXT: dict[str, Any] = {
    "type": "radar",
    "items": [
        {
            "ticker": "NVDA",
            "description": "Major chipmaker in a sector you don't own",
            "price": "892.41",
            "change_percent": "2.7",
            "is_positive": True,
        },
        {
            "ticker": "AAPL",
            "description": "Largest US company by market cap",
            "price": "189.42",
            "change_percent": "1.2",
            "is_positive": True,
        },
        {
            "ticker": "JPM",
            "description": "Reports earnings Thursday — second-largest US bank",
            "price": "201.10",
            "change_percent": "-0.4",
            "is_positive": False,
        },
    ],
}


# ---------- Anthropic stub (single text block) ----------


def _stub_response(*, text_value: str = "Sure — here's what I see.") -> Message:
    return Message(
        id="msg_radar_1",
        content=[TextBlock(text=text_value, type="text")],
        model=MODEL_ID,
        role="assistant",
        stop_reason="end_turn",
        type="message",
        usage=Usage(input_tokens=64, output_tokens=12),
    )


class _FakeStream:
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


def _events_for_text(text_value: str) -> list[Any]:
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


def _stub_client(response: Message) -> Any:
    client = AsyncMock(spec=anthropic.AsyncAnthropic)
    events = _events_for_text(response.content[0].text)
    client.messages.stream = MagicMock(
        return_value=_FakeStreamManager(_FakeStream(events, response))
    )
    return client


# ---------- user + conversation fixture (auto-cleans the turn graph) ----------


class _Fixture:
    def __init__(self, *, user_id: uuid.UUID, conversation_id: uuid.UUID, engine):
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.engine = engine

    async def cleanup(self) -> None:
        async with AsyncSession(
            bind=self.engine, expire_on_commit=False
        ) as cleanup:
            # FK-safe order: invocations → turns → messages → conversation →
            # profile → auth user.
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
    email = f"radar-ctx-{user_id}@test.local"

    async with AsyncSession(bind=db_engine, expire_on_commit=False) as setup:
        await insert_auth_user(setup, user_id=user_id, email=email)
        await ConversationRepository.create_conversation(
            setup, conversation_id=conversation_id, user_id=user_id
        )
        await setup.commit()

    fix = _Fixture(user_id=user_id, conversation_id=conversation_id, engine=db_engine)
    try:
        yield fix
    finally:
        await fix.cleanup()


async def _request_messages_for_turn(
    db_engine, turn_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Read back the single invocation's ``request_messages`` — the JSONB
    record of exactly what the loop sent to Anthropic."""
    async with AsyncSession(bind=db_engine, expire_on_commit=False) as session:
        invs = (
            await session.execute(
                select(ModelInvocation)
                .where(ModelInvocation.agent_turn_id == turn_id)
                .order_by(ModelInvocation.iteration_index.asc())
            )
        ).scalars().all()
    assert len(invs) == 1
    return invs[0].request_messages


async def _drain(emitter: SSEEmitter) -> list[Event]:
    events: list[Event] = []
    async for event in emitter.iter_events():
        events.append(event)
    return events


async def _run(fixture, *, user_message: str, user_context: dict[str, Any] | None):
    client = _stub_client(_stub_response())
    return await run_agent_turn(
        user_id=fixture.user_id,
        conversation_id=fixture.conversation_id,
        user_message=user_message,
        user_context=user_context,
        anthropic_client=client,
        db_factory=make_session_factory(fixture.engine),
        tool_registry=EMPTY_REGISTRY,
        http_clients=ToolHttpClients(),
        system_prompt=SYSTEM_PROMPT,
        model_config=ModelConfig(model_id=MODEL_ID),
        hard_caps=HardCaps(),
        langfuse=_NoopLangfuse(),
        environment="test",
        sse_emitter=SSEEmitter(),
    )


# ---------- radar context flows into the Anthropic input ----------


class TestRadarContextReachesModelInput:
    async def test_radar_context_injected_as_text_block(self, db_engine, fixture):
        result = await _run(
            fixture,
            user_message="Tell me about NVDA on my radar",
            user_context=RADAR_CONTEXT,
        )
        assert result.terminal_state == "end_turn"

        request_messages = await _request_messages_for_turn(db_engine, result.turn_id)
        assert [m["role"] for m in request_messages] == ["user"]

        content = request_messages[0]["content"]
        assert len(content) == 2
        assert content[0] == {
            "type": "text",
            "text": "Tell me about NVDA on my radar",
        }

        injected = content[1]
        assert injected["type"] == "text"
        assert injected["text"].startswith(_ATTACHED_CONTEXT_PREFIX)
        for ticker in ("NVDA", "AAPL", "JPM"):
            assert ticker in injected["text"]

    async def test_injected_json_matches_ios_wire_shape(self, db_engine, fixture):
        result = await _run(
            fixture,
            user_message="What's on my radar?",
            user_context=RADAR_CONTEXT,
        )

        request_messages = await _request_messages_for_turn(db_engine, result.turn_id)
        injected_text = request_messages[0]["content"][1]["text"]
        body = injected_text[len(_ATTACHED_CONTEXT_PREFIX):]

        # The payload round-trips byte-for-byte — type tag, item count, and
        # every iOS field name/value (ticker, description, price,
        # change_percent, is_positive) survive request → history → input.
        assert json.loads(body) == RADAR_CONTEXT

    async def test_empty_radar_items_does_not_crash(self, db_engine, fixture):
        result = await _run(
            fixture,
            user_message="Anything on my radar?",
            user_context={"type": "radar", "items": []},
        )
        assert result.terminal_state == "end_turn"

        request_messages = await _request_messages_for_turn(db_engine, result.turn_id)
        content = request_messages[0]["content"]
        assert len(content) == 2
        body = content[1]["text"][len(_ATTACHED_CONTEXT_PREFIX):]
        assert json.loads(body) == {"type": "radar", "items": []}


# ---------- live LLM (env-gated) ----------


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_LLM_TESTS") != "1",
    reason="live LLM test — set RUN_LIVE_LLM_TESTS=1 to run",
)
class TestRadarContextLiveLLM:
    async def test_live_llm_references_radar_ticker(self, db_engine, fixture):
        client = create_anthropic_client()
        emitter = SSEEmitter()
        # A real streaming turn can emit far more than the 64-event queue
        # holds, so drain concurrently — otherwise ``emit`` blocks forever.
        drain_task = asyncio.create_task(_drain(emitter))
        try:
            result = await run_agent_turn(
                user_id=fixture.user_id,
                conversation_id=fixture.conversation_id,
                user_message="Tell me about NVDA on my radar.",
                user_context=RADAR_CONTEXT,
                anthropic_client=client,
                db_factory=make_session_factory(db_engine),
                tool_registry=EMPTY_REGISTRY,
                http_clients=ToolHttpClients(),
                system_prompt=SYSTEM_PROMPT_V1,
                model_config=ModelConfig(model_id=MODELS.MAIN),
                hard_caps=HardCaps(),
                langfuse=_NoopLangfuse(),
                environment="test",
                sse_emitter=emitter,
            )
        finally:
            await emitter.close()
        await drain_task

        assert result.terminal_state == "end_turn"
        reply = " ".join(
            b.get("text", "")
            for b in result.assistant_message_blocks
            if b.get("type") == "text"
        )
        assert "NVDA" in reply
