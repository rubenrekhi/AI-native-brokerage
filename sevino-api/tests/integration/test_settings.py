"""Integration tests for /v1/settings endpoints against real local Postgres.

Requires: Docker + `make infra` + `make migrate`.
Skipped automatically if Postgres is unavailable.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.main import app
from app.repositories.ach_relationship import AchRelationshipRepository
from tests.integration.conftest import (
    TEST_API_KEY,
    TEST_USER_ID,
    _pg_available_sync,
)

pytestmark = pytest.mark.skipif(
    not _pg_available_sync,
    reason="Local Supabase Postgres not available (run `make infra`)",
)


# ---------------------------------------------------------------------------
# GET /v1/settings (user preferences)
# ---------------------------------------------------------------------------


class TestGetSettings:
    async def test_returns_defaults_when_no_row_exists(
        self, authenticated_db_client, db_session
    ):
        response = await authenticated_db_client.get("/v1/settings")
        assert response.status_code == 200
        assert response.json() == {
            "theme": "system",
            "text_size": "standard",
            "notifications_enabled": True,
            "ai_internet_access": True,
        }

        # Confirm GET did not persist a row (read must be safe/idempotent).
        row = await db_session.execute(
            text("SELECT COUNT(*) FROM user_settings WHERE user_id = :uid"),
            {"uid": uuid.UUID(TEST_USER_ID)},
        )
        assert row.scalar() == 0

    async def test_returns_persisted_values(
        self, authenticated_db_client, db_session
    ):
        await db_session.execute(
            text(
                "INSERT INTO user_settings "
                "(id, user_id, theme, text_size, notifications_enabled, ai_internet_access) "
                "VALUES (gen_random_uuid(), :uid, 'dark', 'large', false, false)"
            ),
            {"uid": uuid.UUID(TEST_USER_ID)},
        )
        await db_session.flush()

        response = await authenticated_db_client.get("/v1/settings")
        assert response.status_code == 200
        assert response.json() == {
            "theme": "dark",
            "text_size": "large",
            "notifications_enabled": False,
            "ai_internet_access": False,
        }

    async def test_unauthenticated_returns_401(self, db_session):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": TEST_API_KEY},
        ) as client:
            response = await client.get("/v1/settings")
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# PATCH /v1/settings
# ---------------------------------------------------------------------------


class TestPatchSettings:
    async def test_creates_row_on_first_patch(
        self, authenticated_db_client, db_session
    ):
        response = await authenticated_db_client.patch(
            "/v1/settings",
            json={"theme": "dark"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["theme"] == "dark"
        # Unprovided fields fall back to server defaults.
        assert body["text_size"] == "standard"
        assert body["notifications_enabled"] is True
        assert body["ai_internet_access"] is True

        row = await db_session.execute(
            text(
                "SELECT theme, text_size, notifications_enabled, ai_internet_access "
                "FROM user_settings WHERE user_id = :uid"
            ),
            {"uid": uuid.UUID(TEST_USER_ID)},
        )
        persisted = row.one()
        assert persisted.theme == "dark"
        assert persisted.text_size == "standard"

    async def test_partial_patch_leaves_other_fields_unchanged(
        self, authenticated_db_client, db_session
    ):
        await db_session.execute(
            text(
                "INSERT INTO user_settings "
                "(id, user_id, theme, text_size, notifications_enabled, ai_internet_access) "
                "VALUES (gen_random_uuid(), :uid, 'dark', 'large', false, false)"
            ),
            {"uid": uuid.UUID(TEST_USER_ID)},
        )
        await db_session.flush()

        response = await authenticated_db_client.patch(
            "/v1/settings",
            json={"notifications_enabled": True},
        )
        assert response.status_code == 200
        assert response.json() == {
            "theme": "dark",
            "text_size": "large",
            "notifications_enabled": True,
            "ai_internet_access": False,
        }

    async def test_invalid_theme_returns_422(self, authenticated_db_client):
        response = await authenticated_db_client.patch(
            "/v1/settings",
            json={"theme": "purple-unicorn"},
        )
        assert response.status_code == 422

    async def test_invalid_text_size_returns_422(self, authenticated_db_client):
        response = await authenticated_db_client.patch(
            "/v1/settings",
            json={"text_size": "XXXL"},
        )
        assert response.status_code == 422

    async def test_empty_body_returns_422(self, authenticated_db_client):
        response = await authenticated_db_client.patch(
            "/v1/settings",
            json={},
        )
        assert response.status_code == 422

    async def test_unauthenticated_returns_401(self, db_session):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": TEST_API_KEY},
        ) as client:
            response = await client.patch(
                "/v1/settings",
                json={"theme": "dark"},
            )
        assert response.status_code == 401

    async def test_scoped_to_current_user(
        self, authenticated_db_client, db_session
    ):
        # Create another user with their own settings row; verify the PATCH
        # from TEST_USER_ID does not touch them.
        other_user_id = uuid.uuid4()
        await db_session.execute(
            text(
                "INSERT INTO auth.users ("
                "id, instance_id, email, encrypted_password, aud, role, "
                "raw_app_meta_data, raw_user_meta_data, created_at, updated_at, "
                "confirmation_token, email_change, email_change_token_new, recovery_token"
                ") VALUES ("
                ":id, '00000000-0000-0000-0000-000000000000', :email, '', "
                "'authenticated', 'authenticated', '{}', '{}', now(), now(), "
                "'', '', '', ''"
                ")"
            ),
            {"id": other_user_id, "email": f"other-{other_user_id}@example.com"},
        )
        # user_profiles row is created automatically by a trigger on auth.users.
        await db_session.execute(
            text(
                "INSERT INTO user_settings "
                "(id, user_id, theme, text_size, notifications_enabled, ai_internet_access) "
                "VALUES (gen_random_uuid(), :uid, 'light', 'small', true, true)"
            ),
            {"uid": other_user_id},
        )
        await db_session.flush()

        response = await authenticated_db_client.patch(
            "/v1/settings",
            json={"theme": "dark"},
        )
        assert response.status_code == 200

        row = await db_session.execute(
            text("SELECT theme FROM user_settings WHERE user_id = :uid"),
            {"uid": other_user_id},
        )
        assert row.scalar() == "light"


# ---------------------------------------------------------------------------
# GET /v1/settings/profile
# ---------------------------------------------------------------------------


@pytest.fixture
async def brokerage_account(db_session: AsyncSession, test_user) -> uuid.UUID:
    account_id = uuid.uuid4()
    await db_session.execute(
        text(
            """
            INSERT INTO brokerage_accounts (
                id, user_id, alpaca_account_id, account_status,
                account_number, kyc_results, kyc_submitted_at
            ) VALUES (
                :id, :user_id, :alpaca_id, 'ACTIVE',
                'SEV123456', '{"status": "approved"}'::jsonb, now()
            )
            """
        ),
        {
            "id": account_id,
            "user_id": test_user,
            "alpaca_id": f"alpaca_{uuid.uuid4()}",
        },
    )
    await db_session.flush()
    return account_id


class TestGetSettingsProfile:

    async def test_returns_minimal_profile_for_fresh_user(
        self, authenticated_db_client
    ):
        response = await authenticated_db_client.get("/v1/settings/profile")
        assert response.status_code == 200

        data = response.json()
        assert data["profile"]["email"] is not None
        assert data["financial_profile"] is None
        assert data["brokerage"] is None
        assert data["linked_accounts"] == []
        assert data["member_since"] is not None

    async def test_returns_financial_profile_when_present(
        self, authenticated_db_client
    ):
        await authenticated_db_client.patch(
            "/v1/onboarding",
            json={"step": "annual_income", "annual_income": "$50K – $99K"},
        )

        response = await authenticated_db_client.get("/v1/settings/profile")
        assert response.status_code == 200

        data = response.json()
        assert data["financial_profile"]["annual_income"] == "$50K – $99K"

    async def test_returns_brokerage_summary(
        self, authenticated_db_client, brokerage_account
    ):
        response = await authenticated_db_client.get("/v1/settings/profile")
        assert response.status_code == 200

        data = response.json()
        assert data["brokerage"]["account_number"] == "SEV123456"
        assert data["brokerage"]["account_status"] == "ACTIVE"
        assert data["brokerage"]["kyc_results"] == {"status": "approved"}

    async def test_returns_active_linked_accounts_only(
        self, authenticated_db_client, db_session, test_user, brokerage_account
    ):
        active = await AchRelationshipRepository.create(
            db_session,
            user_id=test_user,
            brokerage_account_id=brokerage_account,
            plaid_item_id=None,
            alpaca_relationship_id="alp_rel_active",
            institution_name="First Platypus Bank",
            account_mask="0000",
            account_type="CHECKING",
            nickname="Checking",
            status="APPROVED",
        )
        await AchRelationshipRepository.create(
            db_session,
            user_id=test_user,
            brokerage_account_id=brokerage_account,
            plaid_item_id=None,
            alpaca_relationship_id="alp_rel_canceled",
            status="CANCELED",
        )

        response = await authenticated_db_client.get("/v1/settings/profile")
        assert response.status_code == 200

        data = response.json()
        linked = data["linked_accounts"]
        assert len(linked) == 1
        assert linked[0]["alpaca_relationship_id"] == "alp_rel_active"
        assert linked[0]["institution_name"] == "First Platypus Bank"
        assert linked[0]["status"] == "APPROVED"
        assert uuid.UUID(linked[0]["id"]) == active.id

    async def test_missing_profile_returns_404(self, db_session):
        """User without a user_profiles row should get 404."""
        unknown_id = str(uuid.uuid4())
        app.dependency_overrides[get_current_user] = lambda: unknown_id

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
                headers={"X-API-Key": TEST_API_KEY},
            ) as client:
                response = await client.get("/v1/settings/profile")
        finally:
            app.dependency_overrides.pop(get_current_user, None)

        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"

    async def test_unauthenticated_profile_returns_401(self, db_session):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": TEST_API_KEY},
        ) as client:
            response = await client.get("/v1/settings/profile")
        assert response.status_code == 401
