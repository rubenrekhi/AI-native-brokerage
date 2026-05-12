"""Integration tests for the /v1/radar routes."""

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.exceptions import MarketDataUnavailableError
from app.main import app
from app.models.asset import Asset
from app.repositories.radar_item import RadarItemRepository
from app.services.market_data import MarketDataService, get_market_data_service
from tests.integration.conftest import _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync, reason="Local Postgres not running"
)


@pytest.fixture(autouse=True)
def mock_market_data():
    """Stub MarketDataService for every radar test.

    Autouse because the radar route's `_radar_service` factory wires in
    `get_market_data_service` for all four endpoints (even those that
    don't actually call market data). In test envs the real lifespan
    never runs, so `app.state.market_data` isn't set and the real
    Depends would raise `AttributeError`.

    Default behavior is an empty quotes list (overlay fields stay null
    on the GET response). Tests that exercise the overlay merge configure
    `get_batch_quotes.return_value` or `.side_effect`.
    """
    mock = AsyncMock(spec=MarketDataService)
    mock.get_batch_quotes.return_value = {"quotes": []}
    app.dependency_overrides[get_market_data_service] = lambda: mock
    yield mock
    app.dependency_overrides.pop(get_market_data_service, None)


@pytest.fixture
async def test_assets(db_session):
    """Ensure common tradeable tickers exist so radar POST tests pass asset
    validation. Idempotent — the `sync_assets` task may already have
    populated the table from the Alpaca catalog in shared dev environments.
    """
    stmt = pg_insert(Asset).values(
        [
            {"symbol": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ", "tradeable": True},
            {"symbol": "TSLA", "name": "Tesla, Inc.", "exchange": "NASDAQ", "tradeable": True},
            {"symbol": "NVDA", "name": "NVIDIA Corporation", "exchange": "NASDAQ", "tradeable": True},
            {"symbol": "AMZN", "name": "Amazon.com, Inc.", "exchange": "NASDAQ", "tradeable": True},
        ]
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["symbol"],
        set_={"tradeable": True, "name": stmt.excluded.name},
    )
    await db_session.execute(stmt)
    await db_session.flush()


async def test_get_radar_returns_empty_list_when_user_has_no_rows(
    authenticated_db_client, test_user
):
    response = await authenticated_db_client.get("/v1/radar")
    assert response.status_code == 200
    assert response.json() == []


async def test_get_radar_returns_null_overlay_when_no_quote_matches_symbol(
    authenticated_db_client, db_session, test_user, mock_market_data
):
    await RadarItemRepository.create_user_added(
        db_session, user_id=test_user, symbol="AAPL", company_name="Apple Inc.",
    )

    response = await authenticated_db_client.get("/v1/radar")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["symbol"] == "AAPL"
    assert body[0]["company_name"] == "Apple Inc."
    assert body[0]["source"] == "user_added"
    assert body[0]["is_favorited"] is True
    # `mock_market_data` defaults to an empty quotes list → overlay null.
    assert body[0]["price"] is None
    assert body[0]["change_abs"] is None
    assert body[0]["change_pct"] is None


async def test_get_radar_merges_live_prices_into_response(
    authenticated_db_client, db_session, test_user, mock_market_data
):
    await RadarItemRepository.create_user_added(
        db_session, user_id=test_user, symbol="AAPL", company_name="Apple Inc.",
    )
    mock_market_data.get_batch_quotes.return_value = {
        "quotes": [
            {
                "symbol": "AAPL",
                "price": "180.50",
                "change": "1.25",
                "change_percent": "1.24",
            }
        ]
    }

    response = await authenticated_db_client.get("/v1/radar")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["price"] == "180.50"
    assert body[0]["change_abs"] == "1.25"
    # FMP-percent (1.24) converted to PctStr factor (0.0124), serialized
    # with the 4-decimal PctStr precision.
    assert body[0]["change_pct"] == "0.0124"


async def test_get_radar_returns_200_with_null_overlay_when_market_data_fails(
    authenticated_db_client, db_session, test_user, mock_market_data
):
    await RadarItemRepository.create_user_added(
        db_session, user_id=test_user, symbol="AAPL", company_name="Apple Inc.",
    )
    mock_market_data.get_batch_quotes.side_effect = MarketDataUnavailableError()

    response = await authenticated_db_client.get("/v1/radar")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["symbol"] == "AAPL"
    assert body[0]["price"] is None
    assert body[0]["change_abs"] is None
    assert body[0]["change_pct"] is None


async def test_get_radar_requires_auth(client):
    response = await client.get("/v1/radar")
    assert response.status_code == 401


async def test_post_radar_creates_user_added_row(
    authenticated_db_client, test_user, test_assets
):
    response = await authenticated_db_client.post(
        "/v1/radar", json={"symbol": "aapl"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["symbol"] == "AAPL"
    assert body["company_name"] == "Apple Inc."
    assert body["source"] == "user_added"
    assert body["is_favorited"] is True
    assert body["expires_at"] is None


async def test_post_radar_returns_409_on_duplicate_symbol(
    authenticated_db_client, test_user, test_assets
):
    first = await authenticated_db_client.post("/v1/radar", json={"symbol": "AAPL"})
    assert first.status_code == 201

    second = await authenticated_db_client.post("/v1/radar", json={"symbol": "AAPL"})
    assert second.status_code == 409
    assert second.json()["code"] == "RADAR_DUPLICATE_SYMBOL"


async def test_post_radar_returns_409_when_symbol_not_in_assets(
    authenticated_db_client, test_user, test_assets
):
    response = await authenticated_db_client.post(
        "/v1/radar", json={"symbol": "ZZZZ"}
    )

    assert response.status_code == 409
    assert response.json()["code"] == "SYMBOL_NOT_TRADEABLE"


async def test_post_radar_returns_422_when_body_missing_symbol(
    authenticated_db_client, test_user
):
    response = await authenticated_db_client.post("/v1/radar", json={})
    assert response.status_code == 422


async def test_delete_radar_removes_row_and_subsequent_get_excludes_it(
    authenticated_db_client, db_session, test_user
):
    item = await RadarItemRepository.create_user_added(
        db_session, user_id=test_user, symbol="AAPL", company_name="Apple Inc.",
    )

    delete_response = await authenticated_db_client.delete(f"/v1/radar/{item.id}")
    assert delete_response.status_code == 204

    get_response = await authenticated_db_client.get("/v1/radar")
    assert get_response.json() == []


async def test_delete_radar_returns_404_for_unknown_id(
    authenticated_db_client, test_user
):
    response = await authenticated_db_client.delete(f"/v1/radar/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_delete_radar_does_not_let_user_b_delete_user_a_item(
    authenticated_db_client, db_session, test_user, make_extra_user
):
    other_user = await make_extra_user()
    item = await RadarItemRepository.create_user_added(
        db_session, user_id=other_user, symbol="AAPL", company_name="Apple Inc.",
    )

    # authenticated_db_client is acting as test_user, not other_user.
    response = await authenticated_db_client.delete(f"/v1/radar/{item.id}")
    assert response.status_code == 404


async def test_patch_unfavorite_user_added_returns_204_and_deletes_row(
    authenticated_db_client, db_session, test_user
):
    item = await RadarItemRepository.create_user_added(
        db_session, user_id=test_user, symbol="AAPL", company_name="Apple Inc.",
    )

    response = await authenticated_db_client.patch(
        f"/v1/radar/{item.id}", json={"is_favorited": False}
    )

    assert response.status_code == 204
    # Subsequent GET excludes the deleted row.
    get_response = await authenticated_db_client.get("/v1/radar")
    assert get_response.json() == []


async def test_patch_favorite_ai_generated_nulls_expires_at(
    authenticated_db_client, db_session, test_user
):
    item = await RadarItemRepository.create_ai_item(
        db_session, user_id=test_user, symbol="AAPL", company_name="Apple Inc.",
    )
    # Sanity: AI items start with a 7-day expiry from T3's factory.
    assert item.expires_at is not None

    response = await authenticated_db_client.patch(
        f"/v1/radar/{item.id}", json={"is_favorited": True}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["is_favorited"] is True
    assert body["expires_at"] is None


async def test_patch_unfavorite_ai_generated_resets_expires_at(
    authenticated_db_client, db_session, test_user
):
    # Start with a favorited AI item (expires_at=None) so the unfavorite
    # path has to repopulate the timer.
    item = await RadarItemRepository.create_ai_item(
        db_session, user_id=test_user, symbol="AAPL", company_name="Apple Inc.",
    )
    item.is_favorited = True
    item.expires_at = None
    await db_session.flush()

    response = await authenticated_db_client.patch(
        f"/v1/radar/{item.id}", json={"is_favorited": False}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["is_favorited"] is False
    assert body["expires_at"] is not None


async def test_patch_radar_returns_404_for_unknown_id(
    authenticated_db_client, test_user
):
    response = await authenticated_db_client.patch(
        f"/v1/radar/{uuid.uuid4()}", json={"is_favorited": True}
    )
    assert response.status_code == 404


async def test_patch_radar_does_not_let_user_b_modify_user_a_item(
    authenticated_db_client, db_session, test_user, make_extra_user
):
    other_user = await make_extra_user()
    item = await RadarItemRepository.create_user_added(
        db_session, user_id=other_user, symbol="AAPL", company_name="Apple Inc.",
    )

    response = await authenticated_db_client.patch(
        f"/v1/radar/{item.id}", json={"is_favorited": False}
    )
    assert response.status_code == 404
