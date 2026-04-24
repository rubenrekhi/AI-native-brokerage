"""Integration tests for GET /v1/portfolio/history?range=...

End-to-end behavior: auth → account-context dep → range parsing →
cache → Alpaca → response shape. Uses real local Postgres (via
`authenticated_db_client`) but injects mock Alpaca + an in-memory fake
Redis through FastAPI `dependency_overrides`. Auto-skipped when
Postgres on :54322 is down.
"""

from __future__ import annotations

from datetime import datetime, timezone
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
    """Tiny in-memory stand-in for redis.asyncio.Redis."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._store[key] = value


def _history_payload(*, points: int = 30, base: float = 1000.0, step: float = 10.0) -> dict:
    """Build an Alpaca-style portfolio/history payload with N daily points."""
    day = 86_400
    start_ts = 1_700_000_000
    timestamps = [start_ts + i * day for i in range(points)]
    equities = [base + i * step for i in range(points)]
    return {
        "timestamp": timestamps,
        "equity": equities,
        "base_value": base,
        "timeframe": "1D",
    }


@pytest.fixture
def alpaca_mock() -> AsyncMock:
    svc = AsyncMock()
    svc.get_portfolio_history = AsyncMock(return_value=_history_payload())
    return svc


@pytest.fixture
def fake_redis() -> _FakeRedis:
    return _FakeRedis()


@pytest.fixture
def portfolio_deps(alpaca_mock, fake_redis):
    app.dependency_overrides[get_alpaca] = lambda: alpaca_mock
    app.dependency_overrides[get_redis] = lambda: fake_redis
    yield alpaca_mock, fake_redis
    app.dependency_overrides.pop(get_alpaca, None)
    app.dependency_overrides.pop(get_redis, None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHistoryHappyPath:
    async def test_one_month_returns_30_points_with_summary(
        self,
        authenticated_db_client,
        test_brokerage_account,
        portfolio_deps,
    ):
        alpaca_mock, _ = portfolio_deps
        alpaca_mock.get_portfolio_history.return_value = _history_payload(
            points=30, base=1000.0, step=10.0
        )

        response = await authenticated_db_client.get(
            "/v1/portfolio/history", params={"range": "1M"}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["range"] == "1M"
        assert body["timeframe"] == "1D"
        assert body["currency"] == "USD"
        assert body["base_value"] == "1000.00"
        # 30 points stepping +10 → last value = 1000 + 29*10 = 1290.
        assert body["end_value"] == "1290.00"
        assert body["gain_abs"] == "290.00"
        assert body["gain_pct"] == "0.2900"
        assert len(body["points"]) == 30
        # Alpaca called with the period/timeframe pair for 1M.
        alpaca_mock.get_portfolio_history.assert_awaited_once_with(
            test_brokerage_account["alpaca_account_id"],
            period="1M",
            timeframe="1D",
        )


class TestHistoryRangeParam:
    async def test_invalid_range_returns_422(
        self,
        authenticated_db_client,
        test_brokerage_account,
        portfolio_deps,
    ):
        alpaca_mock, _ = portfolio_deps

        response = await authenticated_db_client.get(
            "/v1/portfolio/history", params={"range": "FOO"}
        )

        assert response.status_code == 422
        alpaca_mock.get_portfolio_history.assert_not_called()

    async def test_missing_range_returns_422(
        self,
        authenticated_db_client,
        test_brokerage_account,
        portfolio_deps,
    ):
        alpaca_mock, _ = portfolio_deps

        response = await authenticated_db_client.get("/v1/portfolio/history")

        assert response.status_code == 422
        alpaca_mock.get_portfolio_history.assert_not_called()

    async def test_ytd_passes_dynamic_start_to_alpaca(
        self,
        authenticated_db_client,
        test_brokerage_account,
        portfolio_deps,
    ):
        alpaca_mock, _ = portfolio_deps

        response = await authenticated_db_client.get(
            "/v1/portfolio/history", params={"range": "YTD"}
        )

        assert response.status_code == 200
        # YTD computes the start of the current UTC year at request time.
        year = datetime.now(tz=timezone.utc).year
        alpaca_mock.get_portfolio_history.assert_awaited_once_with(
            test_brokerage_account["alpaca_account_id"],
            timeframe="1D",
            start=f"{year}-01-01T00:00:00Z",
        )

    async def test_one_day_uses_intraday_timeframe(
        self,
        authenticated_db_client,
        test_brokerage_account,
        portfolio_deps,
    ):
        # 1D is the only range that maps to a sub-daily timeframe.
        # Guards against regressions in `range_to_alpaca_params`.
        alpaca_mock, _ = portfolio_deps

        response = await authenticated_db_client.get(
            "/v1/portfolio/history", params={"range": "1D"}
        )

        assert response.status_code == 200
        alpaca_mock.get_portfolio_history.assert_awaited_once_with(
            test_brokerage_account["alpaca_account_id"],
            period="1D",
            timeframe="5Min",
        )


class TestHistoryAccountStatusGate:
    async def test_pending_account_returns_409_account_not_active(
        self,
        authenticated_db_client,
        test_brokerage_account_pending,
        portfolio_deps,
    ):
        # The dep collapses missing-row + non-ACTIVE into one 409 (commit
        # 034c65d). Pending accounts never reach Alpaca.
        alpaca_mock, _ = portfolio_deps

        response = await authenticated_db_client.get(
            "/v1/portfolio/history", params={"range": "1M"}
        )

        assert response.status_code == 409
        body = response.json()
        assert body["code"] == "ACCOUNT_NOT_ACTIVE"
        assert body["detail"] == {"account_status": "APPROVAL_PENDING"}
        alpaca_mock.get_portfolio_history.assert_not_called()


class TestHistoryAlpacaErrors:
    async def test_alpaca_unavailable_returns_503(
        self,
        authenticated_db_client,
        test_brokerage_account,
        portfolio_deps,
    ):
        alpaca_mock, _ = portfolio_deps
        alpaca_mock.get_portfolio_history.side_effect = AlpacaBrokerUnavailableError()

        response = await authenticated_db_client.get(
            "/v1/portfolio/history", params={"range": "1M"}
        )

        assert response.status_code == 503
        assert response.json()["code"] == "ALPACA_UNAVAILABLE"


class TestHistoryCaching:
    async def test_same_range_twice_skips_alpaca_on_second_call(
        self,
        authenticated_db_client,
        test_brokerage_account,
        portfolio_deps,
    ):
        alpaca_mock, _ = portfolio_deps

        first = await authenticated_db_client.get(
            "/v1/portfolio/history", params={"range": "1M"}
        )
        second = await authenticated_db_client.get(
            "/v1/portfolio/history", params={"range": "1M"}
        )

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json() == second.json()
        assert alpaca_mock.get_portfolio_history.call_count == 1

    async def test_different_range_triggers_fresh_alpaca_call(
        self,
        authenticated_db_client,
        test_brokerage_account,
        portfolio_deps,
    ):
        alpaca_mock, _ = portfolio_deps

        await authenticated_db_client.get(
            "/v1/portfolio/history", params={"range": "1M"}
        )
        await authenticated_db_client.get(
            "/v1/portfolio/history", params={"range": "1Y"}
        )

        assert alpaca_mock.get_portfolio_history.call_count == 2


class TestHistoryAuth:
    async def test_unauthenticated_returns_401(self, client):
        response = await client.get(
            "/v1/portfolio/history", params={"range": "1M"}
        )
        assert response.status_code == 401
        assert response.json()["code"] == "AUTHENTICATION_ERROR"
