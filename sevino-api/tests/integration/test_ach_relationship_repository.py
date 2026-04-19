"""Integration tests for AchRelationshipRepository against real local Postgres."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.ach_relationship import AchRelationshipRepository
from tests.integration.conftest import _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync,
    reason="Local Supabase Postgres not available (run `make infra`)",
)


@pytest.fixture
async def brokerage_account(db_session: AsyncSession, test_user) -> uuid.UUID:
    """Create a brokerage_accounts row for the test user and return its id."""
    account_id = uuid.uuid4()
    await db_session.execute(
        text(
            """
            INSERT INTO brokerage_accounts (
                id, user_id, alpaca_account_id, account_status, kyc_submitted_at
            ) VALUES (
                :id, :user_id, :alpaca_id, 'ACTIVE', now()
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


async def _make_rel(
    db_session: AsyncSession,
    user_id: uuid.UUID,
    brokerage_account_id: uuid.UUID,
    **overrides,
):
    defaults = dict(
        user_id=user_id,
        brokerage_account_id=brokerage_account_id,
        plaid_item_id=None,
        alpaca_relationship_id=f"alp_rel_{uuid.uuid4()}",
        institution_name="First Platypus Bank",
        account_mask="0000",
        account_type="CHECKING",
        nickname="Test Checking",
    )
    defaults.update(overrides)
    return await AchRelationshipRepository.create(db_session, **defaults)


class TestCreate:
    async def test_inserts_with_default_queued_status(
        self, db_session: AsyncSession, test_user, brokerage_account
    ):
        rel = await _make_rel(db_session, test_user, brokerage_account)
        assert rel.status == "QUEUED"


class TestLookup:
    async def test_get_by_alpaca_id(
        self, db_session: AsyncSession, test_user, brokerage_account
    ):
        rel = await _make_rel(
            db_session,
            test_user,
            brokerage_account,
            alpaca_relationship_id="alp_rel_lookup",
        )

        found = await AchRelationshipRepository.get_by_alpaca_id(
            db_session, "alp_rel_lookup"
        )
        assert found is not None
        assert found.id == rel.id

    async def test_get_by_alpaca_id_unknown_returns_none(
        self, db_session: AsyncSession
    ):
        found = await AchRelationshipRepository.get_by_alpaca_id(
            db_session, "alp_rel_missing"
        )
        assert found is None


class TestListFiltering:
    async def test_list_active_excludes_canceled(
        self, db_session: AsyncSession, test_user, brokerage_account
    ):
        active = await _make_rel(db_session, test_user, brokerage_account)
        canceled = await _make_rel(db_session, test_user, brokerage_account)
        await AchRelationshipRepository.mark_canceled(db_session, canceled.id)

        rows = await AchRelationshipRepository.list_active_for_user(
            db_session, test_user
        )
        ids = {r.id for r in rows}
        assert active.id in ids
        assert canceled.id not in ids

    async def test_list_all_includes_canceled(
        self, db_session: AsyncSession, test_user, brokerage_account
    ):
        active = await _make_rel(db_session, test_user, brokerage_account)
        canceled = await _make_rel(db_session, test_user, brokerage_account)
        await AchRelationshipRepository.mark_canceled(db_session, canceled.id)

        rows = await AchRelationshipRepository.list_all_for_user(
            db_session, test_user
        )
        ids = {r.id for r in rows}
        assert active.id in ids
        assert canceled.id in ids


class TestSoftDelete:
    async def test_mark_canceled_preserves_row(
        self, db_session: AsyncSession, test_user, brokerage_account
    ):
        rel = await _make_rel(
            db_session,
            test_user,
            brokerage_account,
            nickname="Keep My Nickname",
            account_mask="1234",
        )

        pre_count = (
            await db_session.execute(
                text("SELECT count(*) FROM ach_relationships WHERE id = :id"),
                {"id": rel.id},
            )
        ).scalar_one()

        await AchRelationshipRepository.mark_canceled(db_session, rel.id)

        post_count = (
            await db_session.execute(
                text("SELECT count(*) FROM ach_relationships WHERE id = :id"),
                {"id": rel.id},
            )
        ).scalar_one()

        assert pre_count == 1 and post_count == 1

        refreshed = await AchRelationshipRepository.get_by_id(db_session, rel.id)
        assert refreshed is not None
        assert refreshed.status == "CANCELED"
        assert refreshed.nickname == "Keep My Nickname"
        assert refreshed.account_mask == "1234"
