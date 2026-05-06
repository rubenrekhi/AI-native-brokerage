"""Integration tests for GET /v1/portfolio/holdings.

End-to-end behavior: auth → account-context dep → cache → Alpaca + DB
join → response shape. Uses real local Postgres (via
`authenticated_db_client`) but injects mock Alpaca + an in-memory fake
Redis through FastAPI `dependency_overrides`. Auto-skipped when
Postgres on :54322 is down.

Names are joined in via `AssetRepository.get_names_by_symbols`, so the
happy-path test inserts real `assets` rows (rolled back with the
session).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

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


def _account(**overrides) -> dict:
    base = {"cash": "40291.92", "currency": "USD"}
    base.update(overrides)
    return base


def _position(symbol: str, market_value: str, **overrides) -> dict:
    base = {
        "symbol": symbol,
        "qty": "1",
        "avg_entry_price": "100.00",
        "current_price": "100.00",
        "market_value": market_value,
        "cost_basis": "100.00",
        "unrealized_pl": "0.00",
        "unrealized_plpc": "0.0000",
        "lastday_price": "100.00",
        "change_today": "0.0000",
    }
    base.update(overrides)
    return base


@pytest.fixture
def alpaca_mock() -> AsyncMock:
    svc = AsyncMock()
    svc.get_trading_account = AsyncMock(return_value=_account())
    svc.list_positions = AsyncMock(return_value=[])
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


@pytest.fixture
async def seed_assets(db_session):
    """Insert rows into `assets` for the happy-path symbol→name join.

    Rolled back with the test session — no cleanup needed.
    """
    await db_session.execute(
        text(
            """
            INSERT INTO assets (symbol, name, exchange, tradeable)
            VALUES
                ('TSLA', 'Tesla, Inc.', 'NASDAQ', true),
                ('AMD',  'Advanced Micro Devices, Inc.', 'NASDAQ', true)
            ON CONFLICT (symbol) DO UPDATE
                SET name = EXCLUDED.name
            """
        )
    )
    await db_session.flush()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHoldingsHappyPath:
    async def test_active_account_returns_sorted_holdings_with_names(
        self,
        authenticated_db_client,
        test_brokerage_account,
        portfolio_deps,
        seed_assets,
    ):
        alpaca_mock, _ = portfolio_deps
        alpaca_mock.list_positions.return_value = [
            _position("AMD", "200.00"),
            _position("TSLA", "1500.00"),
        ]

        response = await authenticated_db_client.get("/v1/portfolio/holdings")

        assert response.status_code == 200
        body = response.json()
        assert body["account_status"] == "ACTIVE"
        assert body["currency"] == "USD"
        assert body["cash"] == "40291.92"
        assert body["total_market_value"] == "1700.00"
        symbols = [p["symbol"] for p in body["positions"]]
        assert symbols == ["TSLA", "AMD"]
        assert body["positions"][0]["name"] == "Tesla, Inc."
        assert body["positions"][1]["name"] == "Advanced Micro Devices, Inc."
        alpaca_mock.get_trading_account.assert_awaited_once_with(
            test_brokerage_account["alpaca_account_id"]
        )
        alpaca_mock.list_positions.assert_awaited_once_with(
            test_brokerage_account["alpaca_account_id"]
        )

    async def test_fractional_qty_renders_as_string(
        self,
        authenticated_db_client,
        test_brokerage_account,
        portfolio_deps,
        seed_assets,
    ):
        alpaca_mock, _ = portfolio_deps
        alpaca_mock.list_positions.return_value = [
            _position("TSLA", "12.34", qty="0.125", avg_entry_price="98.72"),
        ]

        response = await authenticated_db_client.get("/v1/portfolio/holdings")

        assert response.status_code == 200
        body = response.json()
        assert body["positions"][0]["qty"] == "0.125"

    async def test_change_today_renders_in_response(
        self,
        authenticated_db_client,
        test_brokerage_account,
        portfolio_deps,
        seed_assets,
    ):
        # 100 shares moved $10 each today = $1000 position-level $
        # gain. iOS renders this directly under "Day's Gain" — no further
        # multiplication.
        alpaca_mock, _ = portfolio_deps
        alpaca_mock.list_positions.return_value = [
            _position(
                "TSLA",
                "11000.00",
                qty="100",
                current_price="110.00",
                lastday_price="100.00",
                change_today="0.10",
            ),
        ]

        response = await authenticated_db_client.get("/v1/portfolio/holdings")

        assert response.status_code == 200
        body = response.json()
        assert body["positions"][0]["change_today"] == "1000.00"
        assert body["positions"][0]["change_today_percent"] == "0.1000"

    async def test_unknown_symbol_falls_back_to_symbol_as_name(
        self,
        authenticated_db_client,
        test_brokerage_account,
        portfolio_deps,
    ):
        # No `seed_assets` fixture — the symbol has no row in `assets`.
        alpaca_mock, _ = portfolio_deps
        alpaca_mock.list_positions.return_value = [_position("XYZ", "50.00")]

        response = await authenticated_db_client.get("/v1/portfolio/holdings")

        assert response.status_code == 200
        body = response.json()
        assert body["positions"][0]["symbol"] == "XYZ"
        assert body["positions"][0]["name"] == "XYZ"


class TestHoldingsEmpty:
    async def test_empty_positions_returns_empty_list_with_cash(
        self,
        authenticated_db_client,
        test_brokerage_account,
        portfolio_deps,
    ):
        alpaca_mock, _ = portfolio_deps
        alpaca_mock.get_trading_account.return_value = _account(cash="500.00")
        alpaca_mock.list_positions.return_value = []

        response = await authenticated_db_client.get("/v1/portfolio/holdings")

        assert response.status_code == 200
        body = response.json()
        assert body["positions"] == []
        assert body["total_market_value"] == "0.00"
        assert body["cash"] == "500.00"


class TestHoldingsAccountStatusGate:
    async def test_pending_account_returns_409_account_not_active(
        self,
        authenticated_db_client,
        test_brokerage_account_pending,
        portfolio_deps,
    ):
        # The dep collapses missing-row + non-ACTIVE into one 409 (commit
        # 034c65d). Pending accounts never reach Alpaca.
        alpaca_mock, _ = portfolio_deps

        response = await authenticated_db_client.get("/v1/portfolio/holdings")

        assert response.status_code == 409
        body = response.json()
        assert body["code"] == "ACCOUNT_NOT_ACTIVE"
        assert body["detail"] == {"account_status": "APPROVAL_PENDING"}
        alpaca_mock.get_trading_account.assert_not_called()
        alpaca_mock.list_positions.assert_not_called()

    async def test_no_brokerage_row_returns_409_account_not_active(
        self,
        authenticated_db_client,
        test_user,  # auth user exists, but no brokerage_accounts row
        portfolio_deps,
    ):
        alpaca_mock, _ = portfolio_deps

        response = await authenticated_db_client.get("/v1/portfolio/holdings")

        assert response.status_code == 409
        body = response.json()
        assert body["code"] == "ACCOUNT_NOT_ACTIVE"
        assert body["detail"] == {"account_status": None}
        alpaca_mock.get_trading_account.assert_not_called()
        alpaca_mock.list_positions.assert_not_called()


class TestHoldingsAlpacaErrors:
    async def test_alpaca_unavailable_returns_503(
        self,
        authenticated_db_client,
        test_brokerage_account,
        portfolio_deps,
    ):
        # Holdings fans out `get_trading_account` + `list_positions` via
        # `asyncio.gather`; either side raising should still surface 503.
        alpaca_mock, _ = portfolio_deps
        alpaca_mock.list_positions.side_effect = AlpacaBrokerUnavailableError()

        response = await authenticated_db_client.get("/v1/portfolio/holdings")

        assert response.status_code == 503
        assert response.json()["code"] == "ALPACA_UNAVAILABLE"


class TestHoldingsCaching:
    async def test_second_call_within_ttl_skips_alpaca(
        self,
        authenticated_db_client,
        test_brokerage_account,
        portfolio_deps,
        seed_assets,
    ):
        alpaca_mock, fake_redis = portfolio_deps
        alpaca_mock.list_positions.return_value = [_position("TSLA", "1500.00")]

        first = await authenticated_db_client.get("/v1/portfolio/holdings")
        second = await authenticated_db_client.get("/v1/portfolio/holdings")

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json() == second.json()
        assert alpaca_mock.get_trading_account.call_count == 1
        assert alpaca_mock.list_positions.call_count == 1

        cache_key = f"portfolio:holdings:{test_brokerage_account['user_id']}"
        cached_raw = await fake_redis.get(cache_key)
        assert cached_raw is not None


class TestHoldingsAuth:
    async def test_unauthenticated_returns_401(self, client):
        response = await client.get("/v1/portfolio/holdings")
        assert response.status_code == 401
        assert response.json()["code"] == "AUTHENTICATION_ERROR"
