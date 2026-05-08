"""Integration tests for B3.2 idempotent replay.

Per AI v0 plan B3.2 acceptance criteria (sevino-api/docs/ai-v0-plan.md):

* Send same key twice; second response matches the first byte-for-byte
  (modulo the per-stream ``id:`` field which is regenerated on each
  emit).
* ``model_invocations`` count stays at 1 across both requests — Anthropic
  is not called twice.
* Replay completes within ~500ms (no real LLM latency).

These tests exercise the full chat-turn route with a fakeredis-backed
idempotency slot, a real local Postgres for persistence, and a stubbed
Anthropic client whose call count we assert directly.
"""

from __future__ import annotations

import time
import uuid
from typing import Any
from unittest.mock import MagicMock

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
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.anthropic_client import get_anthropic
from app.ai.observability.langfuse import _NoopLangfuse, get_langfuse
from app.ai.runtime.db import get_db_factory, make_session_factory
from app.ai.transport.events import (
    Event,
    TurnStarted,
    parse_wire_frame,
)
from app.ai.transport.idempotency import _redis_key, get_idempotency_redis
from app.auth import get_current_user
from app.main import app
from app.models.agent_turn import AgentTurn
from app.models.message import Message as MessageRow
from app.models.model_invocation import ModelInvocation
from tests.integration.conftest import (
    TEST_API_KEY,
    _pg_available_sync,
    insert_auth_user,
)

pytestmark = pytest.mark.skipif(
    not _pg_available_sync,
    reason="Local Supabase Postgres not available (run `make infra`)",
)

MODEL_ID = "claude-sonnet-4-6"


def _stub_response(text_value: str = "hello world") -> Message:
    return Message(
        id="msg_replay_1",
        content=[TextBlock(text=text_value, type="text")],
        model=MODEL_ID,
        role="assistant",
        stop_reason="end_turn",
        type="message",
        usage=Usage(input_tokens=10, output_tokens=5),
    )


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
    block = message.content[0]
    return [
        RawContentBlockStartEvent(
            content_block=TextBlock(text="", type="text"),
            index=0,
            type="content_block_start",
        ),
        RawContentBlockDeltaEvent(
            delta=AnthropicTextDelta(text=block.text, type="text_delta"),
            index=0,
            type="content_block_delta",
        ),
        RawContentBlockStopEvent(index=0, type="content_block_stop"),
    ]


class _CountingAnthropic:
    """Minimal ``AsyncAnthropic`` substitute that counts ``messages.stream``
    calls so the test can assert Anthropic was only invoked on the first
    request."""

    def __init__(self, response: Message) -> None:
        self._response = response
        self.call_count = 0
        # FastAPI/anthropic SDK callers don't introspect the type, but
        # AsyncMock spec=anthropic.AsyncAnthropic gives this object the
        # right type hint surface for the dependency override.
        self.messages = MagicMock()
        self.messages.stream = self._stream

    def _stream(self, **kwargs: Any) -> _FakeStreamManager:
        self.call_count += 1
        events = _events_for(self._response)
        return _FakeStreamManager(_FakeStream(events, self._response))


async def _consume_sse(
    client: AsyncClient, url: str, *, json: dict[str, Any]
) -> tuple[list[Event], float]:
    """POST and parse the full SSE stream into typed events. Returns
    ``(events, elapsed_seconds)`` so callers can assert on replay
    latency."""
    started = time.monotonic()
    async with client.stream("POST", url, json=json) as response:
        assert response.status_code == 200, await response.aread()
        assert response.headers["content-type"].startswith("text/event-stream")
        body = (await response.aread()).decode("utf-8")
    elapsed = time.monotonic() - started
    normalised = body.replace("\r\n", "\n")
    events = [
        parse_wire_frame(frame)
        for frame in normalised.split("\n\n")
        if frame.strip()
    ]
    return events, elapsed


async def _delete_conversation_chain(
    engine,
    *,
    conversation_id: uuid.UUID,
    user_ids: list[uuid.UUID],
) -> None:
    async with AsyncSession(bind=engine, expire_on_commit=False) as cleanup:
        await cleanup.execute(
            text(
                "DELETE FROM tool_executions WHERE model_invocation_id IN ("
                "SELECT id FROM model_invocations WHERE agent_turn_id IN ("
                "SELECT id FROM agent_turns WHERE conversation_id = :id))"
            ),
            {"id": conversation_id},
        )
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
        for uid in user_ids:
            await cleanup.execute(
                text("DELETE FROM user_profiles WHERE id = :id"),
                {"id": uid},
            )
            await cleanup.execute(
                text("DELETE FROM auth.users WHERE id = :id"),
                {"id": uid},
            )
        await cleanup.commit()


class _Fixture:
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
        await _delete_conversation_chain(
            self.engine,
            conversation_id=self.conversation_id,
            user_ids=[self.user_id],
        )


@pytest.fixture
async def fixture(db_engine):
    user_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    email = f"replay-{user_id}@test.local"

    async with AsyncSession(bind=db_engine, expire_on_commit=False) as setup:
        await insert_auth_user(setup, user_id=user_id, email=email)
        await setup.commit()

    fix = _Fixture(
        user_id=user_id, conversation_id=conversation_id, engine=db_engine
    )
    try:
        yield fix
    finally:
        await fix.cleanup()


@pytest.fixture
async def chat_client(db_engine, fixture):
    db_factory = make_session_factory(db_engine)
    redis = FakeRedis()

    app.dependency_overrides[get_current_user] = lambda: str(fixture.user_id)
    app.dependency_overrides[get_db_factory] = lambda: db_factory
    app.dependency_overrides[get_langfuse] = lambda: _NoopLangfuse()
    app.dependency_overrides[get_idempotency_redis] = lambda: redis

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": TEST_API_KEY},
    ) as ac:
        yield ac

    await redis.aclose()
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db_factory, None)
    app.dependency_overrides.pop(get_anthropic, None)
    app.dependency_overrides.pop(get_langfuse, None)
    app.dependency_overrides.pop(get_idempotency_redis, None)


def _install_anthropic(stub: Any) -> None:
    app.dependency_overrides[get_anthropic] = lambda: stub


def _event_payloads(events: list[Event]) -> list[dict[str, Any]]:
    """JSON shape of every event with the per-stream ``id`` stripped.

    The AC requires that the second response matches the first
    byte-for-byte modulo the ``id`` field. Pydantic ``model_dump``
    canonicalises the JSON shape (ordered fields, no whitespace ambiguity),
    so dropping ``id`` and comparing the resulting dicts is the cleanest
    expression of that invariant.
    """
    payloads: list[dict[str, Any]] = []
    for event in events:
        dumped = event.model_dump(mode="json")
        dumped.pop("id", None)
        payloads.append(dumped)
    return payloads


class TestReplay:
    async def test_second_request_replays_first_response_byte_for_byte(
        self, db_engine, fixture, chat_client
    ):
        # AC: second response matches first byte-for-byte (modulo ``id``).
        # Also covers: model_invocations stays at 1 (the stub's call count
        # tracks Anthropic invocations directly, and we cross-check the DB
        # row count).
        stub = _CountingAnthropic(_stub_response(text_value="hello world"))
        _install_anthropic(stub)

        url = f"/v1/conversations/{fixture.conversation_id}/turns"
        body = {"message": "hi", "idempotency_key": "replay-key-1"}

        first_events, _ = await _consume_sse(chat_client, url, json=body)
        second_events, replay_elapsed = await _consume_sse(
            chat_client, url, json=body
        )

        # Anthropic was only called on the first request.
        assert stub.call_count == 1

        # Same event sequence on both responses.
        assert [type(e).__name__ for e in first_events] == [
            "TurnStarted",
            "BlockStart",
            "TextDelta",
            "BlockEnd",
            "TurnCompleted",
        ]
        assert [type(e).__name__ for e in second_events] == [
            type(e).__name__ for e in first_events
        ]

        # Byte-for-byte match modulo ``id``.
        assert _event_payloads(second_events) == _event_payloads(first_events)

        # AC: replay completes without LLM latency. The primary signal is
        # ``stub.call_count == 1`` above (Anthropic not invoked); the
        # wall-clock bound is a coarse guard against the route silently
        # falling back to a live turn. Bound generously so loaded CI
        # runners don't flake — anything well under typical Anthropic
        # latency (2s+) is sufficient evidence of a no-LLM replay.
        assert replay_elapsed < 2.0, (
            f"replay took {replay_elapsed:.3f}s; expected < 2.0s "
            "(if elapsed approaches the live-turn budget, the route "
            "is invoking Anthropic on replay)"
        )

        # DB state: exactly one agent_turn, one model_invocation, two
        # messages (user + assistant) — replay does not write new rows.
        async with AsyncSession(
            bind=db_engine, expire_on_commit=False
        ) as v:
            turn_count = await v.scalar(
                select(func.count())
                .select_from(AgentTurn)
                .where(
                    AgentTurn.conversation_id == fixture.conversation_id
                )
            )
            assert turn_count == 1

            invocation_count = await v.scalar(
                select(func.count())
                .select_from(ModelInvocation)
                .join(AgentTurn, AgentTurn.id == ModelInvocation.agent_turn_id)
                .where(
                    AgentTurn.conversation_id == fixture.conversation_id
                )
            )
            assert invocation_count == 1

            message_count = await v.scalar(
                select(func.count())
                .select_from(MessageRow)
                .where(
                    MessageRow.conversation_id == fixture.conversation_id
                )
            )
            assert message_count == 2

        # Replay reuses the original ``turn_id`` so iOS observability
        # stays stable across retries.
        first_turn_id = next(
            e.turn_id for e in first_events if isinstance(e, TurnStarted)
        )
        second_turn_id = next(
            e.turn_id for e in second_events if isinstance(e, TurnStarted)
        )
        assert first_turn_id == second_turn_id

        # Per-stream ``id`` field is regenerated, not duplicated, so the
        # assertion above isn't masking a literal-copy bug.
        first_ids = {e.id for e in first_events}
        second_ids = {e.id for e in second_events}
        assert first_ids.isdisjoint(second_ids)

    async def test_different_keys_run_separate_turns(
        self, db_engine, fixture, chat_client
    ):
        # Sanity: two requests with *different* keys both invoke Anthropic
        # and produce distinct turns, so the dedupe is keyed by
        # idempotency_key (not, say, user/conversation alone).
        stub = _CountingAnthropic(_stub_response(text_value="hello world"))
        _install_anthropic(stub)

        url = f"/v1/conversations/{fixture.conversation_id}/turns"

        await _consume_sse(
            chat_client,
            url,
            json={"message": "hi", "idempotency_key": "key-a"},
        )
        await _consume_sse(
            chat_client,
            url,
            json={"message": "hi", "idempotency_key": "key-b"},
        )

        assert stub.call_count == 2

        async with AsyncSession(
            bind=db_engine, expire_on_commit=False
        ) as v:
            turn_count = await v.scalar(
                select(func.count())
                .select_from(AgentTurn)
                .where(
                    AgentTurn.conversation_id == fixture.conversation_id
                )
            )
            assert turn_count == 2

    async def test_same_key_different_conversation_does_not_replay(
        self, db_engine, fixture, chat_client
    ):
        # Idempotency slots are keyed by ``(user_id, idempotency_key)``,
        # not by conversation. If the user reuses the same key against a
        # different conversation, the replay path must NOT serve
        # conversation A's persisted turn under conversation B's URL —
        # that would cross-wire the wire envelope's ``conversation_id``
        # with the requested URL.
        stub = _CountingAnthropic(_stub_response(text_value="hello world"))
        _install_anthropic(stub)

        first_url = f"/v1/conversations/{fixture.conversation_id}/turns"
        body = {"message": "hi", "idempotency_key": "shared-key"}

        # First request — runs the turn under conversation A.
        await _consume_sse(chat_client, first_url, json=body)
        assert stub.call_count == 1

        # Second request — same key, different conversation under the
        # same user. Must surface as 409, not a successful replay.
        other_conversation_id = uuid.uuid4()
        try:
            response = await chat_client.post(
                f"/v1/conversations/{other_conversation_id}/turns",
                json=body,
            )
            assert response.status_code == 409
            payload = response.json()
            assert payload["code"] == "IDEMPOTENCY_CONVERSATION_MISMATCH"

            # Anthropic was not re-invoked, and the original turn is
            # untouched.
            assert stub.call_count == 1

            async with AsyncSession(
                bind=db_engine, expire_on_commit=False
            ) as v:
                first_turn_count = await v.scalar(
                    select(func.count())
                    .select_from(AgentTurn)
                    .where(
                        AgentTurn.conversation_id
                        == fixture.conversation_id
                    )
                )
                assert first_turn_count == 1
                second_turn_count = await v.scalar(
                    select(func.count())
                    .select_from(AgentTurn)
                    .where(
                        AgentTurn.conversation_id == other_conversation_id
                    )
                )
                assert second_turn_count == 0
        finally:
            # Conversation B's row was created by ``ensure_owned_conversation``
            # before the idempotency check fired; clean it up so the
            # session-scoped engine doesn't accumulate orphan rows.
            await _delete_conversation_chain(
                db_engine,
                conversation_id=other_conversation_id,
                user_ids=[],
            )


class TestInFlight:
    async def test_concurrent_request_with_same_key_returns_409(
        self, fixture, chat_client
    ):
        # Acceptance for B3.1: a second request that arrives while the
        # first is still ``in_flight`` is rejected with 409 before the
        # SSE stream opens. Simulate the in-flight state by writing the
        # claim record directly — the route only reads the slot, so a
        # synthetic in_flight record is sufficient.
        import json

        # The ``chat_client`` fixture installed a fakeredis on
        # ``get_idempotency_redis``; recover it from the override so we
        # can seed the slot. Format the key via the production helper
        # (``_redis_key``) so a future change to the key shape can't
        # silently desync the test from the route's actual lookup.
        redis = app.dependency_overrides[get_idempotency_redis]()
        await redis.set(
            _redis_key(
                user_id=fixture.user_id, idempotency_key="in-flight-key"
            ),
            json.dumps(
                {
                    "status": "in_flight",
                    "turn_id": str(uuid.uuid4()),
                    "started_at": time.time(),
                }
            ),
            ex=120,
        )

        # Anthropic shouldn't be reached, but install a stub so an
        # accidental call doesn't NoneType-error. The assertion below is
        # the real signal.
        stub = _CountingAnthropic(_stub_response())
        _install_anthropic(stub)

        response = await chat_client.post(
            f"/v1/conversations/{fixture.conversation_id}/turns",
            json={"message": "hi", "idempotency_key": "in-flight-key"},
        )

        assert response.status_code == 409
        body = response.json()
        assert body["code"] == "IDEMPOTENCY_IN_FLIGHT"
        assert stub.call_count == 0
