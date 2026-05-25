"""Integration tests for PlaidItemRepository against real local Postgres."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.plaid_item import PlaidItemRepository
from tests.integration.conftest import TEST_USER_ID, _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync,
    reason="Local Supabase Postgres not available (run `make infra`)",
)

PLAINTEXT_TOKEN = "access-sandbox-abc123-plaintext-value"


async def _make_item(db_session: AsyncSession, user_id: uuid.UUID, **overrides):
    defaults = dict(
        user_id=user_id,
        plaid_item_id="item_abc_123",
        plaid_access_token_plaintext=PLAINTEXT_TOKEN,
        plaid_account_id="acct_xyz",
        institution_name="First Platypus Bank",
        account_mask="0000",
        account_name="Plaid Checking",
    )
    defaults.update(overrides)
    return await PlaidItemRepository.create(db_session, **defaults)


class TestCreateAndRoundTrip:
    async def test_creates_row_with_encrypted_token(
        self, db_session: AsyncSession, test_user
    ):
        item = await _make_item(db_session, test_user)

        raw = await db_session.execute(
            text("SELECT plaid_access_token FROM plaid_items WHERE id = :id"),
            {"id": item.id},
        )
        ciphertext = raw.scalar_one()

        assert ciphertext != PLAINTEXT_TOKEN
        assert PLAINTEXT_TOKEN not in ciphertext
        assert ciphertext.startswith("gAAAA")

    async def test_get_access_token_plaintext_returns_original(
        self, db_session: AsyncSession, test_user
    ):
        item = await _make_item(db_session, test_user)

        plaintext = await PlaidItemRepository.get_access_token_plaintext(
            db_session, item.id
        )

        assert plaintext == PLAINTEXT_TOKEN

    async def test_get_access_token_plaintext_missing_row_returns_none(
        self, db_session: AsyncSession, test_user
    ):
        result = await PlaidItemRepository.get_access_token_plaintext(
            db_session, uuid.uuid4()
        )
        assert result is None


class TestLookup:
    async def test_get_by_plaid_item_id_returns_row(
        self, db_session: AsyncSession, test_user
    ):
        item = await _make_item(db_session, test_user, plaid_item_id="item_lookup_1")

        found = await PlaidItemRepository.get_by_plaid_item_id(
            db_session, "item_lookup_1"
        )

        assert found is not None
        assert found.id == item.id

    async def test_get_by_plaid_item_id_unknown_returns_none(
        self, db_session: AsyncSession, test_user
    ):
        found = await PlaidItemRepository.get_by_plaid_item_id(
            db_session, "item_does_not_exist"
        )
        assert found is None


class TestMarkInactive:
    async def test_flips_status_without_deleting(
        self, db_session: AsyncSession, test_user
    ):
        item = await _make_item(db_session, test_user)
        assert item.status == "active"

        await PlaidItemRepository.mark_inactive(db_session, item.id)

        refreshed = await PlaidItemRepository.get_by_id(db_session, item.id)
        assert refreshed is not None
        assert refreshed.status == "inactive"


class TestMarkRequiresReauth:
    async def test_flips_status_and_returns_item(
        self, db_session: AsyncSession, test_user
    ):
        item = await _make_item(
            db_session, test_user, plaid_item_id="item_reauth_1"
        )
        assert item.status == "active"

        result = await PlaidItemRepository.mark_requires_reauth(
            db_session, "item_reauth_1"
        )

        assert result is not None
        assert result.id == item.id
        assert result.status == "requires_reauth"

        refreshed = await PlaidItemRepository.get_by_id(db_session, item.id)
        assert refreshed is not None
        assert refreshed.status == "requires_reauth"

    async def test_unknown_plaid_item_id_returns_none(
        self, db_session: AsyncSession, test_user
    ):
        result = await PlaidItemRepository.mark_requires_reauth(
            db_session, "item_does_not_exist"
        )
        assert result is None


class TestMarkActive:
    async def test_flips_requires_reauth_back_to_active(
        self, db_session: AsyncSession, test_user
    ):
        item = await _make_item(
            db_session, test_user, plaid_item_id="item_active_1"
        )
        await PlaidItemRepository.mark_requires_reauth(db_session, "item_active_1")

        await PlaidItemRepository.mark_active(db_session, item.id)

        refreshed = await PlaidItemRepository.get_by_id(db_session, item.id)
        assert refreshed is not None
        assert refreshed.status == "active"

    async def test_unknown_pk_does_not_touch_other_rows(
        self, db_session: AsyncSession, test_user
    ):
        sentinel = await _make_item(
            db_session, test_user, plaid_item_id="item_sentinel"
        )

        await PlaidItemRepository.mark_active(db_session, uuid.uuid4())

        refreshed = await PlaidItemRepository.get_by_id(db_session, sentinel.id)
        assert refreshed is not None
        assert refreshed.status == "active"


class TestUniqueConstraint:
    async def test_duplicate_plaid_item_id_raises_integrity_error(
        self, db_session: AsyncSession, test_user
    ):
        await _make_item(db_session, test_user, plaid_item_id="item_dup")

        with pytest.raises(IntegrityError):
            await _make_item(db_session, test_user, plaid_item_id="item_dup")


class TestSoftDeleteRuleOnParentDelete:
    """Deleting a PlaidItem must preserve child AchRelationship rows
    (soft-delete rule per plan Locked Decision #6)."""

    async def test_deleting_plaid_item_sets_ach_relationship_fk_to_null(
        self, db_session: AsyncSession, test_user
    ):
        from app.repositories.ach_relationship import AchRelationshipRepository

        # Brokerage account row (required NOT NULL FK on ach_relationships)
        brokerage_id = uuid.uuid4()
        await db_session.execute(
            text(
                """
                INSERT INTO brokerage_accounts (
                    id, user_id, alpaca_account_id, account_status, kyc_submitted_at
                ) VALUES (:id, :user_id, :alpaca_id, 'ACTIVE', now())
                """
            ),
            {
                "id": brokerage_id,
                "user_id": test_user,
                "alpaca_id": f"alpaca_{uuid.uuid4()}",
            },
        )
        await db_session.flush()

        item = await _make_item(
            db_session, test_user, plaid_item_id="item_parent_delete"
        )
        rel = await AchRelationshipRepository.create(
            db_session,
            user_id=test_user,
            brokerage_account_id=brokerage_id,
            plaid_item_id=item.id,
            alpaca_relationship_id=f"alp_{uuid.uuid4()}",
            institution_name="First Platypus Bank",
            account_mask="0000",
            account_type="CHECKING",
            nickname="Test Checking",
        )
        assert rel.plaid_item_id == item.id

        # Hard-delete the PlaidItem via the ORM
        await db_session.delete(item)
        await db_session.flush()

        # AchRelationship row must still exist with plaid_item_id now NULL
        result = await db_session.execute(
            text("SELECT plaid_item_id FROM ach_relationships WHERE id = :id"),
            {"id": rel.id},
        )
        row = result.fetchone()
        assert row is not None, (
            "AchRelationship row was hard-deleted (soft-delete rule violated)"
        )
        assert row[0] is None, f"plaid_item_id expected NULL, got {row[0]!r}"
