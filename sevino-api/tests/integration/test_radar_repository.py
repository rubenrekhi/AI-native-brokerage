"""Integration tests for the radar_items table and RadarItemRepository.

Covers the unique constraint and the read-side repository methods
(`list_for_user`, `get_by_id_for_user`) including sort order and the
read-time expiry filter.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
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
