"""Integration tests for the /v1/radar routes."""

import pytest

from app.repositories.radar_item import RadarItemRepository
from tests.integration.conftest import _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync, reason="Local Postgres not running"
)


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
