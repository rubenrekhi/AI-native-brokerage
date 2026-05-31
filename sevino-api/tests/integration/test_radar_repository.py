"""Integration tests for the radar_items table and RadarItemRepository.

Covers the unique constraint and the read-side repository methods
(`list_for_user`, `list_all_symbols`, `get_by_id_for_user`) including sort
order and the read-time expiry filter.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.radar_item import RadarItem
from app.repositories.radar_item import RadarItemRepository
from tests.integration.conftest import _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync, reason="Local Postgres not running"
)


async def test_unique_constraint_blocks_duplicate_user_symbol(
    db_session, test_user
):
    db_session.add(RadarItem(user_id=test_user, symbol="AAPL"))
    await db_session.flush()

    db_session.add(RadarItem(user_id=test_user, symbol="AAPL"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_list_for_user_returns_empty_for_user_with_no_items(
    db_session, test_user
):
    assert await RadarItemRepository.list_for_user(db_session, test_user) == []


async def test_list_for_user_orders_favorited_first_then_relevance_then_recency(
    db_session, test_user
):
    now = datetime.now(timezone.utc)
    # (symbol, is_favorited, relevance_score, days_ago).
    # Favorited rows tie on null relevance, so created_at breaks the tie
    # (FAV_NEW > FAV_OLD). Unfavorited rows sort by relevance desc with
    # nulls last (HIGH > MID > NO).
    for symbol, fav, rel, days_ago in [
        ("FAV_OLD", True, None, 5),
        ("FAV_NEW", True, None, 1),
        ("HIGH_REL", False, 0.9, 0),
        ("MID_REL", False, 0.5, 0),
        ("NO_REL", False, None, 0),
    ]:
        db_session.add(RadarItem(
            user_id=test_user, symbol=symbol,
            is_favorited=fav, relevance_score=rel,
            created_at=now - timedelta(days=days_ago),
        ))
    await db_session.flush()

    rows = await RadarItemRepository.list_for_user(db_session, test_user)
    assert [r.symbol for r in rows] == [
        "FAV_NEW", "FAV_OLD", "HIGH_REL", "MID_REL", "NO_REL",
    ]


async def test_list_for_user_filters_out_rows_past_their_expires_at(
    db_session, test_user
):
    now = datetime.now(timezone.utc)
    for symbol, expires in [
        ("NO_EXPIRY", None),
        ("NOT_YET_EXPIRED", now + timedelta(days=1)),
        ("EXPIRED", now - timedelta(days=1)),
    ]:
        db_session.add(RadarItem(
            user_id=test_user, symbol=symbol,
            is_favorited=False, expires_at=expires,
        ))
    await db_session.flush()

    visible = {
        r.symbol
        for r in await RadarItemRepository.list_for_user(db_session, test_user)
    }
    assert visible == {"NO_EXPIRY", "NOT_YET_EXPIRED"}


async def test_list_for_user_does_not_return_other_users_items(
    db_session, test_user, make_extra_user
):
    other_user = await make_extra_user()
    db_session.add(RadarItem(user_id=other_user, symbol="THEIRS"))
    db_session.add(RadarItem(user_id=test_user, symbol="MINE"))
    await db_session.flush()

    rows = await RadarItemRepository.list_for_user(db_session, test_user)
    assert [r.symbol for r in rows] == ["MINE"]


async def test_list_all_symbols_includes_expired_rows_and_scopes_to_user(
    db_session, test_user, make_extra_user
):
    other_user = await make_extra_user()
    now = datetime.now(timezone.utc)
    db_session.add(RadarItem(
        user_id=test_user, symbol="EXPIRED",
        source="ai_generated", is_favorited=False,
        expires_at=now - timedelta(days=1),
    ))
    db_session.add(RadarItem(user_id=test_user, symbol="LIVE", expires_at=None))
    db_session.add(RadarItem(user_id=other_user, symbol="THEIRS"))
    await db_session.flush()

    # list_for_user hides EXPIRED; list_all_symbols must still surface it so a
    # new batch never re-picks a symbol that still holds a row.
    visible = {
        r.symbol
        for r in await RadarItemRepository.list_for_user(db_session, test_user)
    }
    assert "EXPIRED" not in visible

    assert await RadarItemRepository.list_all_symbols(
        db_session, test_user
    ) == {"EXPIRED", "LIVE"}


async def test_get_by_id_for_user_returns_row_when_owned(
    db_session, test_user
):
    item = RadarItem(user_id=test_user, symbol="AAPL")
    db_session.add(item)
    await db_session.flush()

    result = await RadarItemRepository.get_by_id_for_user(
        db_session, item.id, test_user
    )
    assert result is not None
    assert result.id == item.id


async def test_get_by_id_for_user_returns_none_when_owned_by_another_user(
    db_session, test_user, make_extra_user
):
    other_user = await make_extra_user()
    item = RadarItem(user_id=other_user, symbol="AAPL")
    db_session.add(item)
    await db_session.flush()

    result = await RadarItemRepository.get_by_id_for_user(
        db_session, item.id, test_user
    )
    assert result is None


async def test_get_by_id_for_user_returns_none_for_unknown_id(
    db_session, test_user
):
    result = await RadarItemRepository.get_by_id_for_user(
        db_session, uuid.uuid4(), test_user
    )
    assert result is None


async def test_get_by_symbol_for_user_returns_row_when_owned(
    db_session, test_user
):
    item = RadarItem(user_id=test_user, symbol="AAPL")
    db_session.add(item)
    await db_session.flush()

    result = await RadarItemRepository.get_by_symbol_for_user(
        db_session, test_user, "AAPL"
    )
    assert result is not None
    assert result.id == item.id


async def test_get_by_symbol_for_user_returns_none_for_other_users_symbol(
    db_session, test_user, make_extra_user
):
    other_user = await make_extra_user()
    db_session.add(RadarItem(user_id=other_user, symbol="AAPL"))
    await db_session.flush()

    result = await RadarItemRepository.get_by_symbol_for_user(
        db_session, test_user, "AAPL"
    )
    assert result is None


async def test_get_by_symbol_for_user_returns_none_for_unknown_symbol(
    db_session, test_user
):
    result = await RadarItemRepository.get_by_symbol_for_user(
        db_session, test_user, "ZZZZ"
    )
    assert result is None


async def test_create_user_added_sets_favorited_no_expiry_user_source(
    db_session, test_user
):
    item = await RadarItemRepository.create_user_added(
        db_session,
        user_id=test_user,
        symbol="AAPL",
        company_name="Apple Inc.",
    )
    assert item.user_id == test_user
    assert item.symbol == "AAPL"
    assert item.company_name == "Apple Inc."
    assert item.source == "user_added"
    assert item.is_favorited is True
    assert item.expires_at is None


async def test_create_ai_item_sets_unfavorited_7d_expiry_ai_source(
    db_session, test_user
):
    before = datetime.now(timezone.utc)
    item = await RadarItemRepository.create_ai_item(
        db_session,
        user_id=test_user,
        symbol="NVDA",
        company_name="NVIDIA Corporation",
        context_blurb="AI chip giant with strong data center growth.",
        relevance_score=0.92,
    )
    after = datetime.now(timezone.utc)
    assert item.symbol == "NVDA"
    assert item.company_name == "NVIDIA Corporation"
    assert item.context_blurb == "AI chip giant with strong data center growth."
    assert item.relevance_score == 0.92
    assert item.source == "ai_generated"
    assert item.is_favorited is False
    assert item.expires_at is not None
    # 7-day TTL is set from Python's clock, so the row should land in
    # [before + 7d, after + 7d].
    assert before + timedelta(days=7) <= item.expires_at <= after + timedelta(days=7)


async def test_create_ai_item_accepts_null_blurb_and_score(
    db_session, test_user
):
    item = await RadarItemRepository.create_ai_item(
        db_session,
        user_id=test_user,
        symbol="TSLA",
        company_name="Tesla, Inc.",
    )
    assert item.context_blurb is None
    assert item.relevance_score is None


async def test_create_user_added_rejects_duplicate_for_same_user(
    db_session, test_user
):
    await RadarItemRepository.create_user_added(
        db_session, user_id=test_user, symbol="AAPL", company_name="Apple Inc.",
    )
    with pytest.raises(IntegrityError):
        await RadarItemRepository.create_user_added(
            db_session, user_id=test_user, symbol="AAPL", company_name="Apple Inc.",
        )


async def test_create_user_added_allows_same_symbol_for_different_user(
    db_session, test_user, make_extra_user
):
    other_user = await make_extra_user()
    await RadarItemRepository.create_user_added(
        db_session, user_id=test_user, symbol="AAPL", company_name="Apple Inc.",
    )
    item = await RadarItemRepository.create_user_added(
        db_session, user_id=other_user, symbol="AAPL", company_name="Apple Inc.",
    )
    assert item.user_id == other_user


async def test_delete_removes_the_row(db_session, test_user):
    item = await RadarItemRepository.create_user_added(
        db_session, user_id=test_user, symbol="AAPL", company_name="Apple Inc.",
    )
    item_id = item.id

    await RadarItemRepository.delete(db_session, item)

    assert await RadarItemRepository.get_by_id_for_user(
        db_session, item_id, test_user
    ) is None


async def test_delete_expired_ai_items_only_deletes_expired_non_favorited_ai_rows(
    db_session, test_user
):
    now = datetime.now(timezone.utc)
    past = now - timedelta(days=1)
    future = now + timedelta(days=1)
    # (symbol, source, is_favorited, expires_at). Only EXPIRED_AI should
    # match the sweep predicate. USER_ADDED_DRIFT exercises the
    # defense-in-depth source filter — the row is a state that the write
    # path shouldn't produce, but the sweep must not touch user_added.
    rows = [
        ("EXPIRED_AI", "ai_generated", False, past),
        ("FRESH_AI", "ai_generated", False, future),
        ("FAV_AI", "ai_generated", True, None),
        ("USER_ADDED", "user_added", True, None),
        ("USER_ADDED_DRIFT", "user_added", False, past),
    ]
    for symbol, source, fav, expires in rows:
        db_session.add(RadarItem(
            user_id=test_user, symbol=symbol,
            source=source, is_favorited=fav, expires_at=expires,
        ))
    await db_session.flush()

    deleted_count = await RadarItemRepository.delete_expired_ai_items(db_session)

    # `delete_expired_ai_items` is global (sweep cron), so both its count and
    # an unscoped read can include committed rows from other users/sessions in
    # the shared local DB. Assert against this test's own rows: at least our
    # expired row was swept, and exactly the right rows survive for this user.
    assert deleted_count >= 1
    result = await db_session.execute(
        select(RadarItem.symbol).where(RadarItem.user_id == test_user)
    )
    remaining = set(result.scalars().all())
    assert remaining == {"FRESH_AI", "FAV_AI", "USER_ADDED", "USER_ADDED_DRIFT"}


async def test_delete_expired_ai_items_leaves_unexpired_ai_rows(
    db_session, test_user
):
    item = await RadarItemRepository.create_ai_item(
        db_session, user_id=test_user, symbol="NVDA", company_name="NVIDIA Corp.",
    )

    await RadarItemRepository.delete_expired_ai_items(db_session)

    # The user's fresh AI row (default 7d expiry) doesn't match the sweep, so
    # it survives. Assert survival (scoped) rather than a global delete count
    # of 0 — committed rows from other sessions in the shared local DB, or a
    # leaked AI row that has since aged past its expiry, would break `== 0`.
    assert await RadarItemRepository.get_by_id_for_user(
        db_session, item.id, test_user
    ) is not None


async def test_create_ai_item_accepts_bucket_and_expires_at_override(
    db_session, test_user
):
    anchor = datetime.now(timezone.utc) + timedelta(days=7)
    item = await RadarItemRepository.create_ai_item(
        db_session,
        user_id=test_user,
        symbol="META",
        company_name="Meta Platforms",
        bucket="diversification",
        expires_at=anchor,
    )

    assert item.bucket == "diversification"
    # `expires_at` flows straight through; the default 7d-from-now path is
    # only taken when the caller leaves it unset.
    assert item.expires_at == anchor


async def test_delete_unfavorited_ai_drops_only_unfavorited_ai_rows_for_user(
    db_session, test_user, make_extra_user
):
    other_user = await make_extra_user()
    rows = [
        ("KEEP_FAV_AI", test_user, "ai_generated", True),
        ("KEEP_USER_ADDED", test_user, "user_added", False),
        ("KEEP_USER_ADDED_FAV", test_user, "user_added", True),
        ("DROP_AI_1", test_user, "ai_generated", False),
        ("DROP_AI_2", test_user, "ai_generated", False),
        ("KEEP_OTHER_USER_AI", other_user, "ai_generated", False),
    ]
    for symbol, uid, source, fav in rows:
        db_session.add(RadarItem(
            user_id=uid, symbol=symbol,
            source=source, is_favorited=fav,
        ))
    await db_session.flush()

    deleted = await RadarItemRepository.delete_unfavorited_ai(
        db_session, test_user
    )
    assert deleted == 2

    # Scope to the two users this test created — an unscoped read would pick
    # up committed rows from other users/sessions sharing the local DB.
    result = await db_session.execute(
        select(RadarItem.symbol).where(
            RadarItem.user_id.in_([test_user, other_user])
        )
    )
    remaining = set(result.scalars().all())
    assert remaining == {
        "KEEP_FAV_AI",
        "KEEP_USER_ADDED",
        "KEEP_USER_ADDED_FAV",
        "KEEP_OTHER_USER_AI",
    }


async def test_delete_unfavorited_ai_returns_zero_when_no_match(
    db_session, test_user
):
    db_session.add(RadarItem(
        user_id=test_user, symbol="FAV_AI",
        source="ai_generated", is_favorited=True,
    ))
    db_session.add(RadarItem(
        user_id=test_user, symbol="MINE",
        source="user_added", is_favorited=True,
    ))
    await db_session.flush()

    assert await RadarItemRepository.delete_unfavorited_ai(
        db_session, test_user
    ) == 0
