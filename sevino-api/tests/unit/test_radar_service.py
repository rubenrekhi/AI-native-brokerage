"""Unit tests for RadarService."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.exceptions import (
    ConflictError,
    MarketDataError,
    MarketDataInvalidInputError,
    MarketDataUnavailableError,
    MarketDataUpstreamError,
    NotFoundError,
)
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


def _orm_row(symbol: str = "AAPL", user_id=None) -> RadarItem:
    return RadarItem(
        id=uuid4(),
        user_id=user_id or uuid4(),
        symbol=symbol,
        company_name="Apple Inc.",
        context_blurb=None,
        source="user_added",
        is_favorited=True,
        relevance_score=None,
        expires_at=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _patch_profile(monkeypatch, anchor=None):
    """Patch UserProfileRepository.get_by_id so list_for_user can read the
    cadence anchor without a real DB."""
    async def fake_get_by_id(db, user_id):
        return SimpleNamespace(next_radar_refresh_at=anchor)

    monkeypatch.setattr(
        "app.services.radar.UserProfileRepository.get_by_id", fake_get_by_id
    )


async def test_list_for_user_returns_empty_and_skips_market_data_when_no_rows(
    monkeypatch,
):
    async def fake_list_for_user(db, user_id):
        return []

    monkeypatch.setattr(
        "app.services.radar.RadarItemRepository.list_for_user",
        fake_list_for_user,
    )
    anchor = datetime(2026, 2, 1, tzinfo=timezone.utc)
    _patch_profile(monkeypatch, anchor)

    market_data = AsyncMock()
    result = await RadarService(market_data, AsyncMock()).list_for_user(uuid4())

    # Anchor surfaces even with no items — iOS needs it for the empty state.
    assert result.items == []
    assert result.next_refresh_at == anchor
    market_data.get_batch_quotes.assert_not_called()


async def test_list_for_user_returns_null_overlay_when_symbol_missing_from_quotes(
    monkeypatch,
):
    user_id = uuid4()
    row = _orm_row(symbol="AAPL", user_id=user_id)

    async def fake_list_for_user(db, uid):
        return [row]

    monkeypatch.setattr(
        "app.services.radar.RadarItemRepository.list_for_user",
        fake_list_for_user,
    )
    _patch_profile(monkeypatch)

    market_data = AsyncMock()
    market_data.get_batch_quotes.return_value = {"quotes": []}

    result = await RadarService(market_data, AsyncMock()).list_for_user(user_id)

    market_data.get_batch_quotes.assert_awaited_once_with(["AAPL"])
    assert len(result.items) == 1
    assert isinstance(result.items[0], RadarItemRead)
    assert result.items[0].price is None
    assert result.items[0].change_abs is None
    assert result.items[0].change_pct is None


async def test_list_for_user_merges_quote_overlay_into_matching_rows(monkeypatch):
    user_id = uuid4()
    row = _orm_row(symbol="AAPL", user_id=user_id)

    async def fake_list_for_user(db, uid):
        return [row]

    monkeypatch.setattr(
        "app.services.radar.RadarItemRepository.list_for_user",
        fake_list_for_user,
    )
    _patch_profile(monkeypatch)

    market_data = AsyncMock()
    market_data.get_batch_quotes.return_value = {
        "quotes": [
            {
                "symbol": "AAPL",
                "price": "180.50",
                "change": "1.25",
                # FMP returns the percentage value (1.24% → "1.24"); the
                # service divides by 100 to fit the PctStr factor convention.
                "change_percent": "1.24",
            }
        ]
    }

    result = await RadarService(market_data, AsyncMock()).list_for_user(user_id)

    assert result.items[0].price == Decimal("180.50")
    assert result.items[0].change_abs == Decimal("1.25")
    assert result.items[0].change_pct == Decimal("1.24") / Decimal(100)


async def test_list_for_user_graceful_degrades_on_market_data_unavailable(
    monkeypatch,
):
    user_id = uuid4()
    row = _orm_row(symbol="AAPL", user_id=user_id)

    async def fake_list_for_user(db, uid):
        return [row]

    monkeypatch.setattr(
        "app.services.radar.RadarItemRepository.list_for_user",
        fake_list_for_user,
    )
    _patch_profile(monkeypatch)

    market_data = AsyncMock()
    market_data.get_batch_quotes.side_effect = MarketDataUnavailableError()

    result = await RadarService(market_data, AsyncMock()).list_for_user(user_id)

    assert len(result.items) == 1
    assert result.items[0].price is None
    assert result.items[0].change_abs is None
    assert result.items[0].change_pct is None


@pytest.mark.parametrize(
    "error",
    [
        MarketDataUpstreamError(status_code=429),
        MarketDataUpstreamError(status_code=500),
        MarketDataError("no data for AAPL", symbol="AAPL"),
        MarketDataInvalidInputError("bad symbol"),
    ],
)
async def test_list_for_user_graceful_degrades_on_any_market_data_error(
    monkeypatch, error
):
    """Live quote overlay is optional — every MarketData* error must fall
    through to null overlays, never a 5xx. Regression for FMP 429s blowing
    up GET /v1/radar instead of degrading."""
    user_id = uuid4()
    row = _orm_row(symbol="AAPL", user_id=user_id)

    async def fake_list_for_user(db, uid):
        return [row]

    monkeypatch.setattr(
        "app.services.radar.RadarItemRepository.list_for_user",
        fake_list_for_user,
    )
    _patch_profile(monkeypatch)

    market_data = AsyncMock()
    market_data.get_batch_quotes.side_effect = error

    result = await RadarService(market_data, AsyncMock()).list_for_user(user_id)

    assert len(result.items) == 1
    assert result.items[0].price is None
    assert result.items[0].change_abs is None
    assert result.items[0].change_pct is None


async def test_add_user_item_uppercases_symbol_before_asset_lookup(monkeypatch):
    captured = _patch_repos(
        monkeypatch,
        asset=Asset(symbol="AAPL", name="Apple Inc.", tradeable=True),
    )

    await RadarService(AsyncMock(), AsyncMock()).add_user_item(uuid4(), "aapl")

    assert captured["lookup_symbol"] == "AAPL"
    assert captured["symbol"] == "AAPL"


async def test_add_user_item_raises_symbol_not_tradeable_when_asset_missing(
    monkeypatch,
):
    _patch_repos(monkeypatch, asset=None)

    with pytest.raises(ConflictError) as exc_info:
        await RadarService(AsyncMock(), AsyncMock()).add_user_item(uuid4(), "ZZZZ")

    assert exc_info.value.code == "SYMBOL_NOT_TRADEABLE"
    assert exc_info.value.detail == {"symbol": "ZZZZ"}


async def test_add_user_item_translates_integrity_error_to_duplicate(monkeypatch):
    _patch_repos(
        monkeypatch,
        asset=Asset(symbol="AAPL", name="Apple Inc.", tradeable=True),
        create_raises=IntegrityError("stmt", {}, Exception("dup")),
    )

    with pytest.raises(ConflictError) as exc_info:
        await RadarService(AsyncMock(), AsyncMock()).add_user_item(uuid4(), "AAPL")

    assert exc_info.value.code == "RADAR_DUPLICATE_SYMBOL"
    assert exc_info.value.detail == {"symbol": "AAPL"}


async def test_add_user_item_persists_company_name_from_asset(monkeypatch):
    captured = _patch_repos(
        monkeypatch,
        asset=Asset(symbol="AAPL", name="Apple Inc.", tradeable=True),
    )

    await RadarService(AsyncMock(), AsyncMock()).add_user_item(uuid4(), "AAPL")

    assert captured["company_name"] == "Apple Inc."


async def test_remove_raises_not_found_when_item_unknown(monkeypatch):
    async def fake_get_by_id_for_user(db, item_id, user_id):
        return None

    monkeypatch.setattr(
        "app.services.radar.RadarItemRepository.get_by_id_for_user",
        fake_get_by_id_for_user,
    )

    with pytest.raises(NotFoundError):
        await RadarService(AsyncMock(), AsyncMock()).remove(uuid4(), uuid4())


def _make_radar_item(
    *,
    is_favorited: bool,
    source: str = "user_added",
    expires_at: datetime | None = None,
) -> RadarItem:
    return RadarItem(
        id=uuid4(),
        user_id=uuid4(),
        symbol="AAPL",
        company_name="Apple Inc.",
        context_blurb=None,
        source=source,
        is_favorited=is_favorited,
        relevance_score=None,
        expires_at=expires_at,
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
    result = await RadarService(AsyncMock(), db).toggle_favorite(
        uuid4(), uuid4(), True
    )

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
    result = await RadarService(AsyncMock(), db).toggle_favorite(
        uuid4(), uuid4(), True
    )

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
        await RadarService(AsyncMock(), AsyncMock()).toggle_favorite(uuid4(), uuid4(), True)


async def test_toggle_unfavorite_user_added_deletes_row_and_returns_none(
    monkeypatch,
):
    item = _make_radar_item(is_favorited=True, source="user_added")

    async def fake_get_by_id_for_user(db, item_id, user_id):
        return item

    deleted: list[RadarItem] = []

    async def fake_delete(db, target):
        deleted.append(target)

    monkeypatch.setattr(
        "app.services.radar.RadarItemRepository.get_by_id_for_user",
        fake_get_by_id_for_user,
    )
    monkeypatch.setattr(
        "app.services.radar.RadarItemRepository.delete", fake_delete
    )

    result = await RadarService(AsyncMock(), AsyncMock()).toggle_favorite(
        uuid4(), uuid4(), False
    )

    assert result is None
    assert deleted == [item]


async def test_toggle_favorite_ai_generated_nulls_expires_at(monkeypatch):
    future = datetime.now(timezone.utc) + timedelta(days=3)
    item = _make_radar_item(
        is_favorited=False, source="ai_generated", expires_at=future
    )

    async def fake_get_by_id_for_user(db, item_id, user_id):
        return item

    monkeypatch.setattr(
        "app.services.radar.RadarItemRepository.get_by_id_for_user",
        fake_get_by_id_for_user,
    )

    result = await RadarService(AsyncMock(), AsyncMock()).toggle_favorite(
        uuid4(), uuid4(), True
    )

    assert result is not None
    assert result.is_favorited is True
    assert item.expires_at is None


async def test_toggle_unfavorite_ai_generated_resets_expires_at(monkeypatch):
    item = _make_radar_item(
        is_favorited=True, source="ai_generated", expires_at=None
    )

    async def fake_get_by_id_for_user(db, item_id, user_id):
        return item

    monkeypatch.setattr(
        "app.services.radar.RadarItemRepository.get_by_id_for_user",
        fake_get_by_id_for_user,
    )

    before = datetime.now(timezone.utc)
    result = await RadarService(AsyncMock(), AsyncMock()).toggle_favorite(
        uuid4(), uuid4(), False
    )
    after = datetime.now(timezone.utc)

    assert result is not None
    assert result.is_favorited is False
    # expires_at lands in [before + 7d, after + 7d].
    assert item.expires_at is not None
    assert before + timedelta(days=7) <= item.expires_at <= after + timedelta(days=7)


async def test_remove_by_symbol_deletes_and_returns_true(monkeypatch):
    item = _make_radar_item(is_favorited=True)
    deleted: list[RadarItem] = []

    async def fake_get_by_symbol_for_user(db, user_id, symbol):
        return item

    async def fake_delete(db, target):
        deleted.append(target)

    monkeypatch.setattr(
        "app.services.radar.RadarItemRepository.get_by_symbol_for_user",
        fake_get_by_symbol_for_user,
    )
    monkeypatch.setattr(
        "app.services.radar.RadarItemRepository.delete", fake_delete
    )

    result = await RadarService(AsyncMock(), AsyncMock()).remove_user_item_by_symbol(
        uuid4(), "AAPL"
    )

    assert result is True
    assert deleted == [item]


async def test_remove_by_symbol_returns_false_when_absent(monkeypatch):
    delete_called = False

    async def fake_get_by_symbol_for_user(db, user_id, symbol):
        return None

    async def fake_delete(db, target):
        nonlocal delete_called
        delete_called = True

    monkeypatch.setattr(
        "app.services.radar.RadarItemRepository.get_by_symbol_for_user",
        fake_get_by_symbol_for_user,
    )
    monkeypatch.setattr(
        "app.services.radar.RadarItemRepository.delete", fake_delete
    )

    result = await RadarService(AsyncMock(), AsyncMock()).remove_user_item_by_symbol(
        uuid4(), "AAPL"
    )

    assert result is False
    assert delete_called is False


async def test_remove_by_symbol_uppercases_before_lookup(monkeypatch):
    captured: dict = {}

    async def fake_get_by_symbol_for_user(db, user_id, symbol):
        captured["symbol"] = symbol
        return None

    monkeypatch.setattr(
        "app.services.radar.RadarItemRepository.get_by_symbol_for_user",
        fake_get_by_symbol_for_user,
    )

    await RadarService(AsyncMock(), AsyncMock()).remove_user_item_by_symbol(
        uuid4(), "aapl"
    )

    assert captured["symbol"] == "AAPL"


async def test_list_items_returns_reads_without_calling_market_data(monkeypatch):
    rows = [_orm_row(symbol="AAPL"), _orm_row(symbol="NVDA")]

    async def fake_list_for_user(db, user_id):
        return rows

    monkeypatch.setattr(
        "app.services.radar.RadarItemRepository.list_for_user",
        fake_list_for_user,
    )

    market_data = AsyncMock()
    result = await RadarService(market_data, AsyncMock()).list_items(uuid4())

    assert [r.symbol for r in result] == ["AAPL", "NVDA"]
    assert all(isinstance(r, RadarItemRead) for r in result)
    # "get" never needs live quotes — the price overlay is skipped.
    market_data.get_batch_quotes.assert_not_called()


async def test_list_items_returns_empty_list_for_no_rows(monkeypatch):
    async def fake_list_for_user(db, user_id):
        return []

    monkeypatch.setattr(
        "app.services.radar.RadarItemRepository.list_for_user",
        fake_list_for_user,
    )

    result = await RadarService(AsyncMock(), AsyncMock()).list_items(uuid4())
    assert result == []


async def test_remove_by_symbol_deletes_ai_generated_rows_too(monkeypatch):
    item = _make_radar_item(is_favorited=False, source="ai_generated")
    deleted: list[RadarItem] = []

    async def fake_get_by_symbol_for_user(db, user_id, symbol):
        return item

    async def fake_delete(db, target):
        deleted.append(target)

    monkeypatch.setattr(
        "app.services.radar.RadarItemRepository.get_by_symbol_for_user",
        fake_get_by_symbol_for_user,
    )
    monkeypatch.setattr(
        "app.services.radar.RadarItemRepository.delete", fake_delete
    )

    result = await RadarService(AsyncMock(), AsyncMock()).remove_user_item_by_symbol(
        uuid4(), "AAPL"
    )

    assert result is True
    assert deleted == [item]
