"""Integration tests for /v1/settings/* routes."""

import uuid
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, Mock

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
# GET /v1/settings/documents + /documents/{id}/download
# ---------------------------------------------------------------------------


class TestListDocuments:
    async def test_returns_mapped_documents(
        self, client, patch_repo, alpaca_mock
    ):
        alpaca_mock.list_documents.return_value = [
            {
                "id": "doc-1",
                "type": "account_statement",
                "date": "2026-03-31",
                "name": "March Statement",
            },
            {
                "id": "doc-2",
                "type": "tax_1099",
                "date": "2026-02-15",
            },
        ]

        response = await client.get("/v1/settings/documents")

        assert response.status_code == 200
        assert response.json() == {
            "documents": [
                {
                    "id": "doc-1",
                    "type": "account_statement",
                    "date": "2026-03-31",
                    "name": "March Statement",
                },
                {
                    "id": "doc-2",
                    "type": "tax_1099",
                    "date": "2026-02-15",
                    "name": None,
                },
            ]
        }
        alpaca_mock.list_documents.assert_awaited_once_with(
            "alpaca_acc_42", document_type=None, start=None, end=None
        )

    async def test_blank_name_normalized_to_null(
        self, client, patch_repo, alpaca_mock
    ):
        alpaca_mock.list_documents.return_value = [
            {"id": "doc-3", "type": "tax_1099", "date": "2026-02-15", "name": "   "},
        ]

        response = await client.get("/v1/settings/documents")

        assert response.status_code == 200
        assert response.json()["documents"][0]["name"] is None

    async def test_skips_malformed_document_without_500(
        self, client, patch_repo, alpaca_mock
    ):
        alpaca_mock.list_documents.return_value = [
            {"id": "doc-1", "type": "account_statement", "date": "2026-03-31"},
            {"type": "account_statement", "date": "2026-02-28"},  # missing id
        ]

        response = await client.get("/v1/settings/documents")

        assert response.status_code == 200
        assert [d["id"] for d in response.json()["documents"]] == ["doc-1"]

    async def test_forwards_type_filter(self, client, patch_repo, alpaca_mock):
        alpaca_mock.list_documents.return_value = []

        response = await client.get(
            "/v1/settings/documents",
            params={"type": "tax_1099", "start": "2026-01-01", "end": "2026-12-31"},
        )

        assert response.status_code == 200
        alpaca_mock.list_documents.assert_awaited_once_with(
            "alpaca_acc_42",
            document_type="tax_1099",
            start="2026-01-01",
            end="2026-12-31",
        )

    async def test_rejects_malformed_type_filter(self, client, patch_repo):
        response = await client.get(
            "/v1/settings/documents", params={"type": "Bad Value!"}
        )
        assert response.status_code == 422

    async def test_rejects_malformed_date_filter(self, client, patch_repo):
        response = await client.get(
            "/v1/settings/documents", params={"start": "not-a-date"}
        )
        assert response.status_code == 422

    async def test_404_when_no_brokerage(
        self, client, patch_repo, alpaca_mock
    ):
        patch_repo.return_value = None

        response = await client.get("/v1/settings/documents")

        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"
        alpaca_mock.list_documents.assert_not_called()

    async def test_requires_auth(self, unauthenticated_client):
        response = await unauthenticated_client.get("/v1/settings/documents")
        assert response.status_code == 401


DOC_UUID = "11111111-2222-3333-4444-555555555555"


class TestDownloadDocument:
    async def test_streams_pdf_bytes(self, client, patch_repo, alpaca_mock):
        pdf_chunks = [b"%PDF-1.4\n", b"fake"]

        async def _iter():
            for c in pdf_chunks:
                yield c

        alpaca_mock.stream_document.return_value = _iter()

        response = await client.get(f"/v1/settings/documents/{DOC_UUID}/download")

        assert response.status_code == 200
        assert response.content == b"".join(pdf_chunks)
        assert response.headers["content-type"] == "application/pdf"
        assert f'filename="{DOC_UUID}.pdf"' in response.headers["content-disposition"]
        alpaca_mock.stream_document.assert_awaited_once_with(
            "alpaca_acc_42", DOC_UUID
        )

    async def test_404_surfaces_before_streaming(
        self, client, patch_repo, alpaca_mock
    ):
        """Alpaca 404 must reach the client as 404, not a truncated 200."""
        from app.exceptions import NotFoundError

        alpaca_mock.stream_document.side_effect = NotFoundError(
            "Alpaca resource not found", resource="alpaca_account"
        )

        response = await client.get(f"/v1/settings/documents/{DOC_UUID}/download")

        assert response.status_code == 404

    async def test_rejects_non_uuid_document_id(self, client, patch_repo):
        response = await client.get("/v1/settings/documents/not-a-uuid/download")
        assert response.status_code == 422

    async def test_404_when_no_brokerage(
        self, client, patch_repo, alpaca_mock
    ):
        patch_repo.return_value = None

        response = await client.get(f"/v1/settings/documents/{DOC_UUID}/download")

        assert response.status_code == 404
        alpaca_mock.stream_document.assert_not_called()

    async def test_requires_auth(self, unauthenticated_client):
        response = await unauthenticated_client.get(
            f"/v1/settings/documents/{DOC_UUID}/download"
        )
        assert response.status_code == 401


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


class TestUpdateProfile:
    @pytest.fixture
    def patch_update_fields(self, mocker):
        return mocker.patch(
            "app.services.settings.UserProfileRepository.update_fields",
            new_callable=AsyncMock,
        )

    @pytest.fixture
    def patch_get_profile(self, mocker):
        """Stub the refreshed-profile read; shape is asserted by other tests."""
        from datetime import datetime, timezone

        from app.schemas.onboarding import ProfileData
        from app.schemas.settings import SettingsProfileResponse

        response = SettingsProfileResponse(
            profile=ProfileData(first_name="Ada", last_name="Lovelace"),
            financial_profile=None,
            brokerage=None,
            linked_accounts=[],
            member_since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        return mocker.patch(
            "app.services.settings.SettingsService.get_profile",
            new_callable=AsyncMock,
            return_value=response,
        )

    async def test_updates_db_and_syncs_alpaca_when_active(
        self,
        client,
        patch_repo,
        patch_update_fields,
        patch_get_profile,
        alpaca_mock,
    ):
        body = {
            "first_name": "Ada",
            "middle_name": "Augusta",
            "last_name": "Lovelace",
            "phone_number": "+15551112222",
            "street_address": ["1 Analytical Way"],
            "city": "London",
            "state": "LN",
            "postal_code": "10001",
        }

        response = await client.patch("/v1/settings/profile", json=body)

        assert response.status_code == 200
        patch_update_fields.assert_awaited_once_with(
            ANY, uuid.UUID(TEST_USER_ID), **body
        )
        alpaca_mock.update_account.assert_awaited_once_with(
            "alpaca_acc_42",
            {
                "contact": {
                    "phone_number": "+15551112222",
                    "street_address": ["1 Analytical Way"],
                    "city": "London",
                    "state": "LN",
                    "postal_code": "10001",
                },
                "identity": {
                    "given_name": "Ada",
                    "middle_name": "Augusta",
                    "family_name": "Lovelace",
                },
            },
        )
        patch_get_profile.assert_awaited_once()

    async def test_sends_only_submitted_fields_to_alpaca(
        self,
        client,
        patch_repo,
        patch_update_fields,
        patch_get_profile,
        alpaca_mock,
    ):
        response = await client.patch(
            "/v1/settings/profile", json={"city": "Paris"}
        )

        assert response.status_code == 200
        alpaca_mock.update_account.assert_awaited_once_with(
            "alpaca_acc_42", {"contact": {"city": "Paris"}}
        )

    async def test_identity_only_update_omits_contact_section(
        self,
        client,
        patch_repo,
        patch_update_fields,
        patch_get_profile,
        alpaca_mock,
    ):
        response = await client.patch(
            "/v1/settings/profile", json={"first_name": "Ada"}
        )

        assert response.status_code == 200
        alpaca_mock.update_account.assert_awaited_once_with(
            "alpaca_acc_42", {"identity": {"given_name": "Ada"}}
        )

    async def test_preferred_name_does_not_hit_alpaca(
        self,
        client,
        patch_repo,
        patch_update_fields,
        patch_get_profile,
        alpaca_mock,
    ):
        response = await client.patch(
            "/v1/settings/profile", json={"preferred_name": "Addie"}
        )

        assert response.status_code == 200
        patch_update_fields.assert_awaited_once_with(
            ANY, uuid.UUID(TEST_USER_ID), preferred_name="Addie"
        )
        alpaca_mock.update_account.assert_not_called()

    @pytest.mark.parametrize(
        "non_active_status",
        ["SUBMITTED", "APPROVED", "ACTION_REQUIRED", "ACCOUNT_CLOSED", "REJECTED"],
    )
    async def test_skips_alpaca_when_brokerage_not_active(
        self,
        client,
        patch_repo,
        brokerage,
        patch_update_fields,
        patch_get_profile,
        alpaca_mock,
        non_active_status,
    ):
        brokerage.account_status = non_active_status

        response = await client.patch(
            "/v1/settings/profile", json={"city": "Paris"}
        )

        assert response.status_code == 200
        patch_update_fields.assert_awaited_once()
        alpaca_mock.update_account.assert_not_called()

    async def test_skips_alpaca_when_no_brokerage(
        self,
        client,
        patch_repo,
        patch_update_fields,
        patch_get_profile,
        alpaca_mock,
    ):
        patch_repo.return_value = None

        response = await client.patch(
            "/v1/settings/profile", json={"city": "Paris"}
        )

        assert response.status_code == 200
        alpaca_mock.update_account.assert_not_called()

    async def test_empty_body_returns_422(self, client):
        response = await client.patch("/v1/settings/profile", json={})
        assert response.status_code == 422

    async def test_404_when_profile_missing(
        self,
        client,
        patch_repo,
        patch_update_fields,
        alpaca_mock,
    ):
        from app.exceptions import NotFoundError

        patch_update_fields.side_effect = NotFoundError(
            "User profile not found", resource="user_profile"
        )

        response = await client.patch(
            "/v1/settings/profile", json={"city": "Paris"}
        )

        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"
        alpaca_mock.update_account.assert_not_called()

    async def test_alpaca_failure_surfaces_error(
        self,
        client,
        patch_repo,
        patch_update_fields,
        patch_get_profile,
        alpaca_mock,
    ):
        from app.services.alpaca_broker import AlpacaBrokerError

        alpaca_mock.update_account.side_effect = AlpacaBrokerError(
            status_code=400, message="bad contact"
        )

        response = await client.patch(
            "/v1/settings/profile", json={"city": "Paris"}
        )

        assert response.status_code == 422
        assert response.json()["code"] == "ALPACA_ERROR"
        patch_get_profile.assert_not_called()

    async def test_alpaca_unavailable_surfaces_503(
        self,
        client,
        patch_repo,
        patch_update_fields,
        patch_get_profile,
        alpaca_mock,
    ):
        from app.services.alpaca_broker import AlpacaBrokerUnavailableError

        alpaca_mock.update_account.side_effect = AlpacaBrokerUnavailableError(
            "upstream timeout"
        )

        response = await client.patch(
            "/v1/settings/profile", json={"city": "Paris"}
        )

        assert response.status_code == 503
        patch_get_profile.assert_not_called()

    async def test_requires_auth(self, unauthenticated_client):
        response = await unauthenticated_client.patch(
            "/v1/settings/profile", json={"city": "Paris"}
        )
        assert response.status_code == 401


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
# DELETE /v1/settings/brokerage-account
# ---------------------------------------------------------------------------


class TestCloseBrokerageAccount:
    @pytest.fixture(autouse=True)
    def _default_alpaca_state(self, alpaca_mock):
        alpaca_mock.list_positions.return_value = []
        alpaca_mock.list_transfers.return_value = []
        alpaca_mock.get_trading_account.return_value = {
            "id": "alpaca_acc_42",
            "cash": "0",
            "equity": "0",
            "buying_power": "0",
            "portfolio_value": "0",
        }
        alpaca_mock.close_account.return_value = {"id": "alpaca_acc_42"}

    @pytest.fixture
    def patch_update_status(self, mocker):
        return mocker.patch(
            "app.services.settings.BrokerageAccountRepository.update_status",
            new_callable=AsyncMock,
        )

    async def test_happy_path_closes_and_updates_status(
        self,
        client,
        db_mock,
        patch_repo,
        patch_update_status,
        alpaca_mock,
        brokerage,
    ):
        response = await client.delete("/v1/settings/brokerage-account")

        assert response.status_code == 204
        assert response.content == b""
        alpaca_mock.list_positions.assert_awaited_once_with("alpaca_acc_42")
        alpaca_mock.list_transfers.assert_awaited_once_with("alpaca_acc_42")
        alpaca_mock.close_account.assert_awaited_once_with("alpaca_acc_42")
        patch_update_status.assert_awaited_once_with(
            ANY, brokerage.id, "ACCOUNT_CLOSED"
        )
        db_mock.commit.assert_awaited()

    async def test_404_when_no_brokerage_account(
        self, client, patch_repo, alpaca_mock, patch_update_status
    ):
        patch_repo.return_value = None

        response = await client.delete("/v1/settings/brokerage-account")

        assert response.status_code == 404
        body = response.json()
        assert body["code"] == "NOT_FOUND"
        assert body["detail"] == {"resource": "brokerage_account"}
        alpaca_mock.list_positions.assert_not_called()
        alpaca_mock.close_account.assert_not_called()
        patch_update_status.assert_not_called()

    @pytest.mark.parametrize(
        "non_active_status",
        ["SUBMITTED", "APPROVED", "ACTION_REQUIRED", "ACCOUNT_CLOSED", "REJECTED"],
    )
    async def test_404_when_brokerage_not_active(
        self,
        client,
        patch_repo,
        alpaca_mock,
        brokerage,
        patch_update_status,
        non_active_status,
    ):
        brokerage.account_status = non_active_status

        response = await client.delete("/v1/settings/brokerage-account")

        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"
        alpaca_mock.list_positions.assert_not_called()
        alpaca_mock.close_account.assert_not_called()
        patch_update_status.assert_not_called()

    async def test_409_when_open_positions_exist(
        self, client, patch_repo, alpaca_mock, patch_update_status
    ):
        alpaca_mock.list_positions.return_value = [
            {"symbol": "AAPL", "qty": "3"},
            {"symbol": "TSLA", "qty": "1"},
        ]

        response = await client.delete("/v1/settings/brokerage-account")

        assert response.status_code == 409
        body = response.json()
        assert body["code"] == "OPEN_POSITIONS"
        assert "Close all positions" in body["error"]
        assert body["detail"] == {"position_count": 2}
        alpaca_mock.list_transfers.assert_not_called()
        alpaca_mock.close_account.assert_not_called()
        patch_update_status.assert_not_called()

    @pytest.mark.parametrize(
        "pending_status",
        ["QUEUED", "APPROVAL_PENDING", "PENDING", "SENT_TO_CLEARING"],
    )
    async def test_409_when_pending_transfers_exist(
        self,
        client,
        patch_repo,
        alpaca_mock,
        patch_update_status,
        pending_status,
    ):
        alpaca_mock.list_transfers.return_value = [
            {"id": "t1", "status": pending_status},
            {"id": "t2", "status": "COMPLETE"},
        ]

        response = await client.delete("/v1/settings/brokerage-account")

        assert response.status_code == 409
        body = response.json()
        assert body["code"] == "PENDING_TRANSFERS"
        assert body["detail"] == {"pending_count": 1}
        alpaca_mock.close_account.assert_not_called()
        patch_update_status.assert_not_called()

    async def test_allows_close_when_only_settled_transfers(
        self, client, patch_repo, alpaca_mock, patch_update_status
    ):
        alpaca_mock.list_transfers.return_value = [
            {"id": "t1", "status": "COMPLETE"},
            {"id": "t2", "status": "CANCELED"},
            {"id": "t3", "status": "RETURNED"},
        ]

        response = await client.delete("/v1/settings/brokerage-account")

        assert response.status_code == 204
        alpaca_mock.close_account.assert_awaited_once_with("alpaca_acc_42")
        patch_update_status.assert_awaited_once()

    async def test_409_when_non_zero_cash_balance(
        self, client, patch_repo, alpaca_mock, patch_update_status
    ):
        alpaca_mock.get_trading_account.return_value = {
            "id": "alpaca_acc_42",
            "cash": "670.50",
            "equity": "670.50",
            "buying_power": "670.50",
            "portfolio_value": "670.50",
        }

        response = await client.delete("/v1/settings/brokerage-account")

        assert response.status_code == 409
        body = response.json()
        assert body["code"] == "NON_ZERO_BALANCE"
        assert "Withdraw" in body["error"]
        assert body["detail"] == {"cash_balance": "670.50"}
        alpaca_mock.close_account.assert_not_called()
        patch_update_status.assert_not_called()

    async def test_allows_close_when_cash_balance_is_zero_string_variants(
        self, client, patch_repo, alpaca_mock, patch_update_status
    ):
        alpaca_mock.get_trading_account.return_value = {
            "id": "alpaca_acc_42",
            "cash": "0.00",
        }

        response = await client.delete("/v1/settings/brokerage-account")

        assert response.status_code == 204
        alpaca_mock.close_account.assert_awaited_once_with("alpaca_acc_42")

    async def test_alpaca_close_failure_skips_status_update(
        self, client, patch_repo, alpaca_mock, patch_update_status
    ):
        from app.services.alpaca_broker import AlpacaBrokerError

        alpaca_mock.close_account.side_effect = AlpacaBrokerError(
            status_code=400, message="cannot close"
        )

        response = await client.delete("/v1/settings/brokerage-account")

        assert response.status_code == 422
        assert response.json()["code"] == "ALPACA_ERROR"
        patch_update_status.assert_not_called()

    @pytest.mark.parametrize(
        "cash_value",
        ["N/A", "unknown", ""],
    )
    async def test_502_when_cash_value_unparseable(
        self, client, patch_repo, alpaca_mock, patch_update_status, cash_value
    ):
        alpaca_mock.get_trading_account.return_value = {
            "id": "alpaca_acc_42",
            "cash": cash_value,
        }

        response = await client.delete("/v1/settings/brokerage-account")

        assert response.status_code == 422
        assert response.json()["code"] == "ALPACA_ERROR"
        alpaca_mock.close_account.assert_not_called()
        patch_update_status.assert_not_called()

    async def test_502_when_cash_field_missing(
        self, client, patch_repo, alpaca_mock, patch_update_status
    ):
        alpaca_mock.get_trading_account.return_value = {"id": "alpaca_acc_42"}

        response = await client.delete("/v1/settings/brokerage-account")

        assert response.status_code == 422
        assert response.json()["code"] == "ALPACA_ERROR"
        alpaca_mock.close_account.assert_not_called()
        patch_update_status.assert_not_called()

    async def test_requires_auth(self, unauthenticated_client):
        response = await unauthenticated_client.delete(
            "/v1/settings/brokerage-account"
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
