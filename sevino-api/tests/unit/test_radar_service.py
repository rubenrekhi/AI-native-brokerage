"""Unit tests for RadarService."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.exceptions import ConflictError, NotFoundError
from app.models.asset import Asset
from app.models.radar_item import RadarItem
from app.schemas.radar import RadarItemRead
from app.services.radar import RadarService


def _patch_repos(monkeypatch, *, asset, create_raises=None):
    """Patch the two repo calls add_user_item makes.

    Returns a dict the test can inspect for the arguments the patched
    repos were called with (e.g. assert symbol was uppercased before
    asset lookup).
    """
    captured: dict = {}

    async def fake_get_by_symbol(db, symbol):
        captured["lookup_symbol"] = symbol
        return asset

    async def fake_create_user_added(db, **kwargs):
        captured.update(kwargs)
        if create_raises is not None:
            raise create_raises
        return RadarItem(
            id=uuid4(),
            user_id=kwargs["user_id"],
            symbol=kwargs["symbol"],
            company_name=kwargs["company_name"],
            source="user_added",
            is_favorited=True,
            expires_at=None,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    monkeypatch.setattr(
        "app.services.radar.AssetRepository.get_by_symbol", fake_get_by_symbol
    )
    monkeypatch.setattr(
        "app.services.radar.RadarItemRepository.create_user_added",
        fake_create_user_added,
    )
    return captured


async def test_list_for_user_returns_empty_when_repo_returns_no_rows(monkeypatch):
    async def fake_list_for_user(db, user_id):
        return []

    monkeypatch.setattr(
        "app.services.radar.RadarItemRepository.list_for_user",
        fake_list_for_user,
    )

    result = await RadarService(AsyncMock()).list_for_user(uuid4())
    assert result == []


async def test_list_for_user_converts_orm_rows_to_schemas_with_null_overlay(
    monkeypatch,
):
    user_id = uuid4()
    orm_row = RadarItem(
        id=uuid4(),
        user_id=user_id,
        symbol="AAPL",
        company_name="Apple Inc.",
        context_blurb=None,
        source="user_added",
        is_favorited=True,
        relevance_score=None,
        expires_at=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    async def fake_list_for_user(db, uid):
        assert uid == user_id
        return [orm_row]

    monkeypatch.setattr(
        "app.services.radar.RadarItemRepository.list_for_user",
        fake_list_for_user,
    )

    result = await RadarService(AsyncMock()).list_for_user(user_id)

    assert len(result) == 1
    assert isinstance(result[0], RadarItemRead)
    assert result[0].symbol == "AAPL"
    assert result[0].is_favorited is True
    # Overlay populated in T11; null for now.
    assert result[0].price is None
    assert result[0].change_abs is None
    assert result[0].change_pct is None


async def test_add_user_item_uppercases_symbol_before_asset_lookup(monkeypatch):
    captured = _patch_repos(
        monkeypatch,
        asset=Asset(symbol="AAPL", name="Apple Inc.", tradeable=True),
    )

    await RadarService(AsyncMock()).add_user_item(uuid4(), "aapl")

    assert captured["lookup_symbol"] == "AAPL"
    assert captured["symbol"] == "AAPL"


async def test_add_user_item_raises_symbol_not_tradeable_when_asset_missing(
    monkeypatch,
):
    _patch_repos(monkeypatch, asset=None)

    with pytest.raises(ConflictError) as exc_info:
        await RadarService(AsyncMock()).add_user_item(uuid4(), "ZZZZ")

    assert exc_info.value.code == "SYMBOL_NOT_TRADEABLE"
    assert exc_info.value.detail == {"symbol": "ZZZZ"}


async def test_add_user_item_translates_integrity_error_to_duplicate(monkeypatch):
    _patch_repos(
        monkeypatch,
        asset=Asset(symbol="AAPL", name="Apple Inc.", tradeable=True),
        create_raises=IntegrityError("stmt", {}, Exception("dup")),
    )

    with pytest.raises(ConflictError) as exc_info:
        await RadarService(AsyncMock()).add_user_item(uuid4(), "AAPL")

    assert exc_info.value.code == "RADAR_DUPLICATE_SYMBOL"
    assert exc_info.value.detail == {"symbol": "AAPL"}


async def test_add_user_item_persists_company_name_from_asset(monkeypatch):
    captured = _patch_repos(
        monkeypatch,
        asset=Asset(symbol="AAPL", name="Apple Inc.", tradeable=True),
    )

    await RadarService(AsyncMock()).add_user_item(uuid4(), "AAPL")

    assert captured["company_name"] == "Apple Inc."


async def test_remove_raises_not_found_when_item_unknown(monkeypatch):
    async def fake_get_by_id_for_user(db, item_id, user_id):
        return None

    monkeypatch.setattr(
        "app.services.radar.RadarItemRepository.get_by_id_for_user",
        fake_get_by_id_for_user,
    )

    with pytest.raises(NotFoundError):
        await RadarService(AsyncMock()).remove(uuid4(), uuid4())


def _make_radar_item(*, is_favorited: bool, source: str = "user_added") -> RadarItem:
    return RadarItem(
        id=uuid4(),
        user_id=uuid4(),
        symbol="AAPL",
        company_name="Apple Inc.",
        context_blurb=None,
        source=source,
        is_favorited=is_favorited,
        relevance_score=None,
        expires_at=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


async def test_toggle_favorite_flips_flag_and_writes_to_db(monkeypatch):
    item = _make_radar_item(is_favorited=False)

    async def fake_get_by_id_for_user(db, item_id, user_id):
        return item

    monkeypatch.setattr(
        "app.services.radar.RadarItemRepository.get_by_id_for_user",
        fake_get_by_id_for_user,
    )

    db = AsyncMock()
    result = await RadarService(db).toggle_favorite(uuid4(), uuid4(), True)

    assert result.is_favorited is True
    assert item.is_favorited is True
    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once_with(item)


async def test_toggle_favorite_no_op_when_state_already_matches(monkeypatch):
    item = _make_radar_item(is_favorited=True)

    async def fake_get_by_id_for_user(db, item_id, user_id):
        return item

    monkeypatch.setattr(
        "app.services.radar.RadarItemRepository.get_by_id_for_user",
        fake_get_by_id_for_user,
    )

    db = AsyncMock()
    result = await RadarService(db).toggle_favorite(uuid4(), uuid4(), True)

    assert result.is_favorited is True
    db.flush.assert_not_called()
    db.refresh.assert_not_called()


async def test_toggle_favorite_raises_not_found_when_item_unknown(monkeypatch):
    async def fake_get_by_id_for_user(db, item_id, user_id):
        return None

    monkeypatch.setattr(
        "app.services.radar.RadarItemRepository.get_by_id_for_user",
        fake_get_by_id_for_user,
    )

    with pytest.raises(NotFoundError):
        await RadarService(AsyncMock()).toggle_favorite(uuid4(), uuid4(), True)
