"""Integration tests for the /v1/recurring-investments routes."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.main import app
from app.models.asset import Asset
from app.routes.recurring_investments import get_alpaca
from app.services.alpaca_broker import AlpacaBrokerService
from tests.integration.conftest import _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync, reason="Local Postgres not running"
)


@pytest.fixture(autouse=True)
def mock_alpaca():
    """Override the route's Alpaca dependency.

    A notional *buy* never touches Alpaca during create (only sells fetch a
    position), but the `Depends(get_alpaca)` reads `app.state.alpaca`, which
    the test lifespan never sets. The mock keeps the dependency resolvable.
    """
    mock = AsyncMock(spec=AlpacaBrokerService)
    app.dependency_overrides[get_alpaca] = lambda: mock
    yield mock
    app.dependency_overrides.pop(get_alpaca, None)


@pytest.fixture
async def recurring_assets(db_session):
    """Seed fractionable (VOO/SPY) and non-fractionable (BRK.A) tickers."""
    stmt = pg_insert(Asset).values(
        [
            {"symbol": "VOO", "name": "Vanguard S&P 500 ETF", "exchange": "NYSE", "tradeable": True, "fractionable": True},
            {"symbol": "SPY", "name": "SPDR S&P 500 ETF", "exchange": "NYSE", "tradeable": True, "fractionable": True},
            {"symbol": "BRKA", "name": "Berkshire Hathaway A", "exchange": "NYSE", "tradeable": True, "fractionable": False},
        ]
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["symbol"],
        set_={
            "tradeable": True,
            "fractionable": stmt.excluded.fractionable,
            "name": stmt.excluded.name,
        },
    )
    await db_session.execute(stmt)
    await db_session.flush()


def _future_date(days: int = 14) -> str:
    d = datetime.now(timezone.utc).date() + timedelta(days=days)
    return f"{d.isoformat()}T00:00:00Z"


def _create_body(**overrides):
    body = {
        "block_id": "blk_ri",
        "ticker": "VOO",
        "amount": "50.00",
        "frequency": "weekly",
        "start_date": _future_date(14),
        "end_condition": {"kind": "never"},
    }
    body.update(overrides)
    return body


async def test_create_returns_201_with_active_plan(
    authenticated_db_client, test_user, test_brokerage_account, recurring_assets
):
    start = _future_date(14)
    start_day = start[:10]
    response = await authenticated_db_client.post(
        "/v1/recurring-investments", json=_create_body(start_date=start)
    )

    assert response.status_code == 201
    body = response.json()
    assert body["ticker"] == "VOO"
    assert body["amount"] == "50.00"
    assert body["frequency"] == "weekly"
    assert body["status"] == "active"
    assert body["start_date"] == start_day
    # First run is the start date.
    assert body["next_run_date"] == start_day
    assert body["end_condition"] == {"kind": "never"}
    assert body["executions_count"] == 0
    uuid.UUID(body["id"])


async def test_create_persists_on_date_end_condition(
    authenticated_db_client, test_user, test_brokerage_account, recurring_assets
):
    end = _future_date(180)
    response = await authenticated_db_client.post(
        "/v1/recurring-investments",
        json=_create_body(
            frequency="monthly",
            end_condition={"kind": "on_date", "date": end},
        ),
    )

    assert response.status_code == 201
    assert response.json()["end_condition"] == {"kind": "on_date", "date": end}


async def test_create_persists_after_count_end_condition(
    authenticated_db_client, test_user, test_brokerage_account, recurring_assets
):
    response = await authenticated_db_client.post(
        "/v1/recurring-investments",
        json=_create_body(end_condition={"kind": "after_count", "count": 24}),
    )

    assert response.status_code == 201
    assert response.json()["end_condition"] == {"kind": "after_count", "count": 24}


async def test_create_accepts_daily_frequency(
    authenticated_db_client, test_user, test_brokerage_account, recurring_assets
):
    response = await authenticated_db_client.post(
        "/v1/recurring-investments", json=_create_body(frequency="daily")
    )
    assert response.status_code == 201
    assert response.json()["frequency"] == "daily"


async def test_create_rejects_amount_below_one_dollar(
    authenticated_db_client, test_user, test_brokerage_account, recurring_assets
):
    response = await authenticated_db_client.post(
        "/v1/recurring-investments", json=_create_body(amount="0.50")
    )
    assert response.status_code == 422


async def test_create_rejects_non_fractionable_symbol(
    authenticated_db_client, test_user, test_brokerage_account, recurring_assets
):
    response = await authenticated_db_client.post(
        "/v1/recurring-investments", json=_create_body(ticker="BRKA")
    )
    assert response.status_code == 409
    assert response.json()["code"] == "ASSET_NOT_FRACTIONABLE"


async def test_create_rejects_unknown_symbol(
    authenticated_db_client, test_user, test_brokerage_account, recurring_assets
):
    response = await authenticated_db_client.post(
        "/v1/recurring-investments", json=_create_body(ticker="ZZZZ")
    )
    assert response.status_code == 409
    assert response.json()["code"] == "SYMBOL_NOT_TRADEABLE"


async def test_create_rejects_past_start_date(
    authenticated_db_client, test_user, test_brokerage_account, recurring_assets
):
    response = await authenticated_db_client.post(
        "/v1/recurring-investments",
        json=_create_body(start_date="2020-01-01T00:00:00Z"),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "RECURRING_START_DATE_IN_PAST"


async def test_create_requires_active_brokerage(
    authenticated_db_client, test_user, recurring_assets
):
    # No test_brokerage_account fixture → user has no ACTIVE account.
    response = await authenticated_db_client.post(
        "/v1/recurring-investments", json=_create_body()
    )
    assert response.status_code == 409
    assert response.json()["code"] == "ACCOUNT_NOT_ACTIVE"


async def test_create_requires_auth(client, recurring_assets):
    response = await client.post(
        "/v1/recurring-investments", json=_create_body()
    )
    assert response.status_code == 401


async def test_list_returns_all_live_plans(
    authenticated_db_client, test_user, test_brokerage_account, recurring_assets
):
    await authenticated_db_client.post(
        "/v1/recurring-investments", json=_create_body(ticker="VOO")
    )
    await authenticated_db_client.post(
        "/v1/recurring-investments", json=_create_body(ticker="SPY")
    )

    response = await authenticated_db_client.get("/v1/recurring-investments")

    assert response.status_code == 200
    plans = response.json()["recurring_investments"]
    # Order is created_at DESC in production; the shared-transaction test
    # gives both rows the same now(), so assert membership, not order.
    assert {plan["ticker"] for plan in plans} == {"VOO", "SPY"}


async def test_pause_then_resume_round_trips_status(
    authenticated_db_client, test_user, test_brokerage_account, recurring_assets
):
    created = await authenticated_db_client.post(
        "/v1/recurring-investments", json=_create_body()
    )
    plan_id = created.json()["id"]

    paused = await authenticated_db_client.patch(
        f"/v1/recurring-investments/{plan_id}", json={"action": "pause"}
    )
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"

    resumed = await authenticated_db_client.patch(
        f"/v1/recurring-investments/{plan_id}", json={"action": "resume"}
    )
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "active"


async def test_resume_rolls_next_run_forward_to_future_date(
    authenticated_db_client, test_user, test_brokerage_account, recurring_assets
):
    # start_date today → next_run_date today; pausing then resuming must never
    # leave next_run_date in the past.
    today_str = datetime.now(timezone.utc).date().isoformat()
    created = await authenticated_db_client.post(
        "/v1/recurring-investments",
        json=_create_body(start_date=_future_date(0), frequency="weekly"),
    )
    plan_id = created.json()["id"]
    assert created.json()["next_run_date"] == today_str

    await authenticated_db_client.patch(
        f"/v1/recurring-investments/{plan_id}", json={"action": "pause"}
    )
    resumed = await authenticated_db_client.patch(
        f"/v1/recurring-investments/{plan_id}", json={"action": "resume"}
    )
    assert resumed.json()["next_run_date"] >= today_str


async def test_resume_non_paused_plan_returns_409(
    authenticated_db_client, test_user, test_brokerage_account, recurring_assets
):
    created = await authenticated_db_client.post(
        "/v1/recurring-investments", json=_create_body()
    )
    plan_id = created.json()["id"]

    response = await authenticated_db_client.patch(
        f"/v1/recurring-investments/{plan_id}", json={"action": "resume"}
    )
    assert response.status_code == 409
    assert response.json()["code"] == "RECURRING_NOT_PAUSED"


async def test_cancel_soft_deletes_and_excludes_from_list(
    authenticated_db_client, test_user, test_brokerage_account, recurring_assets
):
    created = await authenticated_db_client.post(
        "/v1/recurring-investments", json=_create_body()
    )
    plan_id = created.json()["id"]

    cancelled = await authenticated_db_client.delete(
        f"/v1/recurring-investments/{plan_id}"
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    listed = await authenticated_db_client.get("/v1/recurring-investments")
    assert listed.json()["recurring_investments"] == []


async def test_cancel_unknown_id_returns_404(
    authenticated_db_client, test_user
):
    response = await authenticated_db_client.delete(
        f"/v1/recurring-investments/{uuid.uuid4()}"
    )
    assert response.status_code == 404


async def test_pause_unknown_id_returns_404(authenticated_db_client, test_user):
    response = await authenticated_db_client.patch(
        f"/v1/recurring-investments/{uuid.uuid4()}", json={"action": "pause"}
    )
    assert response.status_code == 404


async def test_user_b_cannot_cancel_user_a_plan(
    authenticated_db_client,
    test_user,
    test_brokerage_account,
    recurring_assets,
    make_extra_user,
):
    created = await authenticated_db_client.post(
        "/v1/recurring-investments", json=_create_body()
    )
    plan_id = created.json()["id"]

    # Re-point auth at a different user, then attempt to cancel.
    from app.auth import get_current_user

    other_user = await make_extra_user()
    app.dependency_overrides[get_current_user] = lambda: str(other_user)
    try:
        response = await authenticated_db_client.delete(
            f"/v1/recurring-investments/{plan_id}"
        )
    finally:
        from tests.integration.conftest import TEST_USER_ID

        app.dependency_overrides[get_current_user] = lambda: TEST_USER_ID

    assert response.status_code == 404
