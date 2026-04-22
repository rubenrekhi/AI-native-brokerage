"""Integration tests for /v1/funding/* routes.

The router is not yet mounted on `app.main:app` (that happens in Phase 7).
These tests mount it on a local sub-app so we can exercise the full stack —
schemas, auth, FundingService orchestration — without a real DB or external
services. Repositories are patched at the module path; Plaid and Alpaca are
injected as AsyncMocks via dependency overrides.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.auth import get_current_user
from app.database import get_db
from app.exceptions import register_exception_handlers
from app.routes.funding import get_alpaca, get_plaid, router as funding_router
from app.services.alpaca_broker import AlpacaBrokerError

TEST_USER_ID = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Sub-app + client
# ---------------------------------------------------------------------------


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(funding_router, prefix="/v1/funding", tags=["funding"])
    register_exception_handlers(app)
    return app


@pytest.fixture
def plaid_mock() -> AsyncMock:
    svc = AsyncMock()
    svc.create_link_token.return_value = "link-sandbox-test"
    svc.exchange_public_token.return_value = ("access-sandbox-abc", "item_123")
    svc.create_processor_token.return_value = "processor-sandbox-abc"
    return svc


@pytest.fixture
def alpaca_mock() -> AsyncMock:
    svc = AsyncMock()
    svc.create_ach_relationship.return_value = {
        "id": "alp_rel_xyz",
        "status": "QUEUED",
        "nickname": "Alpaca Nickname",
        "bank_account_type": "CHECKING",
    }
    svc.delete_ach_relationship.return_value = None
    svc.create_transfer.return_value = {
        "id": "xfer_1",
        "status": "QUEUED",
        "amount": "500.00",
        "direction": "INCOMING",
        "created_at": "2026-04-18T18:00:00Z",
    }
    svc.list_transfers.return_value = []
    # The refresh-on-read path calls this for both GET /ach-relationships and
    # POST /transfers. Default to APPROVED so canonical happy-path tests work
    # without per-test wiring.
    svc.list_ach_relationships.return_value = [
        {"id": "alp_rel_xyz", "status": "APPROVED"},
    ]
    return svc


@pytest.fixture
def brokerage():
    return SimpleNamespace(
        id=uuid.uuid4(),
        alpaca_account_id="alpaca_acc_42",
        account_status="ACTIVE",
    )


@pytest.fixture
def patch_repos(mocker, brokerage):
    patches = SimpleNamespace(
        get_brokerage=mocker.patch(
            "app.services.funding.BrokerageAccountRepository.get_by_user_id",
            new_callable=AsyncMock,
            return_value=brokerage,
        ),
        get_by_plaid_item_id=mocker.patch(
            "app.services.funding.PlaidItemRepository.get_by_plaid_item_id",
            new_callable=AsyncMock,
            return_value=None,
        ),
        plaid_item_create=mocker.patch(
            "app.services.funding.PlaidItemRepository.create",
            new_callable=AsyncMock,
        ),
        rel_create=mocker.patch(
            "app.services.funding.AchRelationshipRepository.create",
            new_callable=AsyncMock,
        ),
        list_active=mocker.patch(
            "app.services.funding.AchRelationshipRepository.list_active_for_user",
            new_callable=AsyncMock,
            return_value=[],
        ),
        list_all=mocker.patch(
            "app.services.funding.AchRelationshipRepository.list_all_for_user",
            new_callable=AsyncMock,
            return_value=[],
        ),
        get_rel=mocker.patch(
            "app.services.funding.AchRelationshipRepository.get_by_id",
            new_callable=AsyncMock,
        ),
        mark_canceled=mocker.patch(
            "app.services.funding.AchRelationshipRepository.mark_canceled",
            new_callable=AsyncMock,
        ),
        find_active=mocker.patch(
            "app.services.funding._find_active_relationship_for_item",
            new_callable=AsyncMock,
            return_value=None,
        ),
    )
    return patches


@pytest.fixture
async def client(plaid_mock, alpaca_mock):
    app = _build_app()

    async def _override_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: TEST_USER_ID
    app.dependency_overrides[get_plaid] = lambda: plaid_mock
    app.dependency_overrides[get_alpaca] = lambda: alpaca_mock

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.fixture
async def unauthenticated_client(plaid_mock, alpaca_mock):
    """Client without the auth override — requests should 401."""
    app = _build_app()

    async def _override_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_plaid] = lambda: plaid_mock
    app.dependency_overrides[get_alpaca] = lambda: alpaca_mock

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rel(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        user_id=uuid.UUID(TEST_USER_ID),
        plaid_item_id=uuid.uuid4(),
        alpaca_relationship_id="alp_rel_xyz",
        institution_name="Platypus",
        account_mask="0000",
        account_type="CHECKING",
        nickname="My Checking",
        status="QUEUED",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_plaid_item():
    return SimpleNamespace(
        id=uuid.uuid4(),
        plaid_item_id="item_123",
    )


# ---------------------------------------------------------------------------
# POST /link-token
# ---------------------------------------------------------------------------


class TestLinkToken:
    async def test_returns_link_token(self, client, plaid_mock):
        response = await client.post("/v1/funding/link-token")
        assert response.status_code == 200
        assert response.json() == {"link_token": "link-sandbox-test"}
        plaid_mock.create_link_token.assert_awaited_once_with(user_id=TEST_USER_ID)


# ---------------------------------------------------------------------------
# POST /link-bank
# ---------------------------------------------------------------------------


class TestLinkBank:
    async def test_happy_path(self, client, patch_repos):
        created_item = _make_plaid_item()
        created_rel = _make_rel()
        patch_repos.plaid_item_create.return_value = created_item
        patch_repos.rel_create.return_value = created_rel

        response = await client.post(
            "/v1/funding/link-bank",
            json={
                "public_token": "public-abc",
                "account_id": "plaid_acct_1",
                "institution_name": "Platypus",
                "account_mask": "0000",
                "account_name": "Plaid Checking",
                "nickname": "My Checking",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["alpaca_relationship_id"] == "alp_rel_xyz"
        assert body["nickname"] == "My Checking"
        assert body["status"] == "QUEUED"

    async def test_account_not_active_returns_409(self, client, patch_repos):
        patch_repos.get_brokerage.return_value = None

        response = await client.post(
            "/v1/funding/link-bank",
            json={"public_token": "public-abc", "account_id": "plaid_acct_1"},
        )

        assert response.status_code == 409
        body = response.json()
        assert body["code"] == "ACCOUNT_NOT_ACTIVE"
        assert body["detail"] == {"account_status": None}

    async def test_duplicate_retry_returns_existing(
        self, client, patch_repos, plaid_mock, alpaca_mock
    ):
        existing_item = _make_plaid_item()
        existing_rel = _make_rel(plaid_item_id=existing_item.id)
        patch_repos.get_by_plaid_item_id.return_value = existing_item
        patch_repos.find_active.return_value = existing_rel

        response = await client.post(
            "/v1/funding/link-bank",
            json={"public_token": "public-abc", "account_id": "plaid_acct_1"},
        )

        assert response.status_code == 200
        assert response.json()["alpaca_relationship_id"] == existing_rel.alpaca_relationship_id
        plaid_mock.create_processor_token.assert_not_called()
        alpaca_mock.create_ach_relationship.assert_not_called()

    async def test_alpaca_409_returns_bank_already_linked(
        self, client, patch_repos, alpaca_mock
    ):
        alpaca_mock.create_ach_relationship.side_effect = AlpacaBrokerError(
            status_code=409,
            message="an ach relationship already exists for this account",
        )

        response = await client.post(
            "/v1/funding/link-bank",
            json={"public_token": "public-abc", "account_id": "plaid_acct_1"},
        )

        assert response.status_code == 409
        assert response.json()["code"] == "BANK_ALREADY_LINKED"


# ---------------------------------------------------------------------------
# GET /ach-relationships
# ---------------------------------------------------------------------------


class TestListAchRelationships:
    async def test_returns_only_active(self, client, patch_repos, alpaca_mock):
        patch_repos.list_active.return_value = [
            _make_rel(alpaca_relationship_id="alp_1", status="APPROVED")
        ]
        alpaca_mock.list_ach_relationships.return_value = [
            {"id": "alp_1", "status": "APPROVED"}
        ]

        response = await client.get("/v1/funding/ach-relationships")

        assert response.status_code == 200
        body = response.json()
        assert "relationships" in body
        assert len(body["relationships"]) == 1
        assert body["relationships"][0]["alpaca_relationship_id"] == "alp_1"

    async def test_refreshes_drifted_status_from_alpaca(
        self, client, patch_repos, alpaca_mock
    ):
        # Local says QUEUED, Alpaca now says APPROVED. Response reflects the
        # refreshed value — this is the whole point of the refresh-on-read.
        rel = _make_rel(alpaca_relationship_id="alp_drift", status="QUEUED")
        patch_repos.list_active.return_value = [rel]
        alpaca_mock.list_ach_relationships.return_value = [
            {"id": "alp_drift", "status": "APPROVED"}
        ]

        response = await client.get("/v1/funding/ach-relationships")

        assert response.status_code == 200
        assert response.json()["relationships"][0]["status"] == "APPROVED"
        alpaca_mock.list_ach_relationships.assert_awaited_once_with("alpaca_acc_42")


# ---------------------------------------------------------------------------
# DELETE /ach-relationships/{id}
# ---------------------------------------------------------------------------


class TestDeleteAchRelationship:
    async def test_204_and_marks_canceled(self, client, patch_repos, alpaca_mock):
        rel = _make_rel()
        patch_repos.get_rel.return_value = rel

        response = await client.delete(f"/v1/funding/ach-relationships/{rel.id}")

        assert response.status_code == 204
        alpaca_mock.delete_ach_relationship.assert_awaited_once_with(
            "alpaca_acc_42", rel.alpaca_relationship_id
        )
        patch_repos.mark_canceled.assert_awaited_once_with(
            patch_repos.mark_canceled.call_args.args[0], rel.id
        )


# ---------------------------------------------------------------------------
# POST /transfers
# ---------------------------------------------------------------------------


class TestCreateTransfer:
    async def test_sends_ach_and_immediate_to_alpaca(
        self, client, patch_repos, alpaca_mock
    ):
        rel = _make_rel()
        patch_repos.get_rel.return_value = rel

        response = await client.post(
            "/v1/funding/transfers",
            json={
                "relationship_id": str(rel.id),
                "amount": "500.00",
                "direction": "INCOMING",
            },
        )

        assert response.status_code == 200
        alpaca_mock.create_transfer.assert_awaited_once_with(
            "alpaca_acc_42",
            relationship_id="alp_rel_xyz",
            amount="500.00",
            direction="INCOMING",
        )

    async def test_negative_amount_422(self, client, patch_repos):
        response = await client.post(
            "/v1/funding/transfers",
            json={
                "relationship_id": str(uuid.uuid4()),
                "amount": "-10",
                "direction": "INCOMING",
            },
        )

        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_ERROR"

    async def test_invalid_direction_422(self, client):
        response = await client.post(
            "/v1/funding/transfers",
            json={
                "relationship_id": str(uuid.uuid4()),
                "amount": "10",
                "direction": "SIDEWAYS",
            },
        )

        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_ERROR"

    async def test_queued_relationship_returns_not_approved(
        self, client, patch_repos, alpaca_mock
    ):
        rel = _make_rel(status="QUEUED")
        patch_repos.get_rel.return_value = rel
        alpaca_mock.list_ach_relationships.return_value = [
            {"id": "alp_rel_xyz", "status": "QUEUED"}
        ]

        response = await client.post(
            "/v1/funding/transfers",
            json={
                "relationship_id": str(rel.id),
                "amount": "10",
                "direction": "INCOMING",
            },
        )

        assert response.status_code == 409
        body = response.json()
        assert body["code"] == "RELATIONSHIP_NOT_APPROVED"
        assert body["detail"] == {"status": "QUEUED"}
        alpaca_mock.create_transfer.assert_not_called()

    async def test_cancel_requested_returns_canceled(
        self, client, patch_repos, alpaca_mock
    ):
        rel = _make_rel(status="QUEUED")
        patch_repos.get_rel.return_value = rel
        alpaca_mock.list_ach_relationships.return_value = [
            {"id": "alp_rel_xyz", "status": "CANCEL_REQUESTED"}
        ]

        response = await client.post(
            "/v1/funding/transfers",
            json={
                "relationship_id": str(rel.id),
                "amount": "10",
                "direction": "INCOMING",
            },
        )

        assert response.status_code == 409
        assert response.json()["code"] == "RELATIONSHIP_CANCELED"
        alpaca_mock.create_transfer.assert_not_called()


# ---------------------------------------------------------------------------
# GET /transfers
# ---------------------------------------------------------------------------


class TestListTransfers:
    async def test_merges_bank_for_canceled_relationship(
        self, client, patch_repos, alpaca_mock
    ):
        canceled_rel = _make_rel(
            alpaca_relationship_id="alp_canceled",
            nickname="Old Savings",
            account_mask="9999",
            institution_name="Ducky Bank",
            status="CANCELED",
        )
        patch_repos.list_all.return_value = [canceled_rel]
        alpaca_mock.list_transfers.return_value = [
            {
                "id": "t1",
                "relationship_id": "alp_canceled",
                "status": "COMPLETE",
                "amount": "100.00",
                "direction": "INCOMING",
                "created_at": "2026-01-02T03:04:05Z",
            }
        ]

        response = await client.get("/v1/funding/transfers")

        assert response.status_code == 200
        body = response.json()
        assert body["transfers"][0]["bank"]["nickname"] == "Old Savings"
        assert body["transfers"][0]["bank"]["account_mask"] == "9999"

    async def test_rejects_limit_over_100(self, client, patch_repos):
        response = await client.get("/v1/funding/transfers?limit=101")
        assert response.status_code == 422

    async def test_default_limit_is_50(self, client, patch_repos, alpaca_mock):
        await client.get("/v1/funding/transfers")
        alpaca_mock.list_transfers.assert_awaited_once_with(
            "alpaca_acc_42", limit=50, offset=0
        )

    async def test_exposes_reason_on_returned_transfer(
        self, client, patch_repos, alpaca_mock
    ):
        # RETURNED (ACH chargeback) is the state where `reason` actually matters —
        # users need to know WHY their deposit got clawed back days later.
        patch_repos.list_all.return_value = []
        alpaca_mock.list_transfers.return_value = [
            {
                "id": "t_returned",
                "relationship_id": "alp_rel_xyz",
                "status": "RETURNED",
                "amount": "500.00",
                "direction": "INCOMING",
                "created_at": "2026-04-18T18:00:00Z",
                "reason": "R01 Insufficient funds",
            }
        ]

        response = await client.get("/v1/funding/transfers")

        assert response.status_code == 200
        body = response.json()
        assert body["transfers"][0]["reason"] == "R01 Insufficient funds"
        assert body["transfers"][0]["status"] == "RETURNED"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class TestAuth:
    async def test_link_token_requires_auth(self, unauthenticated_client):
        response = await unauthenticated_client.post("/v1/funding/link-token")
        assert response.status_code == 401
        assert response.json()["code"] == "AUTHENTICATION_ERROR"

    async def test_link_bank_requires_auth(self, unauthenticated_client):
        response = await unauthenticated_client.post(
            "/v1/funding/link-bank",
            json={"public_token": "x", "account_id": "y"},
        )
        assert response.status_code == 401

    async def test_list_relationships_requires_auth(self, unauthenticated_client):
        response = await unauthenticated_client.get("/v1/funding/ach-relationships")
        assert response.status_code == 401

    async def test_delete_relationship_requires_auth(self, unauthenticated_client):
        response = await unauthenticated_client.delete(
            f"/v1/funding/ach-relationships/{uuid.uuid4()}"
        )
        assert response.status_code == 401

    async def test_create_transfer_requires_auth(self, unauthenticated_client):
        response = await unauthenticated_client.post(
            "/v1/funding/transfers",
            json={
                "relationship_id": str(uuid.uuid4()),
                "amount": "10",
                "direction": "INCOMING",
            },
        )
        assert response.status_code == 401

    async def test_list_transfers_requires_auth(self, unauthenticated_client):
        response = await unauthenticated_client.get("/v1/funding/transfers")
        assert response.status_code == 401
