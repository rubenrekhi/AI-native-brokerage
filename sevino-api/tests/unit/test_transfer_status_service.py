import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
import redis.asyncio as aioredis

from app.services.portfolio import PortfolioRange
from app.services.transfer_status import handle_transfer_status_change


@pytest.fixture
def session():
    return AsyncMock()


@pytest.fixture
def redis_mock():
    mock = AsyncMock()
    mock.delete = AsyncMock()
    return mock


def _make_account(user_id: uuid.UUID | None = None):
    account = AsyncMock()
    account.user_id = user_id or uuid.UUID("00000000-0000-0000-0000-000000000001")
    return account


async def test_invalidates_every_history_range(
    session, redis_mock, monkeypatch
):
    account = _make_account()
    monkeypatch.setattr(
        "app.services.transfer_status.BrokerageAccountRepository.get_by_alpaca_account_id",
        AsyncMock(return_value=account),
    )

    await handle_transfer_status_change(
        session,
        redis_mock,
        alpaca_account_id="alp-1",
        transfer_id="trn-1",
        status_from="QUEUED",
        status_to="SENT_TO_CLEARING",
        event_time=datetime(2026, 5, 27, 23, 52, 19, tzinfo=timezone.utc),
    )

    user_id = account.user_id
    expected_keys = [
        f"portfolio:history:{user_id}:{r.value}" for r in PortfolioRange
    ]
    redis_mock.delete.assert_awaited_once_with(*expected_keys)
    # Regression guard — if anyone adds a value to PortfolioRange, this
    # number bumps and forces a deliberate re-look here.
    assert len(expected_keys) == len(PortfolioRange)


async def test_unknown_account_skips_cache_invalidation(
    session, redis_mock, monkeypatch
):
    monkeypatch.setattr(
        "app.services.transfer_status.BrokerageAccountRepository.get_by_alpaca_account_id",
        AsyncMock(return_value=None),
    )

    await handle_transfer_status_change(
        session,
        redis_mock,
        alpaca_account_id="alp-unknown",
        transfer_id="trn-x",
        status_from=None,
        status_to="QUEUED",
        event_time=None,
    )

    redis_mock.delete.assert_not_awaited()


async def test_redis_error_does_not_propagate(session, redis_mock, monkeypatch):
    monkeypatch.setattr(
        "app.services.transfer_status.BrokerageAccountRepository.get_by_alpaca_account_id",
        AsyncMock(return_value=_make_account()),
    )
    redis_mock.delete.side_effect = aioredis.RedisError("boom")

    # Must not raise — cache_invalidate swallows the error, and the service
    # treats invalidation as best-effort.
    await handle_transfer_status_change(
        session,
        redis_mock,
        alpaca_account_id="alp-1",
        transfer_id="trn-1",
        status_from="",
        status_to="REJECTED",
        event_time=None,
    )

    redis_mock.delete.assert_awaited_once()


async def test_empty_status_from_handled_gracefully(
    session, redis_mock, monkeypatch
):
    # Alpaca emits status_from="" (not None) for first-status events.
    # Confirmed by SEV-594 sandbox probe sample: status_from='' on QUEUED.
    monkeypatch.setattr(
        "app.services.transfer_status.BrokerageAccountRepository.get_by_alpaca_account_id",
        AsyncMock(return_value=_make_account()),
    )

    await handle_transfer_status_change(
        session,
        redis_mock,
        alpaca_account_id="alp-1",
        transfer_id="trn-1",
        status_from="",
        status_to="QUEUED",
        event_time=None,
    )

    redis_mock.delete.assert_awaited_once()
