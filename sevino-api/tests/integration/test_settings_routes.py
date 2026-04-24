"""Integration tests for /v1/settings/* routes."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.auth import get_current_user
from app.database import get_db
from app.exceptions import register_exception_handlers
from app.routes.settings import get_alpaca, router as settings_router

TEST_USER_ID = str(uuid.uuid4())


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(settings_router, prefix="/v1/settings", tags=["settings"])
    register_exception_handlers(app)
    return app


@pytest.fixture
def alpaca_mock() -> AsyncMock:
    svc = AsyncMock()
    svc.get_trading_account.return_value = {
        "id": "alpaca_acc_42",
        "equity": "10234.56",
        "cash": "1234.56",
        "buying_power": "2469.12",
        "portfolio_value": "10234.56",
    }
    return svc


@pytest.fixture
def brokerage():
    return SimpleNamespace(
        id=uuid.uuid4(),
        alpaca_account_id="alpaca_acc_42",
        account_status="ACTIVE",
    )


@pytest.fixture
def patch_repo(mocker, brokerage):
    return mocker.patch(
        "app.services.settings.BrokerageAccountRepository.get_by_user_id",
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

    app.dependency_overrides.clear()


@pytest.fixture
async def unauthenticated_client(alpaca_mock):
    app = _build_app()

    async def _override_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_alpaca] = lambda: alpaca_mock

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


class TestGetAccountValue:
    async def test_returns_mapped_alpaca_fields(
        self, client, patch_repo, alpaca_mock
    ):
        response = await client.get("/v1/settings/account-value")

        assert response.status_code == 200
        assert response.json() == {
            "equity": "10234.56",
            "cash": "1234.56",
            "buying_power": "2469.12",
            "portfolio_value": "10234.56",
        }
        alpaca_mock.get_trading_account.assert_awaited_once_with("alpaca_acc_42")

    async def test_missing_fields_surface_as_alpaca_error(
        self, client, patch_repo, alpaca_mock
    ):
        alpaca_mock.get_trading_account.return_value = {"equity": "100.00"}

        response = await client.get("/v1/settings/account-value")

        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "ALPACA_ERROR"
        assert set(body["detail"]["missing"]) == {
            "cash",
            "buying_power",
            "portfolio_value",
        }

    async def test_404_when_no_brokerage_account(
        self, client, patch_repo, alpaca_mock
    ):
        patch_repo.return_value = None

        response = await client.get("/v1/settings/account-value")

        assert response.status_code == 404
        body = response.json()
        assert body["code"] == "NOT_FOUND"
        assert body["detail"] == {"resource": "brokerage_account"}
        alpaca_mock.get_trading_account.assert_not_called()

    async def test_requires_auth(self, unauthenticated_client):
        response = await unauthenticated_client.get("/v1/settings/account-value")
        assert response.status_code == 401
        assert response.json()["code"] == "AUTHENTICATION_ERROR"
