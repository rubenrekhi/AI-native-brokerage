"""
Integration tests for onboarding endpoints against real local Postgres.

Requires: Docker + `make infra` + `make migrate`.
Skipped automatically if Postgres is unavailable.
"""

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.routes.onboarding import get_alpaca
from tests.integration.conftest import TEST_USER_ID, _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync,
    reason="Local Supabase Postgres not available (run `make infra`)",
)


# ---------------------------------------------------------------------------
# PATCH /v1/onboarding
# ---------------------------------------------------------------------------


class TestPatchOnboarding:

    async def test_save_preferred_name(self, authenticated_db_client, db_session):
        response = await authenticated_db_client.patch(
            "/v1/onboarding",
            json={"step": "preferred_name", "preferred_name": "Riley"},
        )
        assert response.status_code == 200
        assert response.json()["step"] == "preferred_name"

        # Verify it was actually written to the DB
        row = await db_session.execute(
            text("SELECT preferred_name, onboarding_step FROM user_profiles WHERE id = :id"),
            {"id": uuid.UUID(TEST_USER_ID)},
        )
        result = row.one()
        assert result.preferred_name == "Riley"
        assert result.onboarding_step == "preferred_name"

    async def test_save_financial_worries_creates_financial_profile(
        self, authenticated_db_client, db_session
    ):
        response = await authenticated_db_client.patch(
            "/v1/onboarding",
            json={
                "step": "financial_worries",
                "financial_worries": ["not_saving_enough", "falling_behind"],
            },
        )
        assert response.status_code == 200

        # Verify user_financial_profiles row was created
        row = await db_session.execute(
            text(
                "SELECT financial_worries FROM user_financial_profiles WHERE user_id = :id"
            ),
            {"id": uuid.UUID(TEST_USER_ID)},
        )
        result = row.one()
        assert result.financial_worries == ["not_saving_enough", "falling_behind"]

    async def test_save_address_fields(self, authenticated_db_client, db_session):
        response = await authenticated_db_client.patch(
            "/v1/onboarding",
            json={
                "step": "address",
                "street_address": ["123 Main St", "Apt 4B"],
                "city": "New York",
                "state": "NY",
                "postal_code": "10001",
            },
        )
        assert response.status_code == 200

        row = await db_session.execute(
            text("SELECT city, state, postal_code FROM user_profiles WHERE id = :id"),
            {"id": uuid.UUID(TEST_USER_ID)},
        )
        result = row.one()
        assert result.city == "New York"
        assert result.state == "NY"
        assert result.postal_code == "10001"

    async def test_invalid_step_rejected(self, authenticated_db_client):
        response = await authenticated_db_client.patch(
            "/v1/onboarding",
            json={"step": "invalid_step"},
        )
        assert response.status_code == 422

    async def test_unauthenticated_returns_401(self, db_session):
        """Client without auth override should get 401."""
        from httpx import ASGITransport, AsyncClient
        from app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": "test-api-key-for-testing"},
        ) as client:
            response = await client.patch(
                "/v1/onboarding",
                json={"step": "preferred_name", "preferred_name": "Riley"},
            )
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /v1/onboarding/status
# ---------------------------------------------------------------------------


class TestGetOnboardingStatus:

    async def test_status_returns_empty_profile(self, authenticated_db_client):
        response = await authenticated_db_client.get("/v1/onboarding/status")
        assert response.status_code == 200

        data = response.json()
        assert data["onboarding_completed"] is False
        assert data["onboarding_step"] is None
        assert data["account_status"] is None
        assert data["profile"]["email"] is not None
        assert data["financial_profile"] is None

    async def test_status_returns_saved_data(self, authenticated_db_client):
        # Save some data first
        await authenticated_db_client.patch(
            "/v1/onboarding",
            json={"step": "preferred_name", "preferred_name": "Riley"},
        )
        await authenticated_db_client.patch(
            "/v1/onboarding",
            json={"step": "annual_income", "annual_income": "$50K \u2013 $99K"},
        )

        response = await authenticated_db_client.get("/v1/onboarding/status")
        assert response.status_code == 200

        data = response.json()
        assert data["onboarding_step"] == "annual_income"
        assert data["profile"]["preferred_name"] == "Riley"
        assert data["financial_profile"]["annual_income"] == "$50K \u2013 $99K"


# ---------------------------------------------------------------------------
# POST /v1/onboarding/submit
# ---------------------------------------------------------------------------


class TestPostOnboardingSubmit:

    async def _fill_onboarding(self, client):
        """Helper — save all required onboarding fields via PATCH calls."""
        steps = [
            {"step": "preferred_name", "preferred_name": "Riley"},
            {"step": "date_of_birth", "date_of_birth": "1998-03-15"},
            {
                "step": "financial_worries",
                "financial_worries": ["not_saving_enough"],
            },
            {
                "step": "investment_goals",
                "investment_goals": ["grow_wealth"],
            },
            {"step": "annual_income", "annual_income": "$50K \u2013 $99K"},
            {"step": "net_worth", "net_worth": "$100K \u2013 $250K"},
            {"step": "liquid_net_worth", "liquid_net_worth": "$25K \u2013 $50K"},
            {"step": "income_stability", "income_stability": "stable"},
            {"step": "time_horizon", "time_horizon": "5-10 years"},
            {"step": "risk_scenario", "risk_scenario_response": "hold"},
            {"step": "max_loss_tolerance", "max_loss_tolerance": "15-25%"},
            {"step": "experience", "experience_level": "invest_regularly"},
            {
                "step": "legal_name",
                "first_name": "Riley",
                "last_name": "Johnson",
            },
            {
                "step": "address",
                "street_address": ["123 Main St"],
                "city": "New York",
                "state": "NY",
                "postal_code": "10001",
            },
            {
                "step": "citizenship",
                "country_of_citizenship": "USA",
                "country_of_birth": "USA",
                "country_of_tax_residence": "USA",
            },
            {
                "step": "employment",
                "employment_info": {
                    "employment_status": "employed",
                    "employer_name": "Acme Inc",
                },
            },
            {
                "step": "funding_sources",
                "funding_sources": ["employment_income"],
            },
            {
                "step": "disclosures",
                "disclosures": {
                    "is_control_person": False,
                    "is_affiliated_exchange_or_finra": False,
                    "is_politically_exposed": False,
                    "immediate_family_exposed": False,
                },
            },
            {
                "step": "agreements",
                "agreements_signed": {
                    "customer_agreement": True,
                    "margin_agreement": True,
                    "signed_at": "2026-04-06T12:00:00Z",
                    "ip_address": "1.2.3.4",
                },
            },
        ]
        for step_data in steps:
            resp = await client.patch("/v1/onboarding", json=step_data)
            assert resp.status_code == 200, f"Failed on step: {step_data['step']}"

    async def test_successful_submission(self, authenticated_db_client, db_session):
        await self._fill_onboarding(authenticated_db_client)

        mock_alpaca = AsyncMock()
        mock_alpaca.create_account.return_value = {
            "id": "alpaca-account-123",
            "status": "SUBMITTED",
            "account_number": "ABC123",
            "kyc_results": None,
        }
        app.dependency_overrides[get_alpaca] = lambda: mock_alpaca

        response = await authenticated_db_client.post(
            "/v1/onboarding/submit",
            json={"tax_id": "123-45-6789"},
        )

        app.dependency_overrides.pop(get_alpaca, None)

        assert response.status_code == 200
        data = response.json()
        assert data["account_status"] == "SUBMITTED"
        assert data["alpaca_account_id"] == "alpaca-account-123"

        # Verify brokerage_accounts row was created
        row = await db_session.execute(
            text(
                "SELECT alpaca_account_id, account_status FROM brokerage_accounts WHERE user_id = :id"
            ),
            {"id": uuid.UUID(TEST_USER_ID)},
        )
        result = row.one()
        assert result.alpaca_account_id == "alpaca-account-123"
        assert result.account_status == "SUBMITTED"

        # Verify Alpaca was called with the SSN (not stored in DB)
        call_payload = mock_alpaca.create_account.call_args[0][0]
        assert call_payload["identity"]["tax_id"] == "123-45-6789"
        assert call_payload["identity"]["tax_id_type"] == "USA_SSN"

        # Verify only last-4 of the SSN was persisted (full SSN is not stored)
        profile_row = await db_session.execute(
            text("SELECT tax_id_last_4 FROM user_profiles WHERE id = :id"),
            {"id": uuid.UUID(TEST_USER_ID)},
        )
        assert profile_row.scalar_one() == "6789"

    async def test_duplicate_submission_returns_409(
        self, authenticated_db_client, db_session
    ):
        await self._fill_onboarding(authenticated_db_client)

        mock_alpaca = AsyncMock()
        mock_alpaca.create_account.return_value = {
            "id": "alpaca-account-123",
            "status": "SUBMITTED",
            "account_number": "ABC123",
            "kyc_results": None,
        }
        app.dependency_overrides[get_alpaca] = lambda: mock_alpaca

        # First submission
        resp1 = await authenticated_db_client.post(
            "/v1/onboarding/submit",
            json={"tax_id": "123-45-6789"},
        )
        assert resp1.status_code == 200

        # Second submission — should fail
        resp2 = await authenticated_db_client.post(
            "/v1/onboarding/submit",
            json={"tax_id": "123-45-6789"},
        )
        assert resp2.status_code == 409
        assert resp2.json()["code"] == "CONFLICT"

        app.dependency_overrides.pop(get_alpaca, None)

    async def test_incomplete_onboarding_returns_422(self, authenticated_db_client):
        # Only save name — skip everything else (no financial profile exists)
        await authenticated_db_client.patch(
            "/v1/onboarding",
            json={"step": "preferred_name", "preferred_name": "Riley"},
        )

        mock_alpaca = AsyncMock()
        app.dependency_overrides[get_alpaca] = lambda: mock_alpaca

        response = await authenticated_db_client.post(
            "/v1/onboarding/submit",
            json={"tax_id": "123-45-6789"},
        )

        app.dependency_overrides.pop(get_alpaca, None)

        assert response.status_code == 422
        assert response.json()["code"] == "INCOMPLETE_ONBOARDING"

    async def test_alpaca_error_returns_422(self, authenticated_db_client):
        await self._fill_onboarding(authenticated_db_client)

        from app.services.alpaca_broker import AlpacaBrokerError

        mock_alpaca = AsyncMock()
        mock_alpaca.create_account.side_effect = AlpacaBrokerError(
            status_code=400,
            message="invalid tax_id format",
            detail={"code": "invalid_request"},
        )
        app.dependency_overrides[get_alpaca] = lambda: mock_alpaca

        response = await authenticated_db_client.post(
            "/v1/onboarding/submit",
            json={"tax_id": "123-45-6789"},
        )

        app.dependency_overrides.pop(get_alpaca, None)

        assert response.status_code == 422
        assert "ALPACA_ERROR" in response.json()["code"]
