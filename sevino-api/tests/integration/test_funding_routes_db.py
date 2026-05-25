"""Real-DB integration tests for GET /v1/funding/ach-relationships.

Covers the requires_reauth surfacing added in SEV-589 — the boolean flips to
true when the underlying plaid_items row is in requires_reauth state.
"""

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.repositories.ach_relationship import AchRelationshipRepository
from app.repositories.plaid_item import PlaidItemRepository
from app.routes.funding import get_alpaca
from tests.integration.conftest import _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync,
    reason="Local Supabase Postgres not available (run `make infra`)",
)


@pytest.fixture
def alpaca_mock_empty() -> AsyncMock:
    """No-op Alpaca mock — refresh-on-read finds nothing to update."""
    svc = AsyncMock()
    svc.list_ach_relationships.return_value = []
    return svc


@pytest.fixture
async def client_with_alpaca_mock(authenticated_db_client, alpaca_mock_empty):
    app.dependency_overrides[get_alpaca] = lambda: alpaca_mock_empty
    yield authenticated_db_client
    app.dependency_overrides.pop(get_alpaca, None)


async def _seed_relationship(
    db_session: AsyncSession,
    user_id: uuid.UUID,
    brokerage_account_id: uuid.UUID,
    *,
    plaid_status: str,
) -> None:
    item = await PlaidItemRepository.create(
        db_session,
        user_id=user_id,
        plaid_item_id=f"item_{uuid.uuid4().hex[:8]}",
        plaid_access_token_plaintext="access-sandbox-x",
        plaid_account_id="acct_x",
        institution_name="Platypus",
    )
    if plaid_status != "active":
        item.status = plaid_status
    await AchRelationshipRepository.create(
        db_session,
        user_id=user_id,
        brokerage_account_id=brokerage_account_id,
        plaid_item_id=item.id,
        alpaca_relationship_id=f"alp_{uuid.uuid4().hex[:8]}",
        institution_name="Platypus",
        account_mask="0000",
        account_type="CHECKING",
        status="APPROVED",
    )
    await db_session.flush()


class TestRequiresReauthSurfacing:
    async def test_true_when_plaid_item_requires_reauth(
        self,
        client_with_alpaca_mock,
        db_session,
        test_user,
        test_brokerage_account,
    ):
        await _seed_relationship(
            db_session,
            test_user,
            test_brokerage_account["id"],
            plaid_status="requires_reauth",
        )

        response = await client_with_alpaca_mock.get("/v1/funding/ach-relationships")

        assert response.status_code == 200
        body = response.json()
        assert len(body["relationships"]) == 1
        assert body["relationships"][0]["requires_reauth"] is True

    @pytest.mark.parametrize("plaid_status", ["active", "inactive"])
    async def test_false_for_non_reauth_plaid_statuses(
        self,
        client_with_alpaca_mock,
        db_session,
        test_user,
        test_brokerage_account,
        plaid_status,
    ):
        await _seed_relationship(
            db_session,
            test_user,
            test_brokerage_account["id"],
            plaid_status=plaid_status,
        )

        response = await client_with_alpaca_mock.get("/v1/funding/ach-relationships")

        assert response.status_code == 200
        body = response.json()
        assert len(body["relationships"]) == 1
        assert body["relationships"][0]["requires_reauth"] is False

    async def test_false_when_relationship_has_no_plaid_item(
        self,
        client_with_alpaca_mock,
        db_session,
        test_user,
        test_brokerage_account,
    ):
        await AchRelationshipRepository.create(
            db_session,
            user_id=test_user,
            brokerage_account_id=test_brokerage_account["id"],
            plaid_item_id=None,
            alpaca_relationship_id=f"alp_{uuid.uuid4().hex[:8]}",
            institution_name="Platypus",
            account_mask="0000",
            status="APPROVED",
        )
        await db_session.flush()

        response = await client_with_alpaca_mock.get("/v1/funding/ach-relationships")

        assert response.status_code == 200
        body = response.json()
        assert len(body["relationships"]) == 1
        assert body["relationships"][0]["requires_reauth"] is False
