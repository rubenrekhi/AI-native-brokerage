"""Integration tests for GET /v1/brokerage/dividends."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.auth import get_current_user
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
    svc.get_dividend_activities.return_value = []
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


def _make_dividend(**overrides):
    defaults = dict(
        id="div_1",
        symbol="AAPL",
        net_amount="22.50",
        status="executed",
        created_at="2026-05-28T13:30:00Z",
        # Alpaca-internal fields that should be dropped at the boundary
        account_id="acc_42",
        activity_type="DIV",
        activity_sub_type="DIV",
        qty="10",
    )
    defaults.update(overrides)
    return defaults


class TestListDividends:
    async def test_happy_path(self, client, patch_brokerage, alpaca_mock):
        alpaca_mock.get_dividend_activities.return_value = [
            _make_dividend(),
            _make_dividend(id="div_2", symbol="MSFT", net_amount="15.75"),
        ]

        response = await client.get("/v1/brokerage/dividends")

        assert response.status_code == 200
        body = response.json()
        assert len(body["dividends"]) == 2
        assert body["dividends"][0] == {
            "id": "div_1",
            "symbol": "AAPL",
            "net_amount": "22.50",
            "status": "executed",
            "created_at": "2026-05-28T13:30:00Z",
        }
        # Alpaca-internal fields stripped at the boundary.
        assert "account_id" not in body["dividends"][0]
        assert "activity_type" not in body["dividends"][0]

        alpaca_mock.get_dividend_activities.assert_awaited_once_with(
            account_id="alpaca_acc_42"
        )

    async def test_empty_returns_empty_list(
        self, client, patch_brokerage, alpaca_mock
    ):
        alpaca_mock.get_dividend_activities.return_value = []

        response = await client.get("/v1/brokerage/dividends")

        assert response.status_code == 200
        assert response.json() == {"dividends": []}

    async def test_non_payment_records_filtered_out(
        self, client, patch_brokerage, alpaca_mock
    ):
        # Account History should only show "money in" lines. Withholdings
        # (DIVNRA/DIVTAX) and ADR pass-through fees (DIVFEE) ride along in the
        # DIV bucket with negative net_amount and must not appear as
        # "dividend payments". Zero-amount records also drop.
        alpaca_mock.get_dividend_activities.return_value = [
            _make_dividend(id="div_pay", symbol="AAPL", net_amount="22.50"),
            _make_dividend(
                id="div_nra",
                symbol="AAPL",
                net_amount="-6.75",
                activity_sub_type="DIVNRA",
            ),
            _make_dividend(
                id="div_fee",
                symbol="BABA",
                net_amount="-0.40",
                activity_sub_type="DIVFEE",
            ),
            _make_dividend(id="div_zero", symbol="TSLA", net_amount="0.00"),
        ]

        response = await client.get("/v1/brokerage/dividends")

        assert response.status_code == 200
        body = response.json()
        assert len(body["dividends"]) == 1
        assert body["dividends"][0]["id"] == "div_pay"

    async def test_limit_and_offset_slice_filtered_results(
        self, client, patch_brokerage, alpaca_mock
    ):
        # Verify pagination applies to the post-filter list, not the raw
        # Alpaca response — otherwise a page full of withholdings could
        # come back empty.
        alpaca_mock.get_dividend_activities.return_value = [
            _make_dividend(
                id="div_nra",
                net_amount="-6.75",
                activity_sub_type="DIVNRA",
            ),
            _make_dividend(id="div_1", net_amount="10.00"),
            _make_dividend(id="div_2", net_amount="20.00"),
            _make_dividend(id="div_3", net_amount="30.00"),
            _make_dividend(id="div_4", net_amount="40.00"),
        ]

        response = await client.get(
            "/v1/brokerage/dividends", params={"limit": 2, "offset": 1}
        )

        assert response.status_code == 200
        body = response.json()
        ids = [d["id"] for d in body["dividends"]]
        assert ids == ["div_2", "div_3"]

    @pytest.mark.parametrize(
        "params",
        [
            {"limit": 0},
            {"limit": 101},
            {"limit": -1},
            {"offset": -1},
        ],
    )
    async def test_invalid_pagination_rejected(
        self, client, patch_brokerage, params
    ):
        response = await client.get("/v1/brokerage/dividends", params=params)
        assert response.status_code == 422

    async def test_malformed_record_skipped(
        self, client, patch_brokerage, alpaca_mock
    ):
        # Missing the required `symbol` field — that one drops, the well-formed
        # one comes through.
        alpaca_mock.get_dividend_activities.return_value = [
            {"id": "div_bad", "net_amount": "5.00", "status": "executed"},
            _make_dividend(),
        ]

        response = await client.get("/v1/brokerage/dividends")

        assert response.status_code == 200
        body = response.json()
        assert len(body["dividends"]) == 1
        assert body["dividends"][0]["id"] == "div_1"

    async def test_all_records_malformed_logs_aggregate_error(
        self, client, patch_brokerage, alpaca_mock, caplog
    ):
        alpaca_mock.get_dividend_activities.return_value = [
            {"id": "div_a", "net_amount": "5.00", "status": "executed"},
            {"id": "div_b", "net_amount": "7.50", "status": "executed"},
        ]

        with caplog.at_level("ERROR", logger="app.services.brokerage"):
            response = await client.get("/v1/brokerage/dividends")

        assert response.status_code == 200
        assert response.json() == {"dividends": []}
        error_messages = [
            r.getMessage() for r in caplog.records if r.levelname == "ERROR"
        ]
        assert any(
            "alpaca_dividend_malformed_all_dropped" in m for m in error_messages
        )

    async def test_no_brokerage_returns_404(self, client, patch_brokerage):
        patch_brokerage.return_value = None

        response = await client.get("/v1/brokerage/dividends")

        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"

    async def test_closed_brokerage_returns_404(
        self, client, patch_brokerage, brokerage
    ):
        brokerage.account_status = "ACCOUNT_CLOSED"

        response = await client.get("/v1/brokerage/dividends")

        assert response.status_code == 404

    async def test_non_active_brokerage_still_serves(
        self, client, patch_brokerage, brokerage, alpaca_mock
    ):
        # Read-only views work for any non-closed account. Mirrors
        # /orders and /positions — local status often lags Alpaca and we
        # don't want to gate dividend history during the APPROVED→ACTIVE
        # window.
        brokerage.account_status = "APPROVED"

        response = await client.get("/v1/brokerage/dividends")

        assert response.status_code == 200
        alpaca_mock.get_dividend_activities.assert_awaited_once()

    async def test_alpaca_unavailable_returns_503(
        self, client, patch_brokerage, alpaca_mock
    ):
        alpaca_mock.get_dividend_activities.side_effect = (
            AlpacaBrokerUnavailableError("upstream down")
        )

        response = await client.get("/v1/brokerage/dividends")

        assert response.status_code == 503
        assert response.json()["code"] == "ALPACA_UNAVAILABLE"

    async def test_alpaca_error_returns_422(
        self, client, patch_brokerage, alpaca_mock
    ):
        alpaca_mock.get_dividend_activities.side_effect = AlpacaBrokerError(
            status_code=400, message="bad params", detail={"reason": "x"}
        )

        response = await client.get("/v1/brokerage/dividends")

        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "ALPACA_ERROR"
