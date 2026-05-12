"""Integration tests for the Phase-2 SSE chat-turn endpoint (B2.3).

Replaces ``test_chat_endpoint_json.py``. Same DB-persistence assertions —
the loop's session-per-write factory still commits user/assistant rows
mid-turn, so the rolling ``db_session`` fixture can't reach those rows
and we use the same fresh-session pattern. The new shape is the response
itself: instead of a JSON body, the test parses the SSE event stream and
asserts on the event sequence.
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
    Usage,
)
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.anthropic_client import get_anthropic
from app.ai.observability.langfuse import _NoopLangfuse, get_langfuse
from app.ai.runtime.db import get_db_factory, make_session_factory
from app.ai.transport.idempotency import get_idempotency_redis
from app.ai.transport.events import (
    BlockEnd,
    BlockStart,
    Event,
    TextDelta,
    TurnCompleted,
    TurnStarted,
    parse_wire_frame,
)
from app.auth import get_current_user
from app.main import app
from app.models.agent_turn import AgentTurn
from app.models.conversation import Conversation
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


def _stub_response(
    *, text: str = "hi from claude", stop_reason: str = "end_turn"
) -> Message:
    return Message(
        id="msg_endpoint_1",
        content=[TextBlock(text=text, type="text")],
        model=MODEL_ID,
        role="assistant",
        stop_reason=stop_reason,
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
    """Stream of raw events that accumulate to ``message``. Mirrors what
    Anthropic emits for a single text-block response."""
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


def _stub_client(response_or_exc: Any) -> AsyncMock:
    """Fake ``AsyncAnthropic`` whose ``messages.stream`` returns a context
    manager that streams events for ``response_or_exc`` (or that raises in
    ``__aenter__`` if a ``BaseException`` is passed)."""
    from unittest.mock import MagicMock

    client = AsyncMock(spec=anthropic.AsyncAnthropic)
    if isinstance(response_or_exc, BaseException):
        class _RaisingManager:
            async def __aenter__(self) -> Any:
                raise response_or_exc

            async def __aexit__(self, *exc: Any) -> None:
                return None

        client.messages.stream = MagicMock(return_value=_RaisingManager())
    else:
        events = _events_for(response_or_exc)
        client.messages.stream = MagicMock(
            return_value=_FakeStreamManager(_FakeStream(events, response_or_exc))
        )
    return client


async def _consume_sse(
    client: AsyncClient, url: str, *, json: dict[str, Any]
) -> list[Event]:
    """POST and parse the full SSE stream into typed events.

    Frames are separated by a blank line on the wire. ``parse_wire_frame``
    re-validates the JSON ``data`` payload back into the
    :class:`~app.ai.transport.events.Event` discriminated union and checks
    that the ``id:`` / ``event:`` lines match the JSON ``id`` / ``type``
    fields, so a desync between the two would fail the test loudly.
    """
    async with client.stream("POST", url, json=json) as response:
        assert response.status_code == 200, await response.aread()
        assert response.headers["content-type"].startswith("text/event-stream")
        body = (await response.aread()).decode("utf-8")
    # sse-starlette emits CRLF; normalise so a single split rule works.
    normalised = body.replace("\r\n", "\n")
    return [
        parse_wire_frame(frame)
        for frame in normalised.split("\n\n")
        if frame.strip()
    ]


async def _delete_conversation_chain(
    engine,
    *,
    conversation_id: uuid.UUID,
    user_ids: list[uuid.UUID],
) -> None:
    """Tear down rows in FK-respecting order for a single conversation."""
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
    """Seeded user + cleanup handle. Conversation row is NOT seeded — the
    endpoint creates it implicitly per D6."""

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
    email = f"chat-endpoint-{user_id}@test.local"

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
    """AsyncClient with: auth → fixture.user_id, db_factory → real engine,
    anthropic → unset (each test installs its own stub), idempotency
    redis → per-test fakeredis so B3.2 claim/replay state doesn't leak
    across tests."""
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


def _install_anthropic(stub: AsyncMock) -> None:
    app.dependency_overrides[get_anthropic] = lambda: stub


# ---------- happy path ----------


class TestHappyPath:
    async def test_streams_event_sequence_and_persists_full_turn(
        self, db_engine, fixture, chat_client
    ):
        _install_anthropic(_stub_client(_stub_response(text="hello world")))

        events = await _consume_sse(
            chat_client,
            f"/v1/conversations/{fixture.conversation_id}/turns",
            json={"message": "how is AMD", "idempotency_key": "k1"},
        )

        # Wire envelope: turn_started → block_start/text_delta/block_end → turn_completed.
        assert [type(e) for e in events] == [
            TurnStarted,
            BlockStart,
            TextDelta,
            BlockEnd,
            TurnCompleted,
        ]

        started = events[0]
        assert isinstance(started, TurnStarted)
        assert started.conversation_id == fixture.conversation_id

        block_start = events[1]
        assert isinstance(block_start, BlockStart)
        assert block_start.block["type"] == "text"
        block_id = block_start.block["block_id"]

        delta = events[2]
        assert isinstance(delta, TextDelta)
        assert delta.block_id == block_id
        assert delta.text == "hello world"

        block_end = events[3]
        assert isinstance(block_end, BlockEnd)
        assert block_end.block_id == block_id

        completed = events[4]
        assert isinstance(completed, TurnCompleted)
        assert completed.terminal_state == "end_turn"
        assert completed.iterations_count == 1
        assert completed.turn_id == started.turn_id

        # All events carry stable ULIDs and they're unique within the stream.
        ids = [e.id for e in events]
        assert len(set(ids)) == len(ids)
        assert all(ids)

        # DB rows produced by the loop persist regardless of transport.
        async with AsyncSession(bind=db_engine, expire_on_commit=False) as v:
            conv = await v.get(Conversation, fixture.conversation_id)
            assert conv is not None
            assert conv.user_id == fixture.user_id

            msgs = list(
                (
                    await v.execute(
                        select(MessageRow)
                        .where(
                            MessageRow.conversation_id
                            == fixture.conversation_id
                        )
                        .order_by(
                            MessageRow.created_at.asc(), MessageRow.id.asc()
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert [m.role for m in msgs] == ["user", "assistant"]
            # User text block carries a server-minted ``block_id`` for the
            # iOS resume decoder; assert shape without pinning the ULID.
            assert len(msgs[0].content_blocks) == 1
            user_block = msgs[0].content_blocks[0]
            assert user_block["type"] == "text"
            assert user_block["text"] == "how is AMD"
            assert isinstance(user_block["block_id"], str) and user_block["block_id"]
            # B2.4: persisted assistant blocks carry the same block_id the
            # ``block_start`` frame announced, so iOS can correlate the
            # streamed envelope with the durable row.
            assert msgs[1].content_blocks == [
                {"type": "text", "block_id": block_id, "text": "hello world"}
            ]

            turn = (
                await v.execute(
                    select(AgentTurn).where(
                        AgentTurn.conversation_id == fixture.conversation_id
                    )
                )
            ).scalar_one()
            # B2.4 plumbs the loop's ``agent_turns.id`` through ``turn_started``
            # / ``turn_completed`` so the wire envelope and the DB row share
            # the same UUID.
            assert turn.id == started.turn_id
            assert turn.terminal_state == "end_turn"
            assert turn.user_id == fixture.user_id
            assert turn.iterations_count == 1
            assert turn.user_message_id == msgs[0].id
            assert turn.assistant_message_id == msgs[1].id

            invs = list(
                (
                    await v.execute(
                        select(ModelInvocation).where(
                            ModelInvocation.agent_turn_id == turn.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(invs) == 1
            assert invs[0].stop_reason == "end_turn"


# ---------- request validation ----------


class TestRequestValidation:
    """Validation runs before the SSE stream opens — failures come back
    as the standard JSON error body, not as an SSE error frame."""

    async def test_missing_idempotency_key_rejected(
        self, fixture, chat_client
    ):
        _install_anthropic(_stub_client(_stub_response()))

        response = await chat_client.post(
            f"/v1/conversations/{fixture.conversation_id}/turns",
            json={"message": "hi"},
        )

        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_ERROR"

    async def test_empty_message_rejected(self, fixture, chat_client):
        _install_anthropic(_stub_client(_stub_response()))

        response = await chat_client.post(
            f"/v1/conversations/{fixture.conversation_id}/turns",
            json={"message": "", "idempotency_key": "k1"},
        )

        assert response.status_code == 422


# ---------- ownership ----------


class TestOwnership:
    async def test_other_users_conversation_returns_404(
        self, db_engine, fixture, chat_client
    ):
        # Seed a conversation owned by a *different* user. The endpoint
        # should refuse to write to it under the test_user's auth.
        other_user_id = uuid.uuid4()
        async with AsyncSession(
            bind=db_engine, expire_on_commit=False
        ) as setup:
            await insert_auth_user(
                setup,
                user_id=other_user_id,
                email=f"other-{other_user_id}@test.local",
            )
            setup.add(
                Conversation(
                    id=fixture.conversation_id, user_id=other_user_id
                )
            )
            await setup.commit()

        try:
            _install_anthropic(_stub_client(_stub_response()))

            response = await chat_client.post(
                f"/v1/conversations/{fixture.conversation_id}/turns",
                json={"message": "hi", "idempotency_key": "k1"},
            )

            assert response.status_code == 404
            assert response.json()["code"] == "NOT_FOUND"

            async with AsyncSession(
                bind=db_engine, expire_on_commit=False
            ) as v:
                turns = list(
                    (
                        await v.execute(
                            select(AgentTurn).where(
                                AgentTurn.conversation_id
                                == fixture.conversation_id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                assert turns == []
        finally:
            await _delete_conversation_chain(
                db_engine,
                conversation_id=fixture.conversation_id,
                user_ids=[other_user_id],
            )


# ---------- auth ----------


class TestAuth:
    async def test_missing_bearer_returns_401(self, fixture):
        # No auth override — exercise the real ``get_current_user``
        # dependency which raises ``AuthenticationError`` when the
        # ``Authorization`` header is missing. Acceptance criterion:
        # JWT enforcement is unchanged from the JSON endpoint.
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": TEST_API_KEY},
        ) as ac:
            response = await ac.post(
                f"/v1/conversations/{fixture.conversation_id}/turns",
                json={"message": "hi", "idempotency_key": "k1"},
            )

        assert response.status_code == 401
        assert response.json()["code"] == "AUTHENTICATION_ERROR"
