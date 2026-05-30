"""Integration tests for GET /v1/shortcuts.

End-to-end: auth -> service (real Postgres via `authenticated_db_client`)
-> 30s cache -> response. An in-memory fake Redis is injected through
`dependency_overrides` so the cache-hit path runs without a live Redis.
Auto-skipped when Postgres on :54322 is down.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import text

from app.dependencies import get_redis
from app.main import app
from app.repositories.user_profile import UserProfileRepository
from tests.integration.conftest import TEST_USER_ID, _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync, reason="Local Postgres not available on :54322"
)


class _FakeRedis:
    """In-memory stand-in supporting the `get`/`setex` cache_get_or_set uses."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._store[key] = value


@pytest.fixture
def fake_redis() -> _FakeRedis:
    return _FakeRedis()


@pytest.fixture(autouse=True)
def _override_redis(fake_redis):
    app.dependency_overrides[get_redis] = lambda: fake_redis
    yield
    app.dependency_overrides.pop(get_redis, None)


async def _make_established_user(db_session, user_id) -> None:
    await db_session.execute(
        text(
            "UPDATE user_profiles SET created_at = now() - interval '60 days' "
            "WHERE id = :id"
        ),
        {"id": user_id},
    )
    for _ in range(10):
        await db_session.execute(
            text(
                "INSERT INTO conversations (id, user_id, created_at, updated_at) "
                "VALUES (gen_random_uuid(), :uid, now(), now())"
            ),
            {"uid": user_id},
        )
    await db_session.flush()


async def test_fresh_user_gets_first_time_in_top_slots(
    authenticated_db_client, test_user
):
    response = await authenticated_db_client.get("/v1/shortcuts")

    assert response.status_code == 200
    items = response.json()["items"]
    assert 0 < len(items) <= 13
    assert sum(1 for i in items if i["category"] == "first_time") == 5
    assert all(i["category"] == "first_time" for i in items[:5])
    assert {i["category"] for i in items} <= {"first_time", "quiet_state"}
    ids = [i["id"] for i in items]
    assert len(ids) == len(set(ids))


async def test_established_user_gets_only_quiet_state(
    authenticated_db_client, db_session, test_user
):
    await _make_established_user(db_session, str(test_user))

    response = await authenticated_db_client.get("/v1/shortcuts")

    assert response.status_code == 200
    items = response.json()["items"]
    assert items
    assert all(i["category"] == "quiet_state" for i in items)


async def test_soft_deleted_conversations_do_not_count_toward_gate(
    authenticated_db_client, db_session, test_user
):
    # Old account, but its conversations are all soft-deleted -> the user
    # hasn't really engaged, so first_time must still fire.
    await db_session.execute(
        text(
            "UPDATE user_profiles SET created_at = now() - interval '60 days' "
            "WHERE id = :id"
        ),
        {"id": str(test_user)},
    )
    for _ in range(5):
        await db_session.execute(
            text(
                "INSERT INTO conversations "
                "(id, user_id, is_deleted, created_at, updated_at) "
                "VALUES (gen_random_uuid(), :uid, true, now(), now())"
            ),
            {"uid": str(test_user)},
        )
    await db_session.flush()

    response = await authenticated_db_client.get("/v1/shortcuts")

    assert response.status_code == 200
    items = response.json()["items"]
    assert any(i["category"] == "first_time" for i in items)


async def test_second_call_within_ttl_served_from_cache(
    authenticated_db_client, test_user, fake_redis
):
    with patch.object(
        UserProfileRepository,
        "get_by_id",
        wraps=UserProfileRepository.get_by_id,
    ) as spy:
        first = await authenticated_db_client.get("/v1/shortcuts")
        second = await authenticated_db_client.get("/v1/shortcuts")

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert spy.call_count == 1
    assert any(
        key.startswith(f"shortcuts:{TEST_USER_ID}:")
        for key in fake_redis._store
    )


async def test_unauthenticated_returns_401(client):
    response = await client.get("/v1/shortcuts")
    assert response.status_code == 401
