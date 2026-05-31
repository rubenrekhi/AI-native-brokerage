"""Integration tests for digest snapshot retention."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.digest import DigestSnapshot
from app.repositories.digest import DigestRepository
from app.services.digest.context import ET
from app.tasks.sweep_digest_snapshots import sweep_digest_snapshots
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
        "app.tasks.sweep_digest_snapshots.async_session", lambda: cm
    )


async def test_sweep_deletes_8_day_old_snapshot_and_keeps_6_day_old(
    db_session, test_user, make_extra_user, monkeypatch
):
    today = datetime.now(timezone.utc).astimezone(ET).date()
    other_user = await make_extra_user()
    old = await DigestRepository.upsert(
        db_session,
        DigestSnapshot(
            user_id=test_user,
            ny_local_date=today - timedelta(days=8),
            cards=[],
            generated_at=datetime.now(timezone.utc) - timedelta(days=8),
        ),
    )
    recent = await DigestRepository.upsert(
        db_session,
        DigestSnapshot(
            user_id=other_user,
            ny_local_date=today - timedelta(days=6),
            cards=[],
            generated_at=datetime.now(timezone.utc) - timedelta(days=6),
        ),
    )
    _patch_async_session(monkeypatch, db_session)

    result = await sweep_digest_snapshots({})

    assert result == {"status": "ok", "deleted_count": 1}
    assert await db_session.get(DigestSnapshot, old.id) is None
    assert await db_session.get(DigestSnapshot, recent.id) is not None
