import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import IntegrityError

from app.exceptions import ConflictError, NotFoundError
from app.services.alpaca_broker import (
    AlpacaBrokerError,
    AlpacaBrokerUnavailableError,
)
from app.services.funding import FundingService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def brokerage():
    return SimpleNamespace(
        id=uuid.uuid4(),
        alpaca_account_id="alpaca_acc_42",
        account_status="ACTIVE",
    )


@pytest.fixture
def db():
    session = AsyncMock()
    session.rollback = AsyncMock()
    return session


@pytest.fixture
def plaid():
    svc = AsyncMock()
    svc.exchange_public_token.return_value = ("access-sandbox-abc", "item_123")
    svc.create_processor_token.return_value = "processor-sandbox-abc"
    svc.create_link_token.return_value = "link-sandbox-abc"
    return svc


@pytest.fixture
def alpaca():
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
    }
    svc.list_transfers.return_value = []
    return svc


def _make_rel(user_id, **overrides):
    defaults = dict(
        id=uuid.uuid4(),
        user_id=user_id,
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


def _make_plaid_item(user_id, **overrides):
    defaults = dict(
        id=uuid.uuid4(),
        user_id=user_id,
        plaid_item_id="item_123",
        plaid_access_token="ciphertext",
        plaid_account_id="plaid_acct_1",
        institution_name="Platypus",
        account_mask="0000",
        account_name="Plaid Checking",
        status="active",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.fixture
def patch_repos(mocker, brokerage):
    """Patch all repository methods + the active-relationship helper by default.

    Tests override individual return values / side effects as needed.
    """
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


# ---------------------------------------------------------------------------
# link_bank
# ---------------------------------------------------------------------------


class TestLinkBankHappyPath:
    async def test_calls_in_expected_order(
        self, db, plaid, alpaca, patch_repos, user_id, brokerage
    ):
        created_item = _make_plaid_item(user_id)
        created_rel = _make_rel(user_id)
        patch_repos.plaid_item_create.return_value = created_item
        patch_repos.rel_create.return_value = created_rel

        result = await FundingService.link_bank(
            db,
            plaid=plaid,
            alpaca=alpaca,
            user_id=user_id,
            public_token="public-abc",
            account_id="plaid_acct_1",
            institution_name="Platypus",
            account_mask="0000",
            account_name="Plaid Checking",
            nickname="My Checking",
        )

        assert result is created_rel

        plaid.exchange_public_token.assert_awaited_once_with(public_token="public-abc")
        plaid.create_processor_token.assert_awaited_once_with(
            access_token="access-sandbox-abc", account_id="plaid_acct_1"
        )
        alpaca.create_ach_relationship.assert_awaited_once_with(
            brokerage.alpaca_account_id, processor_token="processor-sandbox-abc"
        )
        patch_repos.plaid_item_create.assert_awaited_once()
        patch_repos.rel_create.assert_awaited_once()

        rel_kwargs = patch_repos.rel_create.call_args.kwargs
        assert rel_kwargs["alpaca_relationship_id"] == "alp_rel_xyz"
        assert rel_kwargs["brokerage_account_id"] == brokerage.id
        assert rel_kwargs["plaid_item_id"] == created_item.id
        assert rel_kwargs["status"] == "QUEUED"
        assert rel_kwargs["nickname"] == "My Checking"


class TestLinkBankIdempotency:
    async def test_fast_path_returns_existing_relationship(
        self, db, plaid, alpaca, patch_repos, user_id
    ):
        existing_item = _make_plaid_item(user_id)
        existing_rel = _make_rel(user_id, plaid_item_id=existing_item.id)
        patch_repos.get_by_plaid_item_id.return_value = existing_item
        patch_repos.find_active.return_value = existing_rel

        result = await FundingService.link_bank(
            db,
            plaid=plaid,
            alpaca=alpaca,
            user_id=user_id,
            public_token="public-abc",
            account_id="plaid_acct_1",
        )

        assert result is existing_rel
        plaid.create_processor_token.assert_not_called()
        alpaca.create_ach_relationship.assert_not_called()
        patch_repos.plaid_item_create.assert_not_called()
        patch_repos.rel_create.assert_not_called()

    async def test_race_path_integrity_error_returns_existing(
        self, db, plaid, alpaca, patch_repos, user_id
    ):
        existing_item = _make_plaid_item(user_id)
        existing_rel = _make_rel(user_id, plaid_item_id=existing_item.id)

        patch_repos.get_by_plaid_item_id.side_effect = [None, existing_item]
        patch_repos.find_active.return_value = existing_rel
        patch_repos.plaid_item_create.side_effect = IntegrityError("stmt", {}, Exception())

        result = await FundingService.link_bank(
            db,
            plaid=plaid,
            alpaca=alpaca,
            user_id=user_id,
            public_token="public-abc",
            account_id="plaid_acct_1",
        )

        assert result is existing_rel
        db.rollback.assert_awaited()
        patch_repos.rel_create.assert_not_called()


class TestLinkBankAccountGate:
    async def test_no_brokerage_row_raises_account_not_active(
        self, db, plaid, alpaca, patch_repos, user_id
    ):
        patch_repos.get_brokerage.return_value = None

        with pytest.raises(ConflictError) as info:
            await FundingService.link_bank(
                db,
                plaid=plaid,
                alpaca=alpaca,
                user_id=user_id,
                public_token="public-abc",
                account_id="plaid_acct_1",
            )

        assert info.value.code == "ACCOUNT_NOT_ACTIVE"
        assert info.value.detail == {"account_status": None}
        plaid.exchange_public_token.assert_not_called()
        alpaca.create_ach_relationship.assert_not_called()

    async def test_submitted_brokerage_raises_account_not_active(
        self, db, plaid, alpaca, patch_repos, brokerage, user_id
    ):
        brokerage.account_status = "SUBMITTED"
        patch_repos.get_brokerage.return_value = brokerage

        with pytest.raises(ConflictError) as info:
            await FundingService.link_bank(
                db,
                plaid=plaid,
                alpaca=alpaca,
                user_id=user_id,
                public_token="public-abc",
                account_id="plaid_acct_1",
            )

        assert info.value.code == "ACCOUNT_NOT_ACTIVE"
        assert info.value.detail == {"account_status": "SUBMITTED"}


class TestLinkBankAlpacaConflict:
    async def test_409_raises_bank_already_linked(
        self, db, plaid, alpaca, patch_repos, user_id
    ):
        alpaca.create_ach_relationship.side_effect = AlpacaBrokerError(
            status_code=409, message="duplicate"
        )

        with pytest.raises(ConflictError) as info:
            await FundingService.link_bank(
                db,
                plaid=plaid,
                alpaca=alpaca,
                user_id=user_id,
                public_token="public-abc",
                account_id="plaid_acct_1",
            )

        assert info.value.code == "BANK_ALREADY_LINKED"
        patch_repos.plaid_item_create.assert_not_called()

    async def test_non_409_bubbles_up(
        self, db, plaid, alpaca, patch_repos, user_id
    ):
        alpaca.create_ach_relationship.side_effect = AlpacaBrokerError(
            status_code=500, message="server error"
        )

        with pytest.raises(AlpacaBrokerError):
            await FundingService.link_bank(
                db,
                plaid=plaid,
                alpaca=alpaca,
                user_id=user_id,
                public_token="public-abc",
                account_id="plaid_acct_1",
            )


# ---------------------------------------------------------------------------
# create_transfer
# ---------------------------------------------------------------------------


class TestCreateTransfer:
    async def test_decimal_serialized_and_relationship_resolved(
        self, db, alpaca, patch_repos, user_id, brokerage
    ):
        rel = _make_rel(user_id, alpaca_relationship_id="alp_rel_xyz")
        patch_repos.get_rel.return_value = rel

        result = await FundingService.create_transfer(
            db,
            alpaca=alpaca,
            user_id=user_id,
            relationship_pk=rel.id,
            amount=Decimal("500.00"),
            direction="INCOMING",
        )

        alpaca.create_transfer.assert_awaited_once_with(
            brokerage.alpaca_account_id,
            relationship_id="alp_rel_xyz",
            amount="500.00",
            direction="INCOMING",
        )
        assert result["id"] == "xfer_1"

    async def test_rejects_other_user_relationship(
        self, db, alpaca, patch_repos, user_id
    ):
        other_users_rel = _make_rel(uuid.uuid4())
        patch_repos.get_rel.return_value = other_users_rel

        with pytest.raises(NotFoundError):
            await FundingService.create_transfer(
                db,
                alpaca=alpaca,
                user_id=user_id,
                relationship_pk=other_users_rel.id,
                amount=Decimal("10"),
                direction="INCOMING",
            )
        alpaca.create_transfer.assert_not_called()

    async def test_canceled_relationship_raises_conflict(
        self, db, alpaca, patch_repos, user_id
    ):
        rel = _make_rel(user_id, status="CANCELED")
        patch_repos.get_rel.return_value = rel

        with pytest.raises(ConflictError) as info:
            await FundingService.create_transfer(
                db,
                alpaca=alpaca,
                user_id=user_id,
                relationship_pk=rel.id,
                amount=Decimal("10"),
                direction="INCOMING",
            )
        assert info.value.code == "RELATIONSHIP_CANCELED"
        alpaca.create_transfer.assert_not_called()


# ---------------------------------------------------------------------------
# unlink_bank
# ---------------------------------------------------------------------------


class TestUnlinkBank:
    async def test_calls_alpaca_first_then_soft_deletes(
        self, db, alpaca, patch_repos, user_id, brokerage
    ):
        rel = _make_rel(user_id)
        patch_repos.get_rel.return_value = rel
        call_order: list[str] = []
        alpaca.delete_ach_relationship.side_effect = (
            lambda *a, **k: call_order.append("alpaca") or None
        )
        patch_repos.mark_canceled.side_effect = (
            lambda *a, **k: call_order.append("db") or None
        )

        await FundingService.unlink_bank(
            db, alpaca=alpaca, user_id=user_id, relationship_pk=rel.id
        )

        assert call_order == ["alpaca", "db"]
        alpaca.delete_ach_relationship.assert_awaited_once_with(
            brokerage.alpaca_account_id, rel.alpaca_relationship_id
        )
        patch_repos.mark_canceled.assert_awaited_once_with(db, rel.id)

    async def test_404_still_soft_deletes(
        self, db, alpaca, patch_repos, user_id
    ):
        rel = _make_rel(user_id)
        patch_repos.get_rel.return_value = rel
        alpaca.delete_ach_relationship.side_effect = NotFoundError("gone")

        await FundingService.unlink_bank(
            db, alpaca=alpaca, user_id=user_id, relationship_pk=rel.id
        )

        patch_repos.mark_canceled.assert_awaited_once_with(db, rel.id)

    async def test_5xx_does_not_soft_delete(
        self, db, alpaca, patch_repos, user_id
    ):
        rel = _make_rel(user_id)
        patch_repos.get_rel.return_value = rel
        alpaca.delete_ach_relationship.side_effect = AlpacaBrokerUnavailableError("down")

        with pytest.raises(AlpacaBrokerUnavailableError):
            await FundingService.unlink_bank(
                db, alpaca=alpaca, user_id=user_id, relationship_pk=rel.id
            )

        patch_repos.mark_canceled.assert_not_called()

    async def test_rejects_other_users_relationship(
        self, db, alpaca, patch_repos, user_id
    ):
        other_rel = _make_rel(uuid.uuid4())
        patch_repos.get_rel.return_value = other_rel

        with pytest.raises(NotFoundError):
            await FundingService.unlink_bank(
                db, alpaca=alpaca, user_id=user_id, relationship_pk=other_rel.id
            )
        alpaca.delete_ach_relationship.assert_not_called()


# ---------------------------------------------------------------------------
# list_transfers
# ---------------------------------------------------------------------------


class TestListTransfers:
    async def test_merges_nickname_including_canceled(
        self, db, alpaca, patch_repos, user_id
    ):
        active_rel = _make_rel(
            user_id,
            alpaca_relationship_id="alp_active",
            nickname="Checking",
            account_mask="1234",
            institution_name="Platypus",
        )
        canceled_rel = _make_rel(
            user_id,
            alpaca_relationship_id="alp_canceled",
            nickname="Old Savings",
            account_mask="9999",
            institution_name="Ducky Bank",
            status="CANCELED",
        )
        patch_repos.list_all.return_value = [active_rel, canceled_rel]
        alpaca.list_transfers.return_value = [
            {"id": "t1", "relationship_id": "alp_active", "amount": "100"},
            {"id": "t2", "relationship_id": "alp_canceled", "amount": "50"},
            {"id": "t3", "relationship_id": "alp_unknown", "amount": "25"},
        ]

        transfers = await FundingService.list_transfers(
            db, alpaca=alpaca, user_id=user_id, limit=50, offset=0
        )

        assert transfers[0]["bank"]["nickname"] == "Checking"
        assert transfers[1]["bank"]["nickname"] == "Old Savings"
        assert transfers[2]["bank"] is None
        alpaca.list_transfers.assert_awaited_once_with(
            "alpaca_acc_42", limit=50, offset=0
        )


# ---------------------------------------------------------------------------
# create_link_token
# ---------------------------------------------------------------------------


class TestCreateLinkToken:
    async def test_passes_user_id_as_string(self, plaid, user_id):
        token = await FundingService.create_link_token(plaid=plaid, user_id=user_id)

        assert token == "link-sandbox-abc"
        plaid.create_link_token.assert_awaited_once_with(user_id=str(user_id))
