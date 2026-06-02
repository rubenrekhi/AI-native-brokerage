"""Integration tests for /v1/trading/* routes against a real local Postgres.

Mounts the full app, uses the `authenticated_db_client` fixture (real DB
session, mocked auth), and stubs `app.state.alpaca` so order placement
and cancellation never touch the network.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.repositories.order_event import OrderEventRepository
from tests.integration.conftest import _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync,
    reason="Local Supabase Postgres not available (run `make infra`)",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def alpaca_mock():
    svc = AsyncMock()
    svc.create_order.return_value = {
        "id": "alp_ord_route",
        "client_order_id": "client-uuid",
        "symbol": "TSLA",
        "side": "buy",
        "type": "market",
        "qty": "10",
        "notional": None,
        "limit_price": None,
        "status": "accepted",
        "submitted_at": "2026-04-28T15:30:00Z",
    }
    svc.cancel_order.return_value = None
    svc.get_position.return_value = {"symbol": "TSLA", "qty": "5"}
    return svc


@pytest.fixture(autouse=True)
def patch_alpaca_state(monkeypatch, alpaca_mock):
    """Replace `app.state.alpaca` for the duration of the test."""
    monkeypatch.setattr(app.state, "alpaca", alpaca_mock, raising=False)


@pytest.fixture
async def active_brokerage(db_session: AsyncSession, test_user):
    """Insert an ACTIVE brokerage_accounts row for the test user."""
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


@pytest.fixture
async def tradeable_asset(db_session: AsyncSession):
    """Insert a tradeable TSLA asset so symbol lookup succeeds."""
    await db_session.execute(
        text(
            """
            INSERT INTO assets (symbol, name, exchange, tradeable, synced_at)
            VALUES ('TSLA', 'Tesla, Inc.', 'NASDAQ', TRUE, now())
            ON CONFLICT (symbol) DO UPDATE SET tradeable = TRUE
            """
        )
    )
    await db_session.flush()


@pytest.fixture
async def non_fractionable_asset(db_session: AsyncSession):
    """Insert a tradeable-but-not-fractionable asset (whole shares only)."""
    await db_session.execute(
        text(
            """
            INSERT INTO assets (
                symbol, name, exchange, tradeable, fractionable, synced_at
            ) VALUES (
                'ILLQ', 'Illiquid Co', 'NASDAQ', TRUE, FALSE, now()
            )
            ON CONFLICT (symbol) DO UPDATE
            SET tradeable = TRUE, fractionable = FALSE
            """
        )
    )
    await db_session.flush()


# ---------------------------------------------------------------------------
# POST /v1/trading/orders
# ---------------------------------------------------------------------------


class TestPlaceOrderRoute:
    async def test_201_returns_place_order_response(
        self,
        authenticated_db_client,
        active_brokerage,
        tradeable_asset,
        alpaca_mock,
    ):
        response = await authenticated_db_client.post(
            "/v1/trading/orders",
            json={
                "symbol": "TSLA",
                "side": "buy",
                "type": "market",
                "qty": "10",
            },
        )

        assert response.status_code == 201
        body = response.json()
        assert body["alpaca_order_id"] == "alp_ord_route"
        assert body["symbol"] == "TSLA"
        assert body["side"] == "buy"
        assert body["type"] == "market"
        assert body["time_in_force"] == "day"
        assert body["qty"] == "10"
        assert body["status"] == "accepted"
        # `id` is a UUID assigned by the DB.
        uuid.UUID(body["id"])
        alpaca_mock.create_order.assert_awaited_once()
        sent_account, sent_payload = alpaca_mock.create_order.call_args.args
        assert sent_account == active_brokerage
        assert sent_payload["symbol"] == "TSLA"
        assert sent_payload["time_in_force"] == "day"

    async def test_limit_order_uses_gtc(
        self,
        authenticated_db_client,
        active_brokerage,
        tradeable_asset,
        alpaca_mock,
    ):
        alpaca_mock.create_order.return_value = {
            **alpaca_mock.create_order.return_value,
            "type": "limit",
            "limit_price": "180.50",
        }

        response = await authenticated_db_client.post(
            "/v1/trading/orders",
            json={
                "symbol": "TSLA",
                "side": "buy",
                "type": "limit",
                "qty": "5",
                "limit_price": "180.50",
            },
        )

        assert response.status_code == 201
        assert response.json()["time_in_force"] == "gtc"
        sent_payload = alpaca_mock.create_order.call_args.args[1]
        assert sent_payload["time_in_force"] == "gtc"
        assert sent_payload["limit_price"] == "180.50"

    async def test_stop_order_uses_gtc_and_echoes_stop_price(
        self,
        authenticated_db_client,
        active_brokerage,
        tradeable_asset,
        alpaca_mock,
    ):
        alpaca_mock.create_order.return_value = {
            **alpaca_mock.create_order.return_value,
            "side": "sell",
            "type": "stop",
            "qty": "5",
            "stop_price": "170.00",
        }
        # Position fixture holds 5 shares, request 5 → sell allowed.

        response = await authenticated_db_client.post(
            "/v1/trading/orders",
            json={
                "symbol": "TSLA",
                "side": "sell",
                "type": "stop",
                "qty": "5",
                "stop_price": "170.00",
            },
        )

        assert response.status_code == 201
        body = response.json()
        assert body["type"] == "stop"
        assert body["time_in_force"] == "gtc"
        assert body["stop_price"] == "170.00"
        assert body["limit_price"] is None
        sent_payload = alpaca_mock.create_order.call_args.args[1]
        assert sent_payload["type"] == "stop"
        assert sent_payload["stop_price"] == "170.00"
        assert sent_payload["time_in_force"] == "gtc"
        assert "limit_price" not in sent_payload

    async def test_untradeable_symbol_returns_409(
        self, authenticated_db_client, active_brokerage
    ):
        # No asset row inserted → SYMBOL_NOT_TRADEABLE.
        response = await authenticated_db_client.post(
            "/v1/trading/orders",
            json={
                "symbol": "ZZZZ",
                "side": "buy",
                "type": "market",
                "qty": "1",
            },
        )

        assert response.status_code == 409
        assert response.json()["code"] == "SYMBOL_NOT_TRADEABLE"

    async def test_inactive_brokerage_returns_409(
        self, authenticated_db_client, tradeable_asset
    ):
        # No brokerage row → ACCOUNT_NOT_ACTIVE.
        response = await authenticated_db_client.post(
            "/v1/trading/orders",
            json={
                "symbol": "TSLA",
                "side": "buy",
                "type": "market",
                "qty": "1",
            },
        )

        assert response.status_code == 409
        assert response.json()["code"] == "ACCOUNT_NOT_ACTIVE"

    async def test_non_fractionable_asset_returns_409(
        self,
        authenticated_db_client,
        active_brokerage,
        non_fractionable_asset,
        alpaca_mock,
    ):
        response = await authenticated_db_client.post(
            "/v1/trading/orders",
            json={
                "symbol": "ILLQ",
                "side": "buy",
                "type": "market",
                "qty": "0.5",
            },
        )

        assert response.status_code == 409
        body = response.json()
        assert body["code"] == "ASSET_NOT_FRACTIONABLE"
        assert body["detail"] == {"symbol": "ILLQ"}
        alpaca_mock.create_order.assert_not_called()

    async def test_validation_error_returns_422(
        self, authenticated_db_client
    ):
        # Missing both qty and notional.
        response = await authenticated_db_client.post(
            "/v1/trading/orders",
            json={"symbol": "TSLA", "side": "buy", "type": "market"},
        )

        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_ERROR"

    async def test_requires_auth(self, client):
        response = await client.post(
            "/v1/trading/orders",
            json={
                "symbol": "TSLA",
                "side": "buy",
                "type": "market",
                "qty": "1",
            },
        )
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /v1/trading/orders/{id}
# ---------------------------------------------------------------------------


class TestGetOrderRoute:
    async def test_200_returns_order_detail(
        self, authenticated_db_client, db_session, test_user
    ):
        order = await OrderEventRepository.create(
            db_session,
            user_id=test_user,
            alpaca_order_id="alp_ord_get",
            symbol="TSLA",
            side="buy",
            order_type="market",
            status="filled",
            qty=Decimal("3"),
            submitted_at=datetime(2026, 4, 28, 15, 30, tzinfo=timezone.utc),
        )

        response = await authenticated_db_client.get(
            f"/v1/trading/orders/{order.id}"
        )

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == str(order.id)
        assert body["alpaca_order_id"] == "alp_ord_get"
        assert body["symbol"] == "TSLA"
        assert body["status"] == "filled"
        assert body["type"] == "market"
        assert body["time_in_force"] == "day"

    async def test_404_for_unknown_order(self, authenticated_db_client):
        response = await authenticated_db_client.get(
            f"/v1/trading/orders/{uuid.uuid4()}"
        )
        assert response.status_code == 404

    async def test_404_for_other_users_order(
        self, authenticated_db_client, db_session, make_extra_user
    ):
        other_user_id = await make_extra_user()

        order = await OrderEventRepository.create(
            db_session,
            user_id=other_user_id,
            alpaca_order_id="alp_ord_other",
            symbol="TSLA",
            side="buy",
            order_type="market",
            status="new",
            qty=Decimal("1"),
        )

        response = await authenticated_db_client.get(
            f"/v1/trading/orders/{order.id}"
        )
        assert response.status_code == 404

    async def test_requires_auth(self, client):
        response = await client.get(f"/v1/trading/orders/{uuid.uuid4()}")
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# DELETE /v1/trading/orders/{id}
# ---------------------------------------------------------------------------


class TestCancelOrderRoute:
    async def test_200_marks_pending_cancel(
        self,
        authenticated_db_client,
        db_session,
        test_user,
        active_brokerage,
        alpaca_mock,
    ):
        order = await OrderEventRepository.create(
            db_session,
            user_id=test_user,
            alpaca_order_id="alp_ord_cancel",
            symbol="TSLA",
            side="buy",
            order_type="market",
            status="new",
            qty=Decimal("1"),
        )

        response = await authenticated_db_client.delete(
            f"/v1/trading/orders/{order.id}"
        )

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == str(order.id)
        assert body["status"] == "pending_cancel"
        alpaca_mock.cancel_order.assert_awaited_once_with(
            active_brokerage, "alp_ord_cancel"
        )

    async def test_409_for_terminal_order(
        self,
        authenticated_db_client,
        db_session,
        test_user,
        active_brokerage,
        alpaca_mock,
    ):
        order = await OrderEventRepository.create(
            db_session,
            user_id=test_user,
            alpaca_order_id="alp_ord_filled",
            symbol="TSLA",
            side="buy",
            order_type="market",
            status="filled",
            qty=Decimal("1"),
        )

        response = await authenticated_db_client.delete(
            f"/v1/trading/orders/{order.id}"
        )

        assert response.status_code == 409
        assert response.json()["code"] == "ORDER_NOT_CANCELABLE"
        alpaca_mock.cancel_order.assert_not_called()

    async def test_requires_auth(self, client):
        response = await client.delete(f"/v1/trading/orders/{uuid.uuid4()}")
        assert response.status_code == 401
