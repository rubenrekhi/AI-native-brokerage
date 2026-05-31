"""Integration tests for digest_snapshots and DigestRepository.

Covers the unique-constraint-backed upsert idempotency, the date lookup,
and the one-way idempotent dismissal stamp.
"""

import uuid
from datetime import date, datetime, timezone

import pytest

from app.models.digest import DigestSnapshot
from app.repositories.digest import DigestRepository
from tests.integration.conftest import _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync, reason="Local Postgres not running"
)


def _snapshot(user_id, day, *, cards=None, generated_at=None) -> DigestSnapshot:
    return DigestSnapshot(
        user_id=user_id,
        ny_local_date=day,
        cards=cards if cards is not None else [],
        generated_at=generated_at or datetime.now(timezone.utc),
    )


async def test_upsert_inserts_new_snapshot(db_session, test_user):
    today = date(2026, 5, 31)
    persisted = await DigestRepository.upsert(
        db_session, _snapshot(test_user, today, cards=[])
    )

    assert persisted.id is not None
    assert persisted.user_id == test_user
    assert persisted.ny_local_date == today
    assert persisted.cards == []
    assert persisted.dismissed_at is None
    assert persisted.created_at is not None


async def test_upsert_is_idempotent_on_user_and_date(db_session, test_user):
    today = date(2026, 5, 31)
    first = await DigestRepository.upsert(
        db_session, _snapshot(test_user, today, cards=[])
    )
    second = await DigestRepository.upsert(
        db_session,
        _snapshot(test_user, today, cards=[{"kind": "news"}]),
    )

    # Same row (no duplicate), cards refreshed in place.
    assert second.id == first.id
    assert second.cards == [{"kind": "news"}]


async def test_upsert_preserves_dismissed_at_on_regeneration(
    db_session, test_user
):
    today = date(2026, 5, 31)
    snap = await DigestRepository.upsert(
        db_session, _snapshot(test_user, today)
    )
    await DigestRepository.mark_dismissed(db_session, snap.id)

    regenerated = await DigestRepository.upsert(
        db_session, _snapshot(test_user, today, cards=[{"kind": "news"}])
    )

    # Regenerating the same day must not resurrect a dismissed digest.
    assert regenerated.id == snap.id
    assert regenerated.dismissed_at is not None


async def test_get_by_user_and_date_returns_match(db_session, test_user):
    today = date(2026, 5, 31)
    await DigestRepository.upsert(db_session, _snapshot(test_user, today))

    found = await DigestRepository.get_by_user_and_date(
        db_session, test_user, today
    )
    assert found is not None
    assert found.ny_local_date == today


async def test_get_by_user_and_date_returns_none_for_other_day(
    db_session, test_user
):
    await DigestRepository.upsert(
        db_session, _snapshot(test_user, date(2026, 5, 31))
    )
    found = await DigestRepository.get_by_user_and_date(
        db_session, test_user, date(2026, 5, 30)
    )
    assert found is None


async def test_mark_dismissed_stamps_and_is_idempotent(db_session, test_user):
    snap = await DigestRepository.upsert(
        db_session, _snapshot(test_user, date(2026, 5, 31))
    )
    assert snap.dismissed_at is None

    first = await DigestRepository.mark_dismissed(db_session, snap.id)
    assert first is not None and first.dismissed_at is not None
    original_ts = first.dismissed_at

    second = await DigestRepository.mark_dismissed(db_session, snap.id)
    # Re-dismissing keeps the original timestamp.
    assert second is not None and second.dismissed_at == original_ts


async def test_mark_dismissed_returns_none_for_unknown_id(
    db_session, test_user
):
    assert await DigestRepository.mark_dismissed(
        db_session, uuid.uuid4()
    ) is None


async def test_unique_constraint_blocks_duplicate_user_date(
    db_session, test_user
):
    from sqlalchemy.exc import IntegrityError

    today = date(2026, 5, 31)
    db_session.add(_snapshot(test_user, today))
    await db_session.flush()
    db_session.add(_snapshot(test_user, today))
    with pytest.raises(IntegrityError):
        await db_session.flush()
