"""Integration tests for /v1/brokerage/* routes."""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.exceptions import register_exception_handlers
from app.routes.brokerage import get_alpaca, router as brokerage_router
from app.services.alpaca_broker import AlpacaBrokerError, AlpacaBrokerUnavailableError

TEST_USER_ID = str(uuid.uuid4())


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(brokerage_router, prefix="/v1/brokerage", tags=["brokerage"])
    register_exception_handlers(app)
    return app


@pytest.fixture
def alpaca_mock() -> AsyncMock:
    svc = AsyncMock()
    svc.list_orders.return_value = []
    svc.list_positions.return_value = []
    return svc


@pytest.fixture
def brokerage():
    return SimpleNamespace(
        id=uuid.uuid4(),
        alpaca_account_id="alpaca_acc_42",
        account_status="ACTIVE",
    )


@pytest.fixture
def patch_brokerage(mocker, brokerage):
    return mocker.patch(
        "app.services.brokerage.BrokerageAccountRepository.get_by_user_id",
        new_callable=AsyncMock,
        return_value=brokerage,
    )


@pytest.fixture
async def client(alpaca_mock):
    app = _build_app()

    async def _override_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: TEST_USER_ID
    app.dependency_overrides[get_alpaca] = lambda: alpaca_mock

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


def _make_order(**overrides):
    defaults = dict(
        id="ord_1",
        client_order_id="cli_1",
        symbol="AAPL",
        asset_class="us_equity",
        side="buy",
        order_type="market",
        time_in_force="day",
        qty="1",
        notional=None,
        filled_qty="1",
        filled_avg_price="180.00",
        limit_price=None,
        stop_price=None,
        status="filled",
        submitted_at="2026-04-20T14:00:00Z",
        filled_at="2026-04-20T14:00:01Z",
        canceled_at=None,
        expired_at=None,
        failed_at=None,
        created_at="2026-04-20T14:00:00Z",
        # Alpaca-internal fields that should be dropped at the boundary
        account_id="acc_42",
        legs=None,
    )
    defaults.update(overrides)
    return defaults


class TestListOrders:
    async def test_happy_path_defaults_to_all_status(
        self, client, patch_brokerage, alpaca_mock
    ):
        alpaca_mock.list_orders.return_value = [
            _make_order(),
            _make_order(id="ord_2", status="canceled"),
        ]

        response = await client.get("/v1/brokerage/orders")

        assert response.status_code == 200
        body = response.json()
        assert len(body["orders"]) == 2
        assert body["orders"][0]["symbol"] == "AAPL"
        assert "account_id" not in body["orders"][0]

        alpaca_mock.list_orders.assert_awaited_once()
        kwargs = alpaca_mock.list_orders.await_args.kwargs
        assert kwargs["status"] == "all"
        assert kwargs["direction"] == "desc"
        assert kwargs["limit"] == 100

    async def test_passes_filters_through(self, client, patch_brokerage, alpaca_mock):
        response = await client.get(
            "/v1/brokerage/orders",
            params={
                "status": "closed",
                "side": "buy",
                "symbols": "AAPL,TSLA",
                "limit": 50,
            },
        )

        assert response.status_code == 200
        kwargs = alpaca_mock.list_orders.await_args.kwargs
        assert kwargs["status"] == "closed"
        assert kwargs["side"] == "buy"
        assert kwargs["symbols"] == "AAPL,TSLA"
        assert kwargs["limit"] == 50

    async def test_invalid_status_rejected_by_query_validation(self, client, patch_brokerage):
        response = await client.get("/v1/brokerage/orders", params={"status": "bogus"})
        assert response.status_code == 422

    async def test_invalid_side_rejected_by_query_validation(self, client, patch_brokerage):
        response = await client.get("/v1/brokerage/orders", params={"side": "bogus"})
        assert response.status_code == 422

    @pytest.mark.parametrize("limit", [0, 501, -1])
    async def test_limit_out_of_range_rejected(self, client, patch_brokerage, limit):
        response = await client.get("/v1/brokerage/orders", params={"limit": limit})
        assert response.status_code == 422

    async def test_alpaca_unavailable_returns_503(
        self, client, patch_brokerage, alpaca_mock
    ):
        alpaca_mock.list_orders.side_effect = AlpacaBrokerUnavailableError("upstream down")

        response = await client.get("/v1/brokerage/orders")

        assert response.status_code == 503
        assert response.json()["code"] == "ALPACA_UNAVAILABLE"

    async def test_alpaca_error_returns_422(
        self, client, patch_brokerage, alpaca_mock
    ):
        alpaca_mock.list_orders.side_effect = AlpacaBrokerError(
            status_code=400, message="bad params", detail={"reason": "x"}
        )

        response = await client.get("/v1/brokerage/orders")

        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "ALPACA_ERROR"
        assert body["error"] == "bad params"

    async def test_empty_orders_returns_empty_list(
        self, client, patch_brokerage, alpaca_mock
    ):
        alpaca_mock.list_orders.return_value = []

        response = await client.get("/v1/brokerage/orders")

        assert response.status_code == 200
        assert response.json() == {"orders": []}

    async def test_all_records_malformed_logs_aggregate_error(
        self, client, patch_brokerage, alpaca_mock, caplog
    ):
        # Every record missing the required `symbol` field — they all drop and
        # the response is an empty list. The service should emit a single
        # error-level "all dropped" log so this surfaces in ops as one alert
        # instead of N per-record warnings.
        alpaca_mock.list_orders.return_value = [
            {"id": "ord_1", "side": "buy", "status": "filled"},
            {"id": "ord_2", "side": "sell", "status": "canceled"},
        ]

        with caplog.at_level("ERROR", logger="app.services.brokerage"):
            response = await client.get("/v1/brokerage/orders")

        assert response.status_code == 200
        assert response.json() == {"orders": []}
        error_messages = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
        assert any("alpaca_order_malformed_all_dropped" in m for m in error_messages)

    async def test_no_brokerage_returns_404(self, client, patch_brokerage):
        patch_brokerage.return_value = None

        response = await client.get("/v1/brokerage/orders")

        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"

    async def test_non_active_brokerage_still_serves(
        self, client, patch_brokerage, brokerage, alpaca_mock
    ):
        # Read-only views work for any non-closed account. Local status often
        # lags Alpaca (APPROVED here, ACTIVE upstream) and we don't want to
        # 404 the trade-history screen during that window.
        brokerage.account_status = "APPROVED"

        response = await client.get("/v1/brokerage/orders")

        assert response.status_code == 200
        alpaca_mock.list_orders.assert_awaited_once()

    async def test_closed_brokerage_returns_404(self, client, patch_brokerage, brokerage):
        brokerage.account_status = "ACCOUNT_CLOSED"

        response = await client.get("/v1/brokerage/orders")

        assert response.status_code == 404

    async def test_malformed_order_skipped(self, client, patch_brokerage, alpaca_mock):
        # Missing `symbol` (required) — that one should drop, the well-formed
        # order should still come through.
        alpaca_mock.list_orders.return_value = [
            {"id": "ord_bad", "side": "buy", "status": "filled"},
            _make_order(),
        ]

        response = await client.get("/v1/brokerage/orders")

        assert response.status_code == 200
        body = response.json()
        assert len(body["orders"]) == 1
        assert body["orders"][0]["id"] == "ord_1"


class TestListPositions:
    async def test_happy_path(self, client, patch_brokerage, alpaca_mock):
        alpaca_mock.list_positions.return_value = [
            {
                "symbol": "AAPL",
                "asset_class": "us_equity",
                "qty": "10",
                "market_value": "1800.00",
                "cost_basis": "1500.00",  # extra Alpaca field, dropped
            }
        ]

        response = await client.get("/v1/brokerage/positions")

        assert response.status_code == 200
        body = response.json()
        assert body["positions"] == [
            {
                "symbol": "AAPL",
                "asset_class": "us_equity",
                "qty": "10",
                "market_value": "1800.00",
            }
        ]

    async def test_no_brokerage_returns_404(self, client, patch_brokerage):
        patch_brokerage.return_value = None
        response = await client.get("/v1/brokerage/positions")
        assert response.status_code == 404

    async def test_malformed_position_skipped(
        self, client, patch_brokerage, alpaca_mock
    ):
        # Missing the required `symbol` field — that one drops, the well-formed
        # one comes through.
        alpaca_mock.list_positions.return_value = [
            {"asset_class": "us_equity", "qty": "1"},
            {"symbol": "AAPL", "asset_class": "us_equity", "qty": "10", "market_value": "1800.00"},
        ]

        response = await client.get("/v1/brokerage/positions")

        assert response.status_code == 200
        body = response.json()
        assert len(body["positions"]) == 1
        assert body["positions"][0]["symbol"] == "AAPL"

    async def test_alpaca_unavailable_returns_503(
        self, client, patch_brokerage, alpaca_mock
    ):
        alpaca_mock.list_positions.side_effect = AlpacaBrokerUnavailableError("upstream down")

        response = await client.get("/v1/brokerage/positions")

        assert response.status_code == 503
        assert response.json()["code"] == "ALPACA_UNAVAILABLE"


# ---------------------------------------------------------------------------
# /v1/brokerage/cash-interest
# ---------------------------------------------------------------------------


CASH_ENROLLED_AT = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


def _make_cash_brokerage(
    *,
    sweep_status: str | None = "ACTIVE",
    sweep_enrolled_at: datetime | None = CASH_ENROLLED_AT,
    account_status: str = "ACTIVE",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        alpaca_account_id="alpaca_acc_42",
        account_status=account_status,
        sweep_status=sweep_status,
        sweep_enrolled_at=sweep_enrolled_at,
    )


@pytest.fixture
def patch_cash_brokerage(mocker):
    """Patch the gate used by CashInterestService and return a setter.

    Tests call `patch_cash_brokerage(_make_cash_brokerage(...))` for the variant
    they need rather than mutating a shared fixture in place.
    """

    def _set(brokerage):
        return mocker.patch(
            "app.services.brokerage.BrokerageAccountRepository.get_by_user_id",
            new_callable=AsyncMock,
            return_value=brokerage,
        )

    return _set


@pytest.fixture
def patch_apr_tier_name(monkeypatch):
    """Match the APR tier name to what the mocked Alpaca response returns."""
    monkeypatch.setattr(settings, "alpaca_apr_tier_name", "standard")


class TestGetCashInterest:
    async def test_active_sweep_populates_all_fields(
        self,
        client,
        patch_cash_brokerage,
        patch_apr_tier_name,
        alpaca_mock,
    ):
        patch_cash_brokerage(_make_cash_brokerage())
        alpaca_mock.get_trading_account.return_value = {
            "cash": "2412.08",
            "buying_power": "2412.08",
            "pending_transfer_in": "100.00",
        }
        today = datetime.now(timezone.utc).date()
        first_of_month = today.replace(day=1).isoformat()
        alpaca_mock.get_eod_cash_interest.return_value = [
            {"date": first_of_month, "account_accrued_interest": "1.50"},
            {"date": first_of_month, "account_accrued_interest": "2.00"},
            {"date": first_of_month, "account_accrued_interest": "2.93"},
        ]
        alpaca_mock.get_apr_tiers.return_value = {
            "apr_tiers": [{"name": "standard", "account_rate_bps": 425}]
        }
        alpaca_mock.get_interest_activities.return_value = [
            {"activity_sub_type": "SWP", "net_amount": "20.00", "qty": "20.00"},
            {"activity_sub_type": "SWP", "net_amount": "15.44", "qty": "15.44"},
        ]

        response = await client.get("/v1/brokerage/cash-interest")

        assert response.status_code == 200
        body = response.json()
        assert body["balance"] == "2412.08"
        assert body["buying_power"] == "2412.08"
        assert body["pending_deposits"] == "100.00"
        assert body["apy"] == "0.0425"
        assert body["this_month_earned"] == "6.43"
        assert body["days_accrued"] == 3
        # Per spec: lifetime = realized SWP (35.44) + current month accrual (6.43).
        assert body["lifetime_earned"] == "41.87"
        assert body["lifetime_since"] == CASH_ENROLLED_AT.isoformat().replace("+00:00", "Z")
        assert body["interest_paid_out"] == "monthly"
        assert body["fdic_insured_limit"] == "2500000"
        assert body["sweep_status"] == "ACTIVE"

    async def test_no_sweep_returns_zeros(
        self, client, patch_cash_brokerage, alpaca_mock
    ):
        patch_cash_brokerage(
            _make_cash_brokerage(sweep_status=None, sweep_enrolled_at=None)
        )
        alpaca_mock.get_trading_account.return_value = {
            "cash": "150.00",
            "buying_power": "150.00",
            "pending_transfer_in": "0",
        }

        response = await client.get("/v1/brokerage/cash-interest")

        assert response.status_code == 200
        body = response.json()
        assert body["balance"] == "150.00"
        assert body["buying_power"] == "150.00"
        assert body["this_month_earned"] == "0.00"
        assert body["days_accrued"] == 0
        assert body["lifetime_earned"] == "0.00"
        assert body["apy"] == "0.0000"
        assert body["lifetime_since"] is None
        assert body["sweep_status"] is None
        # Interest endpoints must not be hit when there's no enrollment.
        alpaca_mock.get_eod_cash_interest.assert_not_called()
        alpaca_mock.get_apr_tiers.assert_not_called()
        alpaca_mock.get_interest_activities.assert_not_called()

    async def test_no_brokerage_returns_404(self, client, patch_cash_brokerage):
        patch_cash_brokerage(None)

        response = await client.get("/v1/brokerage/cash-interest")

        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"

    async def test_closed_brokerage_returns_404(
        self, client, patch_cash_brokerage
    ):
        patch_cash_brokerage(_make_cash_brokerage(account_status="ACCOUNT_CLOSED"))

        response = await client.get("/v1/brokerage/cash-interest")

        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"

    async def test_pending_brokerage_no_sweep_returns_zero_shape(
        self, client, patch_cash_brokerage, alpaca_mock
    ):
        # Freshly-onboarded user: account row exists but isn't ACTIVE yet and
        # sweep is not enrolled. Read-only views should still surface balance.
        patch_cash_brokerage(
            _make_cash_brokerage(
                account_status="SUBMITTED", sweep_status=None, sweep_enrolled_at=None
            )
        )
        alpaca_mock.get_trading_account.return_value = {
            "cash": "0", "buying_power": "0", "pending_transfer_in": "0",
        }

        response = await client.get("/v1/brokerage/cash-interest")

        assert response.status_code == 200
        body = response.json()
        assert body["sweep_status"] is None
        assert body["lifetime_earned"] == "0.00"
        alpaca_mock.get_eod_cash_interest.assert_not_called()

    async def test_eod_failure_degrades_gracefully(
        self,
        client,
        patch_cash_brokerage,
        patch_apr_tier_name,
        alpaca_mock,
    ):
        patch_cash_brokerage(_make_cash_brokerage())
        alpaca_mock.get_trading_account.return_value = {
            "cash": "500.00",
            "buying_power": "500.00",
            "pending_transfer_in": "0",
        }
        alpaca_mock.get_eod_cash_interest.side_effect = AlpacaBrokerError(
            status_code=500, message="reporting offline"
        )
        alpaca_mock.get_apr_tiers.return_value = {
            "apr_tiers": [{"name": "standard", "account_rate_bps": 425}]
        }
        alpaca_mock.get_interest_activities.return_value = []

        response = await client.get("/v1/brokerage/cash-interest")

        assert response.status_code == 200
        body = response.json()
        # Balance/APY survive even though EOD reporting is down.
        assert body["balance"] == "500.00"
        assert body["apy"] == "0.0425"
        assert body["this_month_earned"] == "0.00"
        assert body["days_accrued"] == 0
        # No realized SWP and no EOD → lifetime degrades to 0.
        assert body["lifetime_earned"] == "0.00"

    async def test_trading_account_unavailable_returns_503(
        self, client, patch_cash_brokerage, alpaca_mock
    ):
        patch_cash_brokerage(_make_cash_brokerage())
        alpaca_mock.get_trading_account.side_effect = AlpacaBrokerUnavailableError(
            "upstream down"
        )

        response = await client.get("/v1/brokerage/cash-interest")

        assert response.status_code == 503
        assert response.json()["code"] == "ALPACA_UNAVAILABLE"
