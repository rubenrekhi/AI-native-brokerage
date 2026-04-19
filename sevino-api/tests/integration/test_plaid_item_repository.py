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


class TestUniqueConstraint:
    async def test_duplicate_plaid_item_id_raises_integrity_error(
        self, db_session: AsyncSession, test_user
    ):
        await _make_item(db_session, test_user, plaid_item_id="item_dup")

        with pytest.raises(IntegrityError):
            await _make_item(db_session, test_user, plaid_item_id="item_dup")
