"""Onboarding completion opts the user into the radar cadence.

Verifies the T6 hook on `POST /v1/onboarding/submit`: after KYC submits
successfully, the route sets ``next_radar_refresh_at = now()`` (the
"radar enabled" signal the hourly cron filters on) and enqueues the first
``generate_radar_batch`` with a deterministic per-user-per-day job id.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from app.main import app
from app.routes.onboarding import get_alpaca
from tests.integration.conftest import TEST_USER_ID, _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync,
    reason="Local Supabase Postgres not available (run `make infra`)",
)


_ONBOARDING_STEPS = [
    {"step": "preferred_name", "preferred_name": "Riley"},
    {"step": "date_of_birth", "date_of_birth": "1998-03-15"},
    {"step": "financial_worries", "financial_worries": ["not_saving_enough"]},
    {"step": "investment_goals", "investment_goals": ["grow_wealth"]},
    {"step": "annual_income", "annual_income": "$50K – $99K"},
    {"step": "net_worth", "net_worth": "$100K – $250K"},
    {"step": "liquid_net_worth", "liquid_net_worth": "$25K – $50K"},
    {"step": "income_stability", "income_stability": "stable"},
    {"step": "time_horizon", "time_horizon": "5-10 years"},
    {"step": "risk_scenario", "risk_scenario_response": "hold"},
    {"step": "max_loss_tolerance", "max_loss_tolerance": "15-25%"},
    {"step": "experience", "experience_level": "invest_regularly"},
    {"step": "legal_name", "first_name": "Riley", "last_name": "Johnson"},
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
    {"step": "funding_sources", "funding_sources": ["employment_income"]},
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


async def _fill_onboarding(client) -> None:
    for step_data in _ONBOARDING_STEPS:
        resp = await client.patch("/v1/onboarding", json=step_data)
        assert resp.status_code == 200, f"Failed on step: {step_data['step']}"


@pytest.fixture
def mock_arq_pool():
    """Stub `app.state.arq` for the duration of one test.

    The route reaches the queue via ``request.app.state.arq``. The real
    lifespan never runs under tests, so install a fresh AsyncMock and
    restore whatever was there afterward.
    """
    prior = getattr(app.state, "arq", None)
    pool = AsyncMock()
    app.state.arq = pool
    yield pool
    app.state.arq = prior


@pytest.fixture
def mock_alpaca_submitted():
    alpaca = AsyncMock()
    alpaca.create_account.return_value = {
        "id": "alpaca-account-123",
        "status": "SUBMITTED",
        "account_number": "ABC123",
        "kyc_results": None,
    }
    app.dependency_overrides[get_alpaca] = lambda: alpaca
    yield alpaca
    app.dependency_overrides.pop(get_alpaca, None)


async def test_submit_enqueues_first_batch_and_sets_anchor(
    authenticated_db_client, db_session, mock_arq_pool, mock_alpaca_submitted
):
    await _fill_onboarding(authenticated_db_client)

    before = datetime.now(timezone.utc)
    response = await authenticated_db_client.post(
        "/v1/onboarding/submit", json={"tax_id": "412-73-8256"}
    )
    after = datetime.now(timezone.utc)

    assert response.status_code == 200

    # Anchor set to ~now — this is the cron's "radar enabled" predicate.
    anchor = (
        await db_session.execute(
            text(
                "SELECT next_radar_refresh_at FROM user_profiles WHERE id = :id"
            ),
            {"id": uuid.UUID(TEST_USER_ID)},
        )
    ).scalar_one()
    assert anchor is not None
    assert before <= anchor <= after

    # First batch enqueued with the deterministic per-user-per-day job id.
    mock_arq_pool.enqueue_job.assert_awaited_once()
    call = mock_arq_pool.enqueue_job.await_args
    assert call.args[0] == "generate_radar_batch"
    assert call.args[1] == TEST_USER_ID
    expected_day = datetime.now(timezone.utc).date().isoformat()
    expected_job_id = f"radar_batch:{TEST_USER_ID}:{expected_day}"
    assert call.kwargs["_job_id"] == expected_job_id


async def test_submit_succeeds_when_enqueue_fails(
    authenticated_db_client, db_session, mock_arq_pool, mock_alpaca_submitted
):
    """A Redis blip on enqueue must not fail the request — the Alpaca
    account is already created and can't be rolled back. The anchor is
    still committed, so the refresh cron self-heals the missing batch.
    """
    await _fill_onboarding(authenticated_db_client)
    mock_arq_pool.enqueue_job.side_effect = ConnectionError("redis down")

    response = await authenticated_db_client.post(
        "/v1/onboarding/submit", json={"tax_id": "412-73-8256"}
    )

    assert response.status_code == 200
    # Brokerage row persisted despite the enqueue failure.
    brokerage = (
        await db_session.execute(
            text(
                "SELECT account_status FROM brokerage_accounts WHERE user_id = :id"
            ),
            {"id": uuid.UUID(TEST_USER_ID)},
        )
    ).scalar_one()
    assert brokerage == "SUBMITTED"
    # Anchor still set — the cron will pick the user up.
    anchor = (
        await db_session.execute(
            text(
                "SELECT next_radar_refresh_at FROM user_profiles WHERE id = :id"
            ),
            {"id": uuid.UUID(TEST_USER_ID)},
        )
    ).scalar_one()
    assert anchor is not None


async def test_submit_does_not_enqueue_when_kyc_fails(
    authenticated_db_client, db_session, mock_arq_pool, mock_alpaca_submitted
):
    """Incomplete onboarding raises before the hook — no anchor, no enqueue.

    The order matters: the batch must only fire once KYC has actually
    succeeded, never on the error path.
    """
    # Skip `_fill_onboarding` — the financial profile is missing, so
    # submit_kyc raises IncompleteOnboardingError before the hook runs.
    await authenticated_db_client.patch(
        "/v1/onboarding",
        json={"step": "preferred_name", "preferred_name": "Riley"},
    )

    response = await authenticated_db_client.post(
        "/v1/onboarding/submit", json={"tax_id": "412-73-8256"}
    )

    assert response.status_code == 422
    mock_arq_pool.enqueue_job.assert_not_awaited()

    anchor = (
        await db_session.execute(
            text(
                "SELECT next_radar_refresh_at FROM user_profiles WHERE id = :id"
            ),
            {"id": uuid.UUID(TEST_USER_ID)},
        )
    ).scalar_one()
    assert anchor is None
