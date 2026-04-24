"""Integration tests for GET /v1/settings/profile against real local Postgres."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.main import app
from app.repositories.ach_relationship import AchRelationshipRepository
from tests.integration.conftest import _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync,
    reason="Local Supabase Postgres not available (run `make infra`)",
)


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
                headers={"X-API-Key": "test-api-key-for-testing"},
            ) as client:
                response = await client.get("/v1/settings/profile")
        finally:
            app.dependency_overrides.pop(get_current_user, None)

        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"

    async def test_unauthenticated_returns_401(self, db_session):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": "test-api-key-for-testing"},
        ) as client:
            response = await client.get("/v1/settings/profile")
        assert response.status_code == 401
