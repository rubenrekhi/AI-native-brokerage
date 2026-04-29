"""Integration tests for OrderEventRepository against real local Postgres."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.order_event import (
    TERMINAL_ORDER_STATUSES,
    OrderEventRepository,
)
from tests.integration.conftest import _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync,
    reason="Local Supabase Postgres not available (run `make infra`)",
)


@pytest.fixture
async def brokerage_account(db_session: AsyncSession, test_user) -> str:
    """Create a brokerage_accounts row for the test user, return its
    alpaca_account_id."""
    alpaca_account_id = f"alpaca_{uuid.uuid4()}"
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
            "id": uuid.uuid4(),
            "user_id": test_user,
            "alpaca_id": alpaca_account_id,
        },
    )
    await db_session.flush()
    return alpaca_account_id


async def _make_order(
    db_session: AsyncSession,
    user_id: uuid.UUID,
    **overrides,
):
    defaults = dict(
        user_id=user_id,
        alpaca_order_id=f"alp_ord_{uuid.uuid4()}",
        symbol="AAPL",
        side="buy",
        order_type="market",
        status="new",
    )
    defaults.update(overrides)
    return await OrderEventRepository.create(db_session, **defaults)


class TestCreate:
    async def test_inserts_row_and_returns_orm_instance(
        self, db_session: AsyncSession, test_user
    ):
        order = await OrderEventRepository.create(
            db_session,
            user_id=test_user,
            alpaca_order_id="alp_ord_create",
            symbol="TSLA",
            side="buy",
            order_type="limit",
            status="new",
            qty=Decimal("3"),
            limit_price=Decimal("250.50"),
        )

        assert order.id is not None
        assert order.user_id == test_user
        assert order.alpaca_order_id == "alp_ord_create"
        assert order.symbol == "TSLA"
        assert order.side == "buy"
        assert order.order_type == "limit"
        assert order.status == "new"
        assert order.qty == Decimal("3")
        assert order.limit_price == Decimal("250.50")
        assert order.notional is None
        assert order.conversation_id is None

    async def test_persists_to_db(
        self, db_session: AsyncSession, test_user
    ):
        order = await _make_order(
            db_session, test_user, alpaca_order_id="alp_ord_persist"
        )

        row = (
            await db_session.execute(
                text("SELECT alpaca_order_id FROM order_events WHERE id = :id"),
                {"id": order.id},
            )
        ).scalar_one()
        assert row == "alp_ord_persist"


class TestGetByIdForUser:
    async def test_returns_order_for_correct_user(
        self, db_session: AsyncSession, test_user
    ):
        order = await _make_order(db_session, test_user)

        found = await OrderEventRepository.get_by_id_for_user(
            db_session, order.id, test_user
        )
        assert found is not None
        assert found.id == order.id

    async def test_returns_none_for_wrong_user(
        self, db_session: AsyncSession, test_user, make_extra_user
    ):
        order = await _make_order(db_session, test_user)
        other_user = await make_extra_user()

        found = await OrderEventRepository.get_by_id_for_user(
            db_session, order.id, other_user
        )
        assert found is None

    async def test_returns_none_for_unknown_order_id(
        self, db_session: AsyncSession, test_user
    ):
        found = await OrderEventRepository.get_by_id_for_user(
            db_session, uuid.uuid4(), test_user
        )
        assert found is None


class TestGetByAlpacaOrderId:
    async def test_returns_row_when_present(
        self, db_session: AsyncSession, test_user
    ):
        order = await _make_order(
            db_session, test_user, alpaca_order_id="alp_ord_lookup"
        )

        found = await OrderEventRepository.get_by_alpaca_order_id(
            db_session, "alp_ord_lookup"
        )
        assert found is not None
        assert found.id == order.id

    async def test_returns_none_for_unknown_id(
        self, db_session: AsyncSession
    ):
        found = await OrderEventRepository.get_by_alpaca_order_id(
            db_session, "alp_ord_missing"
        )
        assert found is None


class TestGetOpenWithAlpacaAccountId:
    async def test_returns_open_orders_with_account_id(
        self,
        db_session: AsyncSession,
        test_user,
        brokerage_account,
    ):
        open_order = await _make_order(db_session, test_user, status="new")

        rows = await OrderEventRepository.get_open_with_alpaca_account_id(
            db_session
        )

        ids = {(row.order.id, row.alpaca_account_id) for row in rows}
        assert (open_order.id, brokerage_account) in ids

    async def test_excludes_terminal_orders(
        self,
        db_session: AsyncSession,
        test_user,
        brokerage_account,
    ):
        open_order = await _make_order(db_session, test_user, status="new")
        terminal_orders = [
            await _make_order(db_session, test_user, status=status)
            for status in TERMINAL_ORDER_STATUSES
        ]

        rows = await OrderEventRepository.get_open_with_alpaca_account_id(
            db_session
        )
        returned_ids = {row.order.id for row in rows}

        assert open_order.id in returned_ids
        for terminal in terminal_orders:
            assert terminal.id not in returned_ids

    async def test_excludes_orders_without_brokerage_account(
        self, db_session: AsyncSession, test_user
    ):
        # No brokerage_account fixture here — INNER JOIN should drop the
        # row.
        unattached_order = await _make_order(
            db_session, test_user, status="new"
        )

        rows = await OrderEventRepository.get_open_with_alpaca_account_id(
            db_session
        )
        returned_ids = {row.order.id for row in rows}
        assert unattached_order.id not in returned_ids

    async def test_includes_partially_filled_as_open(
        self,
        db_session: AsyncSession,
        test_user,
        brokerage_account,
    ):
        order = await _make_order(
            db_session, test_user, status="partially_filled"
        )

        rows = await OrderEventRepository.get_open_with_alpaca_account_id(
            db_session
        )
        returned_ids = {row.order.id for row in rows}
        assert order.id in returned_ids
