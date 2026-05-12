"""Integration tests for the /v1/radar routes."""

import uuid

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.asset import Asset
from app.repositories.radar_item import RadarItemRepository
from tests.integration.conftest import _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync, reason="Local Postgres not running"
)


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


async def test_get_radar_returns_user_rows_with_null_overlay(
    authenticated_db_client, db_session, test_user
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
    # T11 adds the market-data overlay; null for now.
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
