"""Unit tests for RadarService."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

from app.models.radar_item import RadarItem
from app.schemas.radar import RadarItemRead
from app.services.radar import RadarService


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
