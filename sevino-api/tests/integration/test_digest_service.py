"""Integration tests for DigestService.generate_for_user.

A user with no ACTIVE brokerage account never reaches Alpaca
(``build_context`` short-circuits), so a stub client is sufficient. The
default generator set is empty unless managed provider clients are injected.
"""

from unittest.mock import AsyncMock

import pytest

from app.services.alpaca_broker import AlpacaBrokerService
from app.services.digest.service import DigestService
from tests.integration.conftest import _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync, reason="Local Postgres not running"
)


def _service(db_session) -> DigestService:
    return DigestService(db_session, alpaca=AsyncMock(spec=AlpacaBrokerService))


async def test_generate_for_user_persists_empty_digest(db_session, test_user):
    service = _service(db_session)

    snapshot = await service.generate_for_user(test_user)

    assert snapshot.cards == []
    assert snapshot.generated_at is not None
    today = await service.get_today(test_user)
    assert today is not None
    assert today.id == snapshot.id


async def test_generate_for_user_is_idempotent_for_the_day(
    db_session, test_user
):
    service = _service(db_session)

    first = await service.generate_for_user(test_user)
    second = await service.generate_for_user(test_user)

    assert second.id == first.id


async def test_generate_does_not_call_alpaca_without_active_account(
    db_session, test_user
):
    alpaca = AsyncMock(spec=AlpacaBrokerService)
    service = DigestService(db_session, alpaca=alpaca)

    await service.generate_for_user(test_user)

    alpaca.get_trading_account.assert_not_called()
    alpaca.list_positions.assert_not_called()
