"""Integration tests for ``GET /v1/conversations`` (SEV-564).

These tests run against the real local Supabase Postgres so the
``last_message_at`` denormalisation, owner-scoping, and cursor pagination
all exercise the actual SQL the route emits.
"""

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


async def _seed_conversation(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    user_text: str = "Hello there",
    assistant_text: str | None = "Hi! How can I help?",
    last_message_at: datetime | None = None,
) -> uuid.UUID:
    """Insert a conversation + its messages, then optionally pin
    ``last_message_at`` so tests can assert ordering deterministically.

    The repository updates ``last_message_at`` automatically on each
    message append; tests that need a specific recency order override it
    with a direct UPDATE so ordering doesn't depend on row-creation race.

    In production each ``_append_message`` call runs in its own session,
    so messages get distinct ``created_at`` values via separate transaction
    timestamps. The integration fixtures share one session per test (so
    rollback can clean up), which collapses ``now()`` to a single value
    within the test — we manually advance ``messages.created_at`` so the
    assistant message strictly trails the user one and the "last message"
    preview query is deterministic.
    """
    conv_id = uuid.uuid4()
    await ConversationRepository.create_conversation(
        db, conversation_id=conv_id, user_id=user_id
    )
    user_msg = await ConversationRepository.append_user_message(
        db,
        conversation_id=conv_id,
        content_blocks=[{"type": "text", "text": user_text}],
    )
    if assistant_text is not None:
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
    if last_message_at is not None:
        await db.execute(
            text(
                "UPDATE conversations SET last_message_at = :ts "
                "WHERE id = :id"
            ),
            {"ts": last_message_at, "id": conv_id},
        )
    await db.flush()
    return conv_id


def _decode_cursor(cursor: str) -> dict:
    raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
    return json.loads(raw)


# ---------- happy path ----------


class TestList:
    async def test_returns_user_conversations_ordered_by_recency(
        self,
        authenticated_db_client: AsyncClient,
        db_session: AsyncSession,
        test_user,
    ):
        base = datetime.now(timezone.utc) - timedelta(minutes=10)
        oldest = await _seed_conversation(
            db_session,
            user_id=test_user,
            user_text="What is AAPL?",
            last_message_at=base,
        )
        middle = await _seed_conversation(
            db_session,
            user_id=test_user,
            user_text="And TSLA?",
            last_message_at=base + timedelta(minutes=2),
        )
        newest = await _seed_conversation(
            db_session,
            user_id=test_user,
            user_text="Help me balance my portfolio please",
            last_message_at=base + timedelta(minutes=5),
        )

        response = await authenticated_db_client.get("/v1/conversations")

        assert response.status_code == 200, response.text
        body = response.json()
        ids = [item["id"] for item in body["items"]]
        assert ids == [str(newest), str(middle), str(oldest)]

    async def test_title_derived_from_first_user_message(
        self,
        authenticated_db_client: AsyncClient,
        db_session: AsyncSession,
        test_user,
    ):
        await _seed_conversation(
            db_session,
            user_id=test_user,
            user_text="Help me understand option pricing in plain English",
        )

        response = await authenticated_db_client.get("/v1/conversations")
        body = response.json()

        assert response.status_code == 200, response.text
        assert len(body["items"]) == 1
        title = body["items"][0]["title"]
        # First user message → title; ~40 chars then ellipsis when truncated.
        assert title is not None
        assert title.startswith("Help me understand option pricing")
        assert len(title) <= 41  # 40 chars + the ellipsis char

    async def test_preview_uses_last_message_text(
        self,
        authenticated_db_client: AsyncClient,
        db_session: AsyncSession,
        test_user,
    ):
        await _seed_conversation(
            db_session,
            user_id=test_user,
            user_text="hi",
            assistant_text="Sure — based on your portfolio, you have ...",
        )

        response = await authenticated_db_client.get("/v1/conversations")
        body = response.json()

        item = body["items"][0]
        assert item["last_message_preview"] is not None
        assert item["last_message_preview"].startswith(
            "Sure — based on your portfolio"
        )

    async def test_title_is_frozen_after_first_user_message(
        self,
        authenticated_db_client: AsyncClient,
        db_session: AsyncSession,
        test_user,
    ):
        # Acceptance criterion: the title comes from the *first* user
        # message and must not be rewritten when the user follows up with
        # another turn on the same conversation.
        conv_id = uuid.uuid4()
        await ConversationRepository.create_conversation(
            db_session, conversation_id=conv_id, user_id=test_user
        )
        await ConversationRepository.append_user_message(
            db_session,
            conversation_id=conv_id,
            content_blocks=[{"type": "text", "text": "First question"}],
        )
        # Second user message would otherwise overwrite the title.
        await ConversationRepository.append_user_message(
            db_session,
            conversation_id=conv_id,
            content_blocks=[
                {"type": "text", "text": "Completely different topic"}
            ],
        )
        await db_session.flush()

        response = await authenticated_db_client.get("/v1/conversations")
        body = response.json()

        assert response.status_code == 200, response.text
        assert len(body["items"]) == 1
        assert body["items"][0]["title"] == "First question"

    async def test_excludes_conversations_without_messages(
        self,
        authenticated_db_client: AsyncClient,
        db_session: AsyncSession,
        test_user,
    ):
        # A conversation created via ensure_owned_conversation but with no
        # turn yet has ``last_message_at IS NULL`` and shouldn't appear in
        # the sidebar.
        await ConversationRepository.ensure_owned_conversation(
            db_session,
            conversation_id=uuid.uuid4(),
            user_id=test_user,
        )
        # And one with an actual turn does appear.
        await _seed_conversation(db_session, user_id=test_user)

        response = await authenticated_db_client.get("/v1/conversations")
        body = response.json()

        assert response.status_code == 200, response.text
        assert len(body["items"]) == 1


# ---------- owner scoping ----------


class TestOwnerScoping:
    async def test_does_not_leak_other_users_conversations(
        self,
        authenticated_db_client: AsyncClient,
        db_session: AsyncSession,
        test_user,
        make_extra_user,
    ):
        other_user = await make_extra_user()
        await _seed_conversation(db_session, user_id=other_user)
        own = await _seed_conversation(db_session, user_id=test_user)

        response = await authenticated_db_client.get("/v1/conversations")
        body = response.json()

        ids = [item["id"] for item in body["items"]]
        assert ids == [str(own)]


# ---------- pagination ----------


class TestPagination:
    async def test_cursor_walks_through_pages(
        self,
        authenticated_db_client: AsyncClient,
        db_session: AsyncSession,
        test_user,
    ):
        base = datetime.now(timezone.utc) - timedelta(hours=1)
        seeded_newest_first = []
        for i in range(5):
            cid = await _seed_conversation(
                db_session,
                user_id=test_user,
                user_text=f"message {i}",
                last_message_at=base + timedelta(minutes=i),
            )
            seeded_newest_first.append(cid)
        seeded_newest_first.reverse()  # by recency DESC

        # First page
        first = await authenticated_db_client.get(
            "/v1/conversations?limit=2"
        )
        body1 = first.json()
        assert first.status_code == 200, first.text
        assert [it["id"] for it in body1["items"]] == [
            str(seeded_newest_first[0]),
            str(seeded_newest_first[1]),
        ]
        assert body1["next_cursor"] is not None
        # Sanity-check the cursor encodes the last returned row's sort key.
        decoded = _decode_cursor(body1["next_cursor"])
        assert decoded["id"] == str(seeded_newest_first[1])

        # Second page
        second = await authenticated_db_client.get(
            f"/v1/conversations?limit=2&cursor={body1['next_cursor']}"
        )
        body2 = second.json()
        assert [it["id"] for it in body2["items"]] == [
            str(seeded_newest_first[2]),
            str(seeded_newest_first[3]),
        ]
        assert body2["next_cursor"] is not None

        # Final page (1 item, no more cursor)
        third = await authenticated_db_client.get(
            f"/v1/conversations?limit=2&cursor={body2['next_cursor']}"
        )
        body3 = third.json()
        assert [it["id"] for it in body3["items"]] == [
            str(seeded_newest_first[4])
        ]
        assert body3["next_cursor"] is None

    async def test_invalid_cursor_returns_422(
        self,
        authenticated_db_client: AsyncClient,
        db_session: AsyncSession,
        test_user,
    ):
        # Seed at least one row so the request isn't a noop.
        await _seed_conversation(db_session, user_id=test_user)

        response = await authenticated_db_client.get(
            "/v1/conversations?cursor=not-a-real-cursor"
        )
        assert response.status_code == 422
        assert response.json()["code"] == "INVALID_CURSOR"

    async def test_final_page_with_exactly_limit_rows_returns_no_cursor(
        self,
        authenticated_db_client: AsyncClient,
        db_session: AsyncSession,
        test_user,
    ):
        # When the page size matches the row count exactly, the lookahead
        # row never lands and ``next_cursor`` must be null. Easy to get
        # wrong on the boundary.
        base = datetime.now(timezone.utc) - timedelta(hours=1)
        for i in range(2):
            await _seed_conversation(
                db_session,
                user_id=test_user,
                user_text=f"msg {i}",
                last_message_at=base + timedelta(minutes=i),
            )

        response = await authenticated_db_client.get(
            "/v1/conversations?limit=2"
        )
        body = response.json()
        assert response.status_code == 200, response.text
        assert len(body["items"]) == 2
        assert body["next_cursor"] is None

    async def test_empty_list_returns_no_cursor(
        self,
        authenticated_db_client: AsyncClient,
    ):
        response = await authenticated_db_client.get("/v1/conversations")
        body = response.json()
        assert response.status_code == 200, response.text
        assert body["items"] == []
        assert body["next_cursor"] is None


# ---------- auth ----------


class TestAuth:
    async def test_requires_authentication(
        self, client: AsyncClient
    ):
        # `client` is the unauthenticated fixture — no auth override applied.
        response = await client.get("/v1/conversations")
        assert response.status_code == 401
