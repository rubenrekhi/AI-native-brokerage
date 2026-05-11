"""Integration tests for ``GET /v1/conversations/{id}/messages`` (SEV-564)."""

import base64
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.conversation import ConversationRepository
from tests.integration.conftest import _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync,
    reason="Local Supabase Postgres not available (run `make infra`)",
)


def _decode_cursor(cursor: str) -> dict:
    raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
    return json.loads(raw)


async def _seed_conversation_with_turn(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    user_text: str = "Hi",
    assistant_text: str = "Hello!",
) -> uuid.UUID:
    """Same caveat as ``test_conversations_list._seed_conversation`` — push the
    assistant message's ``created_at`` forward by 1s so the ASC order is
    deterministic inside a single test transaction.
    """
    conv_id = uuid.uuid4()
    await ConversationRepository.create_conversation(
        db, conversation_id=conv_id, user_id=user_id
    )
    await ConversationRepository.append_user_message(
        db,
        conversation_id=conv_id,
        content_blocks=[{"type": "text", "text": user_text}],
    )
    assistant_msg = await ConversationRepository.append_assistant_message(
        db,
        conversation_id=conv_id,
        content_blocks=[{"type": "text", "text": assistant_text}],
    )
    await db.execute(
        text(
            "UPDATE messages SET created_at = created_at + interval '1 second' "
            "WHERE id = :id"
        ),
        {"id": assistant_msg.id},
    )
    await db.flush()
    return conv_id


class TestList:
    async def test_returns_messages_ordered_oldest_first(
        self,
        authenticated_db_client: AsyncClient,
        db_session: AsyncSession,
        test_user,
    ):
        conv_id = await _seed_conversation_with_turn(
            db_session,
            user_id=test_user,
            user_text="What is AAPL?",
            assistant_text="Apple Inc. (AAPL) is a technology company …",
        )

        response = await authenticated_db_client.get(
            f"/v1/conversations/{conv_id}/messages"
        )
        body = response.json()

        assert response.status_code == 200, response.text
        assert len(body["items"]) == 2
        assert body["items"][0]["role"] == "user"
        assert body["items"][1]["role"] == "assistant"
        # content_blocks comes back verbatim — text block decoding upstream.
        assert (
            body["items"][0]["content_blocks"][0]["text"] == "What is AAPL?"
        )
        assert body["items"][1]["content_blocks"][0]["text"].startswith(
            "Apple Inc."
        )

    async def test_empty_conversation_returns_empty_items(
        self,
        authenticated_db_client: AsyncClient,
        db_session: AsyncSession,
        test_user,
    ):
        conv_id = uuid.uuid4()
        await ConversationRepository.create_conversation(
            db_session, conversation_id=conv_id, user_id=test_user
        )
        await db_session.flush()

        response = await authenticated_db_client.get(
            f"/v1/conversations/{conv_id}/messages"
        )
        body = response.json()

        assert response.status_code == 200, response.text
        assert body["items"] == []
        assert body["next_cursor"] is None


class TestOwnerScoping:
    async def test_foreign_conversation_returns_404_not_403(
        self,
        authenticated_db_client: AsyncClient,
        db_session: AsyncSession,
        test_user,
        make_extra_user,
    ):
        other_user = await make_extra_user()
        foreign_conv = await _seed_conversation_with_turn(
            db_session, user_id=other_user
        )

        response = await authenticated_db_client.get(
            f"/v1/conversations/{foreign_conv}/messages"
        )

        # 404, not 403 — avoid leaking that the conversation exists under
        # another owner.
        assert response.status_code == 404, response.text

    async def test_missing_conversation_returns_404(
        self,
        authenticated_db_client: AsyncClient,
    ):
        missing = uuid.uuid4()
        response = await authenticated_db_client.get(
            f"/v1/conversations/{missing}/messages"
        )
        assert response.status_code == 404


class TestPagination:
    async def test_cursor_walks_through_pages(
        self,
        authenticated_db_client: AsyncClient,
        db_session: AsyncSession,
        test_user,
    ):
        # Seed 5 messages with deterministic created_at so ordering is
        # reproducible across simulator loads.
        conv_id = uuid.uuid4()
        await ConversationRepository.create_conversation(
            db_session, conversation_id=conv_id, user_id=test_user
        )
        base = datetime.now(timezone.utc) - timedelta(minutes=10)
        message_ids: list[uuid.UUID] = []
        for i in range(5):
            msg = await ConversationRepository.append_user_message(
                db_session,
                conversation_id=conv_id,
                content_blocks=[{"type": "text", "text": f"msg {i}"}],
            )
            message_ids.append(msg.id)
            await db_session.execute(
                text("UPDATE messages SET created_at = :ts WHERE id = :id"),
                {"ts": base + timedelta(seconds=i), "id": msg.id},
            )
        await db_session.flush()

        first = await authenticated_db_client.get(
            f"/v1/conversations/{conv_id}/messages?limit=2"
        )
        body1 = first.json()
        assert first.status_code == 200, first.text
        assert [it["id"] for it in body1["items"]] == [
            str(message_ids[0]),
            str(message_ids[1]),
        ]
        assert body1["next_cursor"] is not None

        second = await authenticated_db_client.get(
            f"/v1/conversations/{conv_id}/messages?limit=2"
            f"&cursor={body1['next_cursor']}"
        )
        body2 = second.json()
        assert [it["id"] for it in body2["items"]] == [
            str(message_ids[2]),
            str(message_ids[3]),
        ]

        third = await authenticated_db_client.get(
            f"/v1/conversations/{conv_id}/messages?limit=2"
            f"&cursor={body2['next_cursor']}"
        )
        body3 = third.json()
        assert [it["id"] for it in body3["items"]] == [str(message_ids[4])]
        assert body3["next_cursor"] is None

    async def test_invalid_cursor_returns_422(
        self,
        authenticated_db_client: AsyncClient,
        db_session: AsyncSession,
        test_user,
    ):
        conv_id = await _seed_conversation_with_turn(
            db_session, user_id=test_user
        )
        response = await authenticated_db_client.get(
            f"/v1/conversations/{conv_id}/messages?cursor=junk"
        )
        assert response.status_code == 422


class TestAuth:
    async def test_requires_authentication(self, client: AsyncClient):
        response = await client.get(
            f"/v1/conversations/{uuid.uuid4()}/messages"
        )
        assert response.status_code == 401
