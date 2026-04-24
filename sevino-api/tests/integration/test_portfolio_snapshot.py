"""Integration tests for GET /v1/portfolio/snapshot.

End-to-end behavior: auth → account-context dep → cache → Alpaca → response
shape. Uses real local Postgres (via `authenticated_db_client`) but injects
mock Alpaca + an in-memory fake Redis through FastAPI `dependency_overrides`
so the test doesn't need a live broker or Redis. Auto-skipped when Postgres
on :54322 is down.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from app.dependencies import get_redis
from app.main import app
from app.routes.portfolio import get_alpaca
from app.services.alpaca_broker import AlpacaBrokerUnavailableError
from tests.integration.conftest import _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync, reason="Local Postgres not available on :54322"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _FakeRedis:
    """Tiny in-memory stand-in for redis.asyncio.Redis.

    Supports the two methods `cache_get_or_set` actually calls (`get`, `setex`)
    so the cache-hit path can be exercised without a live Redis.
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._store[key] = value


@pytest.fixture
def alpaca_mock() -> AsyncMock:
    svc = AsyncMock()
    svc.get_trading_account = AsyncMock(
        return_value={
            "equity": "1084.92",
            "last_equity": "852.10",
            "cash": "40291.92",
            "buying_power": "40291.92",
            "currency": "USD",
        }
    )
    return svc


@pytest.fixture
def fake_redis() -> _FakeRedis:
    return _FakeRedis()


@pytest.fixture
def portfolio_deps(alpaca_mock, fake_redis):
    """Inject mock Alpaca + fake Redis via FastAPI `dependency_overrides`.

    `get_alpaca` and `get_redis` are themselves `Depends()` callables, so
    overriding them keeps the mutation scoped to the override dict and
    cleaned up on teardown — no `app.state` mutation needed.
    """
    app.dependency_overrides[get_alpaca] = lambda: alpaca_mock
    app.dependency_overrides[get_redis] = lambda: fake_redis
    yield alpaca_mock, fake_redis
    app.dependency_overrides.pop(get_alpaca, None)
    app.dependency_overrides.pop(get_redis, None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSnapshotHappyPath:
    async def test_active_account_returns_200_with_snapshot(
        self,
        authenticated_db_client,
        test_brokerage_account,
        portfolio_deps,
    ):
        alpaca_mock, _ = portfolio_deps

        response = await authenticated_db_client.get("/v1/portfolio/snapshot")

        assert response.status_code == 200
        body = response.json()
        assert body["account_status"] == "ACTIVE"
        assert body["currency"] == "USD"
        assert body["equity"] == "1084.92"
        assert body["last_equity"] == "852.10"
        assert body["cash"] == "40291.92"
        assert body["buying_power"] == "40291.92"
        assert body["daily_change_abs"] == "232.82"
        assert body["daily_change_pct"] == "0.2732"
        alpaca_mock.get_trading_account.assert_awaited_once_with(
            test_brokerage_account["alpaca_account_id"]
        )


class TestSnapshotAccountStatusGate:
    async def test_pending_account_returns_409_account_not_active(
        self,
        authenticated_db_client,
        test_brokerage_account_pending,
        portfolio_deps,
    ):
        # The dep collapses missing-row + non-ACTIVE into one 409 (commit
        # 034c65d). Pending accounts never reach Alpaca.
        alpaca_mock, _ = portfolio_deps

        response = await authenticated_db_client.get("/v1/portfolio/snapshot")

        assert response.status_code == 409
        body = response.json()
        assert body["code"] == "ACCOUNT_NOT_ACTIVE"
        assert body["detail"] == {"account_status": "APPROVAL_PENDING"}
        alpaca_mock.get_trading_account.assert_not_called()

    async def test_no_brokerage_row_returns_409_account_not_active(
        self,
        authenticated_db_client,
        test_user,  # auth user exists, but no brokerage_accounts row
        portfolio_deps,
    ):
        alpaca_mock, _ = portfolio_deps

        response = await authenticated_db_client.get("/v1/portfolio/snapshot")

        assert response.status_code == 409
        body = response.json()
        assert body["code"] == "ACCOUNT_NOT_ACTIVE"
        assert body["detail"] == {"account_status": None}
        alpaca_mock.get_trading_account.assert_not_called()


class TestSnapshotAlpacaErrors:
    async def test_alpaca_unavailable_returns_503(
        self,
        authenticated_db_client,
        test_brokerage_account,
        portfolio_deps,
    ):
        alpaca_mock, _ = portfolio_deps
        alpaca_mock.get_trading_account.side_effect = AlpacaBrokerUnavailableError()

        response = await authenticated_db_client.get("/v1/portfolio/snapshot")

        assert response.status_code == 503
        assert response.json()["code"] == "ALPACA_UNAVAILABLE"


class TestSnapshotCaching:
    async def test_second_call_within_ttl_skips_alpaca(
        self,
        authenticated_db_client,
        test_brokerage_account,
        portfolio_deps,
    ):
        alpaca_mock, fake_redis = portfolio_deps

        first = await authenticated_db_client.get("/v1/portfolio/snapshot")
        second = await authenticated_db_client.get("/v1/portfolio/snapshot")

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json() == second.json()
        assert alpaca_mock.get_trading_account.call_count == 1

        cache_key = f"portfolio:snapshot:{test_brokerage_account['user_id']}"
        cached_raw = await fake_redis.get(cache_key)
        assert cached_raw is not None
        assert json.loads(cached_raw)["equity"] == "1084.92"


class TestSnapshotAuth:
    async def test_unauthenticated_returns_401(self, client):
        # `client` from tests/conftest.py has no auth override.
        response = await client.get("/v1/portfolio/snapshot")
        assert response.status_code == 401
        assert response.json()["code"] == "AUTHENTICATION_ERROR"
