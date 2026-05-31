"""GET /v1/radar returns the T6 wrapper: {items, next_refresh_at}.

Covers the wire-format change from a bare list to the wrapper that also
carries the cadence anchor (so iOS can render the right empty-state copy)
and the newly-exposed ``bucket`` field on each item.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from app.main import app
from app.repositories.radar_item import RadarItemRepository
from app.services.market_data import MarketDataService, get_market_data_service
from tests.integration.conftest import TEST_USER_ID, _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync, reason="Local Postgres not running"
)


@pytest.fixture(autouse=True)
def mock_market_data():
    """Stub MarketDataService (the radar route wires it for every endpoint;
    the real lifespan never runs under tests). Empty quotes → null overlay."""
    mock = AsyncMock(spec=MarketDataService)
    mock.get_batch_quotes.return_value = {"quotes": []}
    app.dependency_overrides[get_market_data_service] = lambda: mock
    yield mock
    app.dependency_overrides.pop(get_market_data_service, None)


async def _set_anchor(db_session, user_id: uuid.UUID, anchor: datetime) -> None:
    await db_session.execute(
        text(
            "UPDATE user_profiles SET next_radar_refresh_at = :v WHERE id = :id"
        ),
        {"v": anchor, "id": user_id},
    )
    await db_session.flush()


async def test_response_is_wrapper_with_items_and_anchor(
    authenticated_db_client, db_session, test_user
):
    anchor = datetime.now(timezone.utc) + timedelta(days=5)
    await _set_anchor(db_session, test_user, anchor)
    await RadarItemRepository.create_ai_item(
        db_session,
        user_id=test_user,
        symbol="NVDA",
        company_name="NVIDIA Corporation",
        context_blurb="Major chipmaker in a sector you don't currently own",
        relevance_score=0.9,
        bucket="diversification",
    )

    response = await authenticated_db_client.get("/v1/radar")

    assert response.status_code == 200
    body = response.json()
    # Wrapper shape — not a bare list.
    assert set(body.keys()) == {"items", "next_refresh_at"}
    assert datetime.fromisoformat(body["next_refresh_at"]) == anchor

    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["symbol"] == "NVDA"
    assert item["source"] == "ai_generated"
    assert item["bucket"] == "diversification"


async def test_empty_radar_still_returns_anchor(
    authenticated_db_client, db_session, test_user
):
    """No items yet, but the anchor is set — iOS needs it for the
    "next batch arrives {weekday}" empty state."""
    anchor = datetime.now(timezone.utc) + timedelta(days=7)
    await _set_anchor(db_session, test_user, anchor)

    response = await authenticated_db_client.get("/v1/radar")

    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert datetime.fromisoformat(body["next_refresh_at"]) == anchor


async def test_null_anchor_before_first_batch(
    authenticated_db_client, db_session, test_user
):
    """A user who hasn't completed onboarding has a null anchor."""
    response = await authenticated_db_client.get("/v1/radar")

    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["next_refresh_at"] is None


async def test_user_added_item_has_null_bucket(
    authenticated_db_client, db_session, test_user
):
    await RadarItemRepository.create_user_added(
        db_session, user_id=test_user, symbol="AAPL", company_name="Apple Inc."
    )

    response = await authenticated_db_client.get("/v1/radar")

    body = response.json()
    assert body["items"][0]["symbol"] == "AAPL"
    assert body["items"][0]["bucket"] is None
