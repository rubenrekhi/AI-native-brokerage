"""Integration tests for the /v1/digest routes."""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.digest import DigestSnapshot
from app.repositories.digest import DigestRepository
from app.services.digest.context import ET
from tests.integration.conftest import _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync, reason="Local Postgres not running"
)


def _today_ny():
    return datetime.now(timezone.utc).astimezone(ET).date()


async def _seed_today(db_session, user_id, *, cards=None) -> DigestSnapshot:
    return await DigestRepository.upsert(
        db_session,
        DigestSnapshot(
            user_id=user_id,
            ny_local_date=_today_ny(),
            cards=cards if cards is not None else [],
            generated_at=datetime.now(timezone.utc),
        ),
    )


async def test_get_today_returns_204_when_no_snapshot(
    authenticated_db_client, test_user
):
    response = await authenticated_db_client.get("/v1/digest/today")
    assert response.status_code == 204


async def test_get_today_returns_empty_card_stack_when_present(
    authenticated_db_client, db_session, test_user
):
    await _seed_today(db_session, test_user, cards=[])

    response = await authenticated_db_client.get("/v1/digest/today")

    assert response.status_code == 200
    body = response.json()
    assert body["peek_visible"] is False
    assert body["snapshot"]["cards"] == []
    assert body["snapshot"]["ny_local_date"] == _today_ny().isoformat()
    assert body["snapshot"]["dismissed_at"] is None


async def test_get_today_serializes_persisted_cards(
    authenticated_db_client, db_session, test_user
):
    card = {
        "kind": "news",
        "id": "22222222-2222-2222-2222-222222222222",
        "priority": 1,
        "related_symbols": ["NVDA"],
        "card_context": {},
        "symbol": "NVDA",
        "headline": "Chip rally",
        "source": "Reuters",
        "url": "https://example.com/n",
        "published_at": "2026-05-30T18:30:00Z",
        "summary": "summary",
    }
    await _seed_today(db_session, test_user, cards=[card])

    response = await authenticated_db_client.get("/v1/digest/today")

    assert response.status_code == 200
    cards = response.json()["snapshot"]["cards"]
    assert len(cards) == 1
    assert cards[0]["kind"] == "news"
    assert cards[0]["symbol"] == "NVDA"


async def test_get_today_ignores_other_days(
    authenticated_db_client, db_session, test_user
):
    await DigestRepository.upsert(
        db_session,
        DigestSnapshot(
            user_id=test_user,
            ny_local_date=_today_ny() - timedelta(days=1),
            cards=[],
            generated_at=datetime.now(timezone.utc),
        ),
    )

    response = await authenticated_db_client.get("/v1/digest/today")
    assert response.status_code == 204


async def test_get_today_requires_auth(client):
    response = await client.get("/v1/digest/today")
    assert response.status_code == 401


async def test_dismiss_marks_snapshot_and_persists_across_requests(
    authenticated_db_client, db_session, test_user
):
    await _seed_today(db_session, test_user, cards=[])

    dismiss = await authenticated_db_client.post("/v1/digest/dismiss")
    assert dismiss.status_code == 204

    # Dismissed snapshot still returns, now flagged for the peek presentation.
    follow_up = await authenticated_db_client.get("/v1/digest/today")
    assert follow_up.status_code == 200
    body = follow_up.json()
    assert body["peek_visible"] is True
    assert body["snapshot"]["dismissed_at"] is not None


async def test_dismiss_is_idempotent(
    authenticated_db_client, db_session, test_user
):
    await _seed_today(db_session, test_user, cards=[])

    first = await authenticated_db_client.post("/v1/digest/dismiss")
    assert first.status_code == 204
    second = await authenticated_db_client.post("/v1/digest/dismiss")
    assert second.status_code == 204

    follow_up = await authenticated_db_client.get("/v1/digest/today")
    assert follow_up.json()["snapshot"]["dismissed_at"] is not None


async def test_dismiss_returns_404_when_no_digest_today(
    authenticated_db_client, test_user
):
    response = await authenticated_db_client.post("/v1/digest/dismiss")
    assert response.status_code == 404


async def test_dismiss_requires_auth(client):
    response = await client.post("/v1/digest/dismiss")
    assert response.status_code == 401
