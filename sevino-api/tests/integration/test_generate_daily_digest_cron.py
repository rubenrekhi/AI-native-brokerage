"""Integration tests for the daily digest generation cron."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import func, select, text

from app.models.digest import DigestSnapshot
from app.repositories.digest import DigestRepository
from app.services.digest.context import ET
from app.tasks.generate_daily_digest import generate_daily_digest
from tests.integration.conftest import _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync, reason="Local Postgres not running"
)


def _patch_async_session(monkeypatch, session) -> None:
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(session, "commit", AsyncMock())
    monkeypatch.setattr(
        "app.tasks.generate_daily_digest.async_session", lambda: cm
    )


async def _set_last_active(db_session, user_id: uuid.UUID, value: datetime) -> None:
    await db_session.execute(
        text("UPDATE user_profiles SET last_active_at = :value WHERE id = :id"),
        {"value": value, "id": user_id},
    )
    await db_session.flush()


async def test_cron_generates_for_active_users_and_is_idempotent(
    db_session, test_user, monkeypatch
):
    now = datetime.now(timezone.utc)
    await _set_last_active(db_session, test_user, now)
    _patch_async_session(monkeypatch, db_session)
    calls: list[uuid.UUID] = []

    class FakeDigestService:
        def __init__(self, db, **kwargs):
            self._db = db

        async def generate_for_user(self, user_id):
            calls.append(user_id)
            return await DigestRepository.upsert(
                self._db,
                DigestSnapshot(
                    user_id=user_id,
                    ny_local_date=datetime.now(timezone.utc)
                    .astimezone(ET)
                    .date(),
                    cards=[],
                    generated_at=datetime.now(timezone.utc),
                ),
            )

    monkeypatch.setattr(
        "app.tasks.generate_daily_digest.DigestService", FakeDigestService
    )

    first = await generate_daily_digest({"alpaca": object()})
    second = await generate_daily_digest({"alpaca": object()})

    count = (
        await db_session.execute(select(func.count()).select_from(DigestSnapshot))
    ).scalar_one()
    assert first["generated_count"] == 1
    assert second["generated_count"] == 0
    assert count == 1
    assert calls == [test_user]


async def test_cron_skips_users_not_active_in_last_7_days(
    db_session, test_user, monkeypatch
):
    await _set_last_active(
        db_session, test_user, datetime.now(timezone.utc) - timedelta(days=8)
    )
    _patch_async_session(monkeypatch, db_session)

    class FakeDigestService:
        async def generate_for_user(self, user_id):
            raise AssertionError("inactive user should not be generated")

    monkeypatch.setattr(
        "app.tasks.generate_daily_digest.DigestService", FakeDigestService
    )

    result = await generate_daily_digest({"alpaca": object()})

    assert result["generated_count"] == 0
