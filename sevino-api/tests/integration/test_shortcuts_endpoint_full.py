"""Integration tests for the full shortcut mix once all rules are wired.

Covers the realistic, multi-category feed an established user sees (radar
+ capability + quiet-state) end-to-end through the HTTP endpoint, plus the
quiet-state-heavy night response via the service with a pinned clock.
Alpaca/market-data singletons aren't wired under the test transport, so the
portfolio/market categories stay silent — the mix here is the
broker-independent slice of the ladder. Auto-skipped when Postgres is down.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_redis
from app.main import app
from app.services.shortcuts.service import ShortcutsService
from app.services.shortcuts.time_buckets import TimeBucket, current_bucket
from tests.integration.conftest import _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync, reason="Local Postgres not available on :54322"
)

# 02:00 ET — squarely inside the night bucket regardless of DST.
_NIGHT_UTC = datetime(2026, 5, 30, 6, 0, tzinfo=timezone.utc)


class _FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._store[key] = value


@pytest.fixture(autouse=True)
def _override_redis():
    app.dependency_overrides[get_redis] = lambda: _FakeRedis()
    yield
    app.dependency_overrides.pop(get_redis, None)


async def _establish_user(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(
        text(
            "UPDATE user_profiles SET created_at = now() - interval '60 days' "
            "WHERE id = :id"
        ),
        {"id": user_id},
    )
    for _ in range(10):
        await db.execute(
            text(
                "INSERT INTO conversations (id, user_id, created_at, updated_at) "
                "VALUES (gen_random_uuid(), :uid, now(), now())"
            ),
            {"uid": user_id},
        )
    await db.flush()


async def _insert_radar_item(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(
        text(
            """
            INSERT INTO radar_items
                (id, user_id, symbol, source, is_favorited, created_at, updated_at)
            VALUES (gen_random_uuid(), :uid, 'AAPL', 'ai_generated', false,
                    now(), now())
            """
        ),
        {"uid": user_id},
    )
    await db.flush()


async def test_established_user_with_radar_sees_realistic_mix(
    authenticated_db_client, db_session, test_user
):
    await _establish_user(db_session, str(test_user))
    await _insert_radar_item(db_session, str(test_user))

    response = await authenticated_db_client.get("/v1/shortcuts")

    assert response.status_code == 200
    items = response.json()["items"]
    assert 0 < len(items) <= 13
    categories = {i["category"] for i in items}
    assert "first_time" not in categories
    assert "radar_update" in categories
    assert "capability" in categories
    assert "quiet_state" in categories
    assert any(i["text"] == "What's on Radar today?" for i in items)
    ids = [i["id"] for i in items]
    assert len(ids) == len(set(ids))


async def test_night_bucket_response_is_quiet_state_heavy(
    db_session, test_user
):
    await _establish_user(db_session, str(test_user))

    assert current_bucket(_NIGHT_UTC) == TimeBucket.NIGHT
    service = ShortcutsService(db_session, alpaca=None, market_data=None)
    response = await service.list_for_user(test_user, now=_NIGHT_UTC)

    items = response.items
    assert items
    categories = [i.category for i in items]
    assert set(categories) <= {"capability", "quiet_state"}
    quiet = sum(1 for c in categories if c == "quiet_state")
    assert quiet > sum(1 for c in categories if c == "capability")
