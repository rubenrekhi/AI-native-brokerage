"""Integration tests for /v1/settings/* routes."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.auth import get_current_user
from app.database import get_db
from app.exceptions import register_exception_handlers
from app.routes.settings import (
    get_alpaca,
    get_supabase_admin,
    router as settings_router,
)

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
def supabase_admin_mock() -> AsyncMock:
    svc = AsyncMock()
    svc.delete_user.return_value = None
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
def db_mock() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
async def client(alpaca_mock, supabase_admin_mock, db_mock):
    app = _build_app()

    async def _override_db():
        yield db_mock

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: TEST_USER_ID
    app.dependency_overrides[get_alpaca] = lambda: alpaca_mock
    app.dependency_overrides[get_supabase_admin] = lambda: supabase_admin_mock

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def unauthenticated_client(alpaca_mock, supabase_admin_mock):
    app = _build_app()

    async def _override_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_alpaca] = lambda: alpaca_mock
    app.dependency_overrides[get_supabase_admin] = lambda: supabase_admin_mock

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


# ---------------------------------------------------------------------------
# DELETE /v1/settings/account
# ---------------------------------------------------------------------------


@pytest.fixture
def profile():
    return SimpleNamespace(id=uuid.UUID(TEST_USER_ID))


@pytest.fixture
def patch_profile_repo(mocker, profile):
    return mocker.patch(
        "app.services.settings.UserProfileRepository.get_by_id",
        new_callable=AsyncMock,
        return_value=profile,
    )


class TestDeleteAccount:
    async def test_full_cascade_happy_path(
        self,
        client,
        db_mock,
        profile,
        patch_repo,
        patch_profile_repo,
        supabase_admin_mock,
        alpaca_mock,
    ):
        response = await client.request(
            "DELETE",
            "/v1/settings/account",
            json={"confirmation": "DELETE"},
        )

        assert response.status_code == 204
        assert response.content == b""
        alpaca_mock.close_account.assert_awaited_once_with("alpaca_acc_42")
        db_mock.delete.assert_awaited_once_with(profile)
        db_mock.commit.assert_awaited()
        supabase_admin_mock.delete_user.assert_awaited_once_with(TEST_USER_ID)

    async def test_cascade_runs_in_order_alpaca_db_supabase(
        self,
        client,
        db_mock,
        patch_repo,
        patch_profile_repo,
        supabase_admin_mock,
        alpaca_mock,
    ):
        parent = Mock()
        parent.attach_mock(alpaca_mock.close_account, "alpaca_close")
        parent.attach_mock(db_mock.delete, "db_delete")
        parent.attach_mock(db_mock.commit, "db_commit")
        parent.attach_mock(supabase_admin_mock.delete_user, "supabase_delete")

        response = await client.request(
            "DELETE",
            "/v1/settings/account",
            json={"confirmation": "DELETE"},
        )

        assert response.status_code == 204
        call_names = [c[0] for c in parent.mock_calls]
        assert call_names.index("alpaca_close") < call_names.index("db_delete")
        assert call_names.index("db_delete") < call_names.index("db_commit")
        assert call_names.index("db_commit") < call_names.index("supabase_delete")

    @pytest.mark.parametrize(
        "terminal_status", ["REJECTED", "ACCOUNT_CLOSED"]
    )
    async def test_skips_alpaca_close_on_terminal_status(
        self,
        client,
        db_mock,
        patch_repo,
        patch_profile_repo,
        supabase_admin_mock,
        alpaca_mock,
        brokerage,
        terminal_status,
    ):
        brokerage.account_status = terminal_status

        response = await client.request(
            "DELETE",
            "/v1/settings/account",
            json={"confirmation": "DELETE"},
        )

        assert response.status_code == 204
        alpaca_mock.close_account.assert_not_called()
        db_mock.delete.assert_awaited_once()
        supabase_admin_mock.delete_user.assert_awaited_once_with(TEST_USER_ID)

    @pytest.mark.parametrize(
        "open_status",
        ["APPROVED", "ACTION_REQUIRED", "SUBMITTED", "APPROVAL_PENDING"],
    )
    async def test_closes_alpaca_on_non_terminal_non_active_statuses(
        self,
        client,
        db_mock,
        patch_repo,
        patch_profile_repo,
        supabase_admin_mock,
        alpaca_mock,
        brokerage,
        open_status,
    ):
        brokerage.account_status = open_status

        response = await client.request(
            "DELETE",
            "/v1/settings/account",
            json={"confirmation": "DELETE"},
        )

        assert response.status_code == 204
        alpaca_mock.close_account.assert_awaited_once_with("alpaca_acc_42")

    async def test_skips_alpaca_close_when_no_brokerage(
        self,
        client,
        db_mock,
        patch_repo,
        patch_profile_repo,
        supabase_admin_mock,
        alpaca_mock,
    ):
        patch_repo.return_value = None

        response = await client.request(
            "DELETE",
            "/v1/settings/account",
            json={"confirmation": "DELETE"},
        )

        assert response.status_code == 204
        alpaca_mock.close_account.assert_not_called()
        db_mock.delete.assert_awaited_once()

    async def test_rejects_missing_confirmation(self, client):
        response = await client.request(
            "DELETE", "/v1/settings/account", json={}
        )
        assert response.status_code == 422

    async def test_rejects_wrong_confirmation(self, client):
        response = await client.request(
            "DELETE",
            "/v1/settings/account",
            json={"confirmation": "delete"},
        )
        assert response.status_code == 422

    async def test_404_when_profile_missing(
        self, client, patch_profile_repo, alpaca_mock, supabase_admin_mock
    ):
        patch_profile_repo.return_value = None

        response = await client.request(
            "DELETE",
            "/v1/settings/account",
            json={"confirmation": "DELETE"},
        )

        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"
        alpaca_mock.close_account.assert_not_called()
        supabase_admin_mock.delete_user.assert_not_called()

    async def test_alpaca_failure_halts_before_db_delete(
        self,
        client,
        db_mock,
        patch_repo,
        patch_profile_repo,
        supabase_admin_mock,
        alpaca_mock,
    ):
        from app.services.alpaca_broker import AlpacaBrokerError

        alpaca_mock.close_account.side_effect = AlpacaBrokerError(
            status_code=400, message="cannot close"
        )

        response = await client.request(
            "DELETE",
            "/v1/settings/account",
            json={"confirmation": "DELETE"},
        )

        assert response.status_code == 422
        assert response.json()["code"] == "ALPACA_ERROR"
        db_mock.delete.assert_not_called()
        supabase_admin_mock.delete_user.assert_not_called()

    async def test_supabase_failure_returns_204_and_logs_orphan(
        self,
        client,
        db_mock,
        mocker,
        patch_repo,
        patch_profile_repo,
        supabase_admin_mock,
        alpaca_mock,
    ):
        from app.services.supabase_admin import SupabaseAdminUnavailableError

        supabase_admin_mock.delete_user.side_effect = SupabaseAdminUnavailableError(
            "refused"
        )
        capture = mocker.patch("app.services.settings.sentry_sdk.capture_exception")

        response = await client.request(
            "DELETE",
            "/v1/settings/account",
            json={"confirmation": "DELETE"},
        )

        # DB commit already happened — the profile is gone, so we return 204
        # and leave the auth.users orphan to out-of-band reconciliation.
        assert response.status_code == 204
        db_mock.commit.assert_awaited()
        capture.assert_called_once()

    async def test_requires_auth(self, unauthenticated_client):
        response = await unauthenticated_client.request(
            "DELETE",
            "/v1/settings/account",
            json={"confirmation": "DELETE"},
        )
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# SupabaseAdminService.delete_user
# ---------------------------------------------------------------------------


class TestSupabaseAdminServiceDeleteUser:
    @pytest.fixture
    def _svc_factory(self, mocker):
        """Return a factory that builds a SupabaseAdminService with a
        MockTransport-backed client, so tests don't need to monkeypatch
        httpx.AsyncClient globally."""
        from app.config import settings as app_settings
        from app.services.supabase_admin import SupabaseAdminService

        def _factory(
            handler, *, service_role_key: str = "service-role-token"
        ) -> SupabaseAdminService:
            mocker.patch.object(app_settings, "supabase_url", "https://sb.example")
            mocker.patch.object(
                app_settings, "supabase_service_role_key", service_role_key
            )
            svc = SupabaseAdminService()
            svc._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            return svc

        return _factory

    async def test_sends_admin_delete_with_auth_headers(self, _svc_factory):
        captured: dict = {}

        def _handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            return httpx.Response(204)

        svc = _svc_factory(_handler)
        await svc.delete_user("abc-123")

        assert captured["method"] == "DELETE"
        assert captured["url"] == "https://sb.example/auth/v1/admin/users/abc-123"
        assert captured["headers"]["authorization"] == "Bearer service-role-token"
        assert captured["headers"]["apikey"] == "service-role-token"

    async def test_treats_404_as_success(self, _svc_factory):
        svc = _svc_factory(lambda req: httpx.Response(404))
        await svc.delete_user("abc-123")

    async def test_raises_supabase_admin_error_on_error_status(self, _svc_factory):
        from app.services.supabase_admin import SupabaseAdminError

        svc = _svc_factory(lambda req: httpx.Response(500))
        with pytest.raises(SupabaseAdminError) as exc_info:
            await svc.delete_user("abc-123")
        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == {"status": 500}

    async def test_raises_unavailable_when_service_role_key_missing(
        self, _svc_factory
    ):
        from app.services.supabase_admin import SupabaseAdminUnavailableError

        svc = _svc_factory(lambda req: httpx.Response(204), service_role_key="")
        with pytest.raises(SupabaseAdminUnavailableError):
            await svc.delete_user("abc-123")

    async def test_raises_unavailable_on_network_error(self, _svc_factory):
        from app.services.supabase_admin import SupabaseAdminUnavailableError

        def _boom(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        svc = _svc_factory(_boom)
        with pytest.raises(SupabaseAdminUnavailableError):
            await svc.delete_user("abc-123")
