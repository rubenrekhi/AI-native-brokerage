"""Integration tests for the Phase-1 JSON chat-turn endpoint (A1.9).

Pattern mirrors ``test_loop_persistence.py``: the endpoint runs the agent
loop which commits via its own session-per-write factory, so the rolling
``db_session`` fixture can't reach those rows. We seed a fresh user in a
committing session, hit the endpoint with mocked Anthropic, query
verification rows in a fresh session, then explicitly delete the turn
graph at teardown.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock

import anthropic
import pytest
from anthropic.types import Message, TextBlock, Usage
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.anthropic_client import get_anthropic
from app.ai.runtime.db import get_db_factory, make_session_factory
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


def _stub_client(response_or_exc: Any) -> AsyncMock:
    client = AsyncMock(spec=anthropic.AsyncAnthropic)
    if isinstance(response_or_exc, BaseException):
        client.messages.create = AsyncMock(side_effect=response_or_exc)
    else:
        client.messages.create = AsyncMock(return_value=response_or_exc)
    return client


class _Fixture:
    """Seeded user + endpoint client + cleanup handle. Conversation row is
    NOT seeded — the endpoint creates it implicitly per D6."""

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
    anthropic → unset (each test installs its own stub)."""
    db_factory = make_session_factory(db_engine)

    app.dependency_overrides[get_current_user] = lambda: str(fixture.user_id)
    app.dependency_overrides[get_db_factory] = lambda: db_factory

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": TEST_API_KEY},
    ) as ac:
        yield ac

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db_factory, None)
    app.dependency_overrides.pop(get_anthropic, None)


def _install_anthropic(stub: AsyncMock) -> None:
    app.dependency_overrides[get_anthropic] = lambda: stub


# ---------- happy path ----------


class TestHappyPath:
    async def test_returns_assistant_blocks_and_persists_full_turn(
        self, db_engine, fixture, chat_client
    ):
        _install_anthropic(_stub_client(_stub_response(text="hello world")))

        response = await chat_client.post(
            f"/v1/conversations/{fixture.conversation_id}/turns",
            json={"message": "how is AMD", "idempotency_key": "k1"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body == {
            "terminal_state": "end_turn",
            "assistant_message_blocks": [
                {"type": "text", "text": "hello world"}
            ],
        }

        async with AsyncSession(bind=db_engine, expire_on_commit=False) as v:
            # Conversation row created implicitly on first turn (D6).
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
            assert msgs[0].content_blocks == [
                {"type": "text", "text": "how is AMD"}
            ]
            assert msgs[1].content_blocks == [
                {"type": "text", "text": "hello world"}
            ]

            turn = (
                await v.execute(
                    select(AgentTurn).where(
                        AgentTurn.conversation_id == fixture.conversation_id
                    )
                )
            ).scalar_one()
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

            # No turn rows created against the other user's conversation.
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
            async with AsyncSession(
                bind=db_engine, expire_on_commit=False
            ) as cleanup:
                await cleanup.execute(
                    text(
                        "DELETE FROM conversations WHERE id = :id"
                    ),
                    {"id": fixture.conversation_id},
                )
                await cleanup.execute(
                    text("DELETE FROM user_profiles WHERE id = :id"),
                    {"id": other_user_id},
                )
                await cleanup.execute(
                    text("DELETE FROM auth.users WHERE id = :id"),
                    {"id": other_user_id},
                )
                await cleanup.commit()
