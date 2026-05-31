"""Integration tests for the `radar_update` rule against real radar rows.

Exercises the inline ``radar_items`` filter (unstarred + unexpired +
AI-generated) end-to-end against local Postgres — the WHERE clause a
mocked count can't verify. Auto-skipped when Postgres on :54322 is down.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.shortcuts.context import ShortcutContext
from app.services.shortcuts.rules import radar_update
from app.services.shortcuts.time_buckets import TimeBucket
from tests.integration.conftest import _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync, reason="Local Postgres not available on :54322"
)

_PAST = datetime(2000, 1, 1, tzinfo=timezone.utc)
_FUTURE = datetime(2999, 1, 1, tzinfo=timezone.utc)


def _ctx(user_id: uuid.UUID) -> ShortcutContext:
    return ShortcutContext(
        user_id=user_id,
        bucket=TimeBucket.MARKET_HOURS,
        day=date(2026, 5, 30),
        account_age_days=100,
        conversation_count=100,
    )


async def _insert_radar_item(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    symbol: str,
    source: str = "ai_generated",
    is_favorited: bool = False,
    expires_at: datetime | None = None,
) -> None:
    await db.execute(
        text(
            """
            INSERT INTO radar_items
                (id, user_id, symbol, source, is_favorited, expires_at,
                 created_at, updated_at)
            VALUES
                (gen_random_uuid(), :uid, :symbol, :source, :fav,
                 :expires, now(), now())
            """
        ),
        {
            "uid": user_id,
            "symbol": symbol,
            "source": source,
            "fav": is_favorited,
            "expires": expires_at,
        },
    )
    await db.flush()


async def test_fires_with_unstarred_ai_item(db_session, test_user):
    await _insert_radar_item(db_session, test_user, symbol="AAPL")
    out = await radar_update.evaluate(_ctx(test_user), db_session)
    assert len(out) == 1
    assert out[0].text == "What's on Radar today?"
    assert out[0].category == "radar_update"


async def test_silent_when_only_favorited(db_session, test_user):
    await _insert_radar_item(
        db_session, test_user, symbol="AAPL", is_favorited=True
    )
    out = await radar_update.evaluate(_ctx(test_user), db_session)
    assert out == []


async def test_silent_when_only_user_added(db_session, test_user):
    await _insert_radar_item(
        db_session, test_user, symbol="AAPL", source="user_added"
    )
    out = await radar_update.evaluate(_ctx(test_user), db_session)
    assert out == []


async def test_silent_when_expired(db_session, test_user):
    await _insert_radar_item(
        db_session, test_user, symbol="AAPL", expires_at=_PAST
    )
    out = await radar_update.evaluate(_ctx(test_user), db_session)
    assert out == []


async def test_null_expiry_counts_as_live(db_session, test_user):
    await _insert_radar_item(
        db_session, test_user, symbol="AAPL", expires_at=None
    )
    out = await radar_update.evaluate(_ctx(test_user), db_session)
    assert len(out) == 1


async def test_fires_when_live_item_sits_alongside_expired(db_session, test_user):
    await _insert_radar_item(
        db_session, test_user, symbol="MSFT", expires_at=_PAST
    )
    await _insert_radar_item(
        db_session, test_user, symbol="NVDA", expires_at=_FUTURE
    )
    out = await radar_update.evaluate(_ctx(test_user), db_session)
    assert len(out) == 1


async def test_isolated_per_user(db_session, test_user, make_extra_user):
    other = await make_extra_user()
    await _insert_radar_item(db_session, other, symbol="AAPL")
    out = await radar_update.evaluate(_ctx(test_user), db_session)
    assert out == []
