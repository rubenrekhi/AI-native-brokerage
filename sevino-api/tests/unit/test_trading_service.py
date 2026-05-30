"""Unit tests for TradingService — repos and Alpaca are patched/mocked."""

import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.exceptions import ConflictError, NotFoundError
from app.repositories.order_event import TERMINAL_ORDER_STATUSES
from app.schemas.trading import PlaceOrderRequest
from app.services.alpaca_broker import (
    AlpacaBrokerError,
    AlpacaBrokerUnavailableError,
)
from app.services.trading import TradingService, validate_trade_prerequisites

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
    session.flush = AsyncMock()
    return session


@pytest.fixture
def asset():
    return SimpleNamespace(symbol="TSLA", tradeable=True, fractionable=True)


@pytest.fixture
def alpaca():
    svc = AsyncMock()
    svc.create_order.return_value = {
        "id": "alp_ord_1",
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


def _make_order_event(user_id, **overrides):
    defaults = dict(
        id=uuid.uuid4(),
        user_id=user_id,
        alpaca_order_id="alp_ord_1",
        symbol="TSLA",
        side="buy",
        order_type="market",
        status="accepted",
        qty=Decimal("10"),
        notional=None,
        limit_price=None,
        filled_qty=None,
        filled_avg_price=None,
        submitted_at=None,
        filled_at=None,
        conversation_id=None,
        created_at=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.fixture
def patch_repos(mocker, brokerage, asset, user_id):
    patches = SimpleNamespace(
        get_brokerage=mocker.patch(
            "app.services.trading.BrokerageAccountRepository.get_by_user_id",
            new_callable=AsyncMock,
            return_value=brokerage,
        ),
        get_asset=mocker.patch(
            "app.services.trading.AssetRepository.get_by_symbol",
            new_callable=AsyncMock,
            return_value=asset,
        ),
        order_create=mocker.patch(
            "app.services.trading.OrderEventRepository.create",
            new_callable=AsyncMock,
            return_value=_make_order_event(user_id),
        ),
        get_order=mocker.patch(
            "app.services.trading.OrderEventRepository.get_by_id_for_user",
            new_callable=AsyncMock,
        ),
    )
    return patches


# ---------------------------------------------------------------------------
# place_order — happy paths
# ---------------------------------------------------------------------------


class TestPlaceOrderHappyPath:
    async def test_market_buy_by_qty(
        self, db, alpaca, patch_repos, user_id, brokerage
    ):
        request = PlaceOrderRequest(
            symbol="TSLA", side="buy", type="market", qty="10"
        )

        result = await TradingService.place_order(
            db, alpaca=alpaca, user_id=user_id, data=request
        )

        assert result is patch_repos.order_create.return_value
        alpaca.create_order.assert_awaited_once()
        account_id, payload = alpaca.create_order.call_args.args
        assert account_id == brokerage.alpaca_account_id
        assert payload["symbol"] == "TSLA"
        assert payload["side"] == "buy"
        assert payload["type"] == "market"
        assert payload["qty"] == "10"
        assert "notional" not in payload
        assert "limit_price" not in payload

    async def test_market_buy_by_notional(
        self, db, alpaca, patch_repos, user_id
    ):
        request = PlaceOrderRequest(
            symbol="TSLA", side="buy", type="market", notional="500.00"
        )

        await TradingService.place_order(
            db, alpaca=alpaca, user_id=user_id, data=request
        )

        payload = alpaca.create_order.call_args.args[1]
        assert payload["notional"] == "500.00"
        assert "qty" not in payload

    async def test_market_sell_by_qty_within_position(
        self, db, alpaca, patch_repos, user_id
    ):
        # Position fixture holds 5 shares, request 5 → allowed.
        request = PlaceOrderRequest(
            symbol="TSLA", side="sell", type="market", qty="5"
        )

        await TradingService.place_order(
            db, alpaca=alpaca, user_id=user_id, data=request
        )

        alpaca.get_position.assert_awaited_once_with("alpaca_acc_42", "TSLA")
        alpaca.create_order.assert_awaited_once()

    async def test_market_sell_by_notional_when_position_exists(
        self, db, alpaca, patch_repos, user_id
    ):
        # Notional sells skip the qty cap — position presence is sufficient.
        request = PlaceOrderRequest(
            symbol="TSLA", side="sell", type="market", notional="500.00"
        )

        await TradingService.place_order(
            db, alpaca=alpaca, user_id=user_id, data=request
        )

        alpaca.get_position.assert_awaited_once()
        alpaca.create_order.assert_awaited_once()

    async def test_limit_buy(self, db, alpaca, patch_repos, user_id):
        request = PlaceOrderRequest(
            symbol="TSLA",
            side="buy",
            type="limit",
            qty="5",
            limit_price="180.50",
        )

        await TradingService.place_order(
            db, alpaca=alpaca, user_id=user_id, data=request
        )

        payload = alpaca.create_order.call_args.args[1]
        assert payload["type"] == "limit"
        assert payload["qty"] == "5"
        assert payload["limit_price"] == "180.50"


# ---------------------------------------------------------------------------
# place_order — validation rules
# ---------------------------------------------------------------------------


class TestPlaceOrderRules:
    async def test_inactive_brokerage_blocks(
        self, db, alpaca, patch_repos, user_id
    ):
        patch_repos.get_brokerage.return_value = None

        request = PlaceOrderRequest(
            symbol="TSLA", side="buy", type="market", qty="1"
        )
        with pytest.raises(ConflictError) as info:
            await TradingService.place_order(
                db, alpaca=alpaca, user_id=user_id, data=request
            )

        assert info.value.code == "ACCOUNT_NOT_ACTIVE"
        alpaca.create_order.assert_not_called()

    async def test_submitted_brokerage_blocks(
        self, db, alpaca, patch_repos, user_id, brokerage
    ):
        brokerage.account_status = "SUBMITTED"

        request = PlaceOrderRequest(
            symbol="TSLA", side="buy", type="market", qty="1"
        )
        with pytest.raises(ConflictError) as info:
            await TradingService.place_order(
                db, alpaca=alpaca, user_id=user_id, data=request
            )
        assert info.value.code == "ACCOUNT_NOT_ACTIVE"
        assert info.value.detail == {"account_status": "SUBMITTED"}

    async def test_untradeable_symbol_blocks(
        self, db, alpaca, patch_repos, user_id
    ):
        patch_repos.get_asset.return_value = None

        request = PlaceOrderRequest(
            symbol="TSLA", side="buy", type="market", qty="1"
        )
        with pytest.raises(ConflictError) as info:
            await TradingService.place_order(
                db, alpaca=alpaca, user_id=user_id, data=request
            )
        assert info.value.code == "SYMBOL_NOT_TRADEABLE"
        alpaca.create_order.assert_not_called()

    async def test_sell_with_no_position_blocks(
        self, db, alpaca, patch_repos, user_id
    ):
        alpaca.get_position.side_effect = NotFoundError("no position")

        request = PlaceOrderRequest(
            symbol="TSLA", side="sell", type="market", qty="1"
        )
        with pytest.raises(ConflictError) as info:
            await TradingService.place_order(
                db, alpaca=alpaca, user_id=user_id, data=request
            )
        assert info.value.code == "INSUFFICIENT_POSITION"
        alpaca.create_order.assert_not_called()

    async def test_sell_qty_exceeding_held_blocks(
        self, db, alpaca, patch_repos, user_id
    ):
        alpaca.get_position.return_value = {"symbol": "TSLA", "qty": "3"}

        request = PlaceOrderRequest(
            symbol="TSLA", side="sell", type="market", qty="5"
        )
        with pytest.raises(ConflictError) as info:
            await TradingService.place_order(
                db, alpaca=alpaca, user_id=user_id, data=request
            )
        assert info.value.code == "INSUFFICIENT_POSITION"
        assert info.value.detail["held_qty"] == "3"
        alpaca.create_order.assert_not_called()


# ---------------------------------------------------------------------------
# place_order — fractional / notional pre-validation
# ---------------------------------------------------------------------------


class TestPlaceOrderFractionable:
    async def test_fractionable_asset_allows_fractional_qty(
        self, db, alpaca, patch_repos, user_id
    ):
        # Schema only rejects fractional qty on limit orders, so a market
        # order with qty="0.5" reaches this validator.
        request = PlaceOrderRequest(
            symbol="TSLA", side="buy", type="market", qty="0.5"
        )

        await TradingService.place_order(
            db, alpaca=alpaca, user_id=user_id, data=request
        )

        alpaca.create_order.assert_awaited_once()
        payload = alpaca.create_order.call_args.args[1]
        assert payload["qty"] == "0.5"

    async def test_non_fractionable_blocks_fractional_qty(
        self, db, alpaca, patch_repos, user_id
    ):
        patch_repos.get_asset.return_value = SimpleNamespace(
            symbol="ILLQ", tradeable=True, fractionable=False
        )

        request = PlaceOrderRequest(
            symbol="ILLQ", side="buy", type="market", qty="0.5"
        )
        with pytest.raises(ConflictError) as info:
            await TradingService.place_order(
                db, alpaca=alpaca, user_id=user_id, data=request
            )

        assert info.value.code == "ASSET_NOT_FRACTIONABLE"
        assert info.value.detail == {"symbol": "ILLQ"}
        alpaca.create_order.assert_not_called()

    async def test_non_fractionable_allows_whole_qty(
        self, db, alpaca, patch_repos, user_id
    ):
        patch_repos.get_asset.return_value = SimpleNamespace(
            symbol="ILLQ", tradeable=True, fractionable=False
        )

        request = PlaceOrderRequest(
            symbol="ILLQ", side="buy", type="market", qty="10"
        )
        await TradingService.place_order(
            db, alpaca=alpaca, user_id=user_id, data=request
        )

        alpaca.create_order.assert_awaited_once()

    async def test_non_fractionable_blocks_notional_order(
        self, db, alpaca, patch_repos, user_id
    ):
        # Notional orders always produce fractional shares, so a
        # whole-shares-only asset must reject them regardless of amount.
        patch_repos.get_asset.return_value = SimpleNamespace(
            symbol="ILLQ", tradeable=True, fractionable=False
        )

        request = PlaceOrderRequest(
            symbol="ILLQ", side="buy", type="market", notional="100.00"
        )
        with pytest.raises(ConflictError) as info:
            await TradingService.place_order(
                db, alpaca=alpaca, user_id=user_id, data=request
            )

        assert info.value.code == "ASSET_NOT_FRACTIONABLE"
        alpaca.create_order.assert_not_called()


# ---------------------------------------------------------------------------
# place_order — payload construction
# ---------------------------------------------------------------------------


class TestPlaceOrderPayload:
    async def test_market_uses_day_time_in_force(
        self, db, alpaca, patch_repos, user_id
    ):
        request = PlaceOrderRequest(
            symbol="TSLA", side="buy", type="market", qty="1"
        )
        await TradingService.place_order(
            db, alpaca=alpaca, user_id=user_id, data=request
        )

        payload = alpaca.create_order.call_args.args[1]
        assert payload["time_in_force"] == "day"

    async def test_limit_uses_gtc_time_in_force(
        self, db, alpaca, patch_repos, user_id
    ):
        request = PlaceOrderRequest(
            symbol="TSLA",
            side="buy",
            type="limit",
            qty="1",
            limit_price="100",
        )
        await TradingService.place_order(
            db, alpaca=alpaca, user_id=user_id, data=request
        )

        payload = alpaca.create_order.call_args.args[1]
        assert payload["time_in_force"] == "gtc"

    async def test_generates_client_order_id(
        self, db, alpaca, patch_repos, user_id
    ):
        request = PlaceOrderRequest(
            symbol="TSLA", side="buy", type="market", qty="1"
        )
        await TradingService.place_order(
            db, alpaca=alpaca, user_id=user_id, data=request
        )

        payload = alpaca.create_order.call_args.args[1]
        # Sanity: it's a UUID string the Pydantic UUID parser accepts.
        assert uuid.UUID(payload["client_order_id"])

    async def test_uppercases_symbol_in_payload(
        self, db, alpaca, patch_repos, user_id
    ):
        request = PlaceOrderRequest(
            symbol="tsla", side="buy", type="market", qty="1"
        )
        await TradingService.place_order(
            db, alpaca=alpaca, user_id=user_id, data=request
        )

        payload = alpaca.create_order.call_args.args[1]
        assert payload["symbol"] == "TSLA"


# ---------------------------------------------------------------------------
# place_order — Alpaca error pass-through
# ---------------------------------------------------------------------------


class TestPlaceOrderAlpacaError:
    async def test_alpaca_error_bubbles_up(
        self, db, alpaca, patch_repos, user_id
    ):
        alpaca.create_order.side_effect = AlpacaBrokerError(
            status_code=422, message="insufficient buying power"
        )

        request = PlaceOrderRequest(
            symbol="TSLA", side="buy", type="market", qty="1"
        )
        with pytest.raises(AlpacaBrokerError):
            await TradingService.place_order(
                db, alpaca=alpaca, user_id=user_id, data=request
            )

        # We never persisted because Alpaca rejected the order.
        patch_repos.order_create.assert_not_called()


# ---------------------------------------------------------------------------
# cancel_order
# ---------------------------------------------------------------------------


class TestCancelOrder:
    async def test_happy_path(
        self, db, alpaca, patch_repos, user_id, brokerage
    ):
        order = _make_order_event(user_id, status="new")
        patch_repos.get_order.return_value = order

        result = await TradingService.cancel_order(
            db, alpaca=alpaca, user_id=user_id, order_id=order.id
        )

        assert result is order
        assert order.status == "pending_cancel"
        alpaca.cancel_order.assert_awaited_once_with(
            brokerage.alpaca_account_id, order.alpaca_order_id
        )
        db.flush.assert_awaited()

    async def test_404_for_unknown_order(
        self, db, alpaca, patch_repos, user_id
    ):
        patch_repos.get_order.return_value = None

        with pytest.raises(NotFoundError):
            await TradingService.cancel_order(
                db, alpaca=alpaca, user_id=user_id, order_id=uuid.uuid4()
            )
        alpaca.cancel_order.assert_not_called()

    @pytest.mark.parametrize("terminal_status", sorted(TERMINAL_ORDER_STATUSES))
    async def test_rejects_terminal_status(
        self, db, alpaca, patch_repos, user_id, terminal_status
    ):
        order = _make_order_event(user_id, status=terminal_status)
        patch_repos.get_order.return_value = order

        with pytest.raises(ConflictError) as info:
            await TradingService.cancel_order(
                db, alpaca=alpaca, user_id=user_id, order_id=order.id
            )
        assert info.value.code == "ORDER_NOT_CANCELABLE"
        assert info.value.detail == {"status": terminal_status}
        alpaca.cancel_order.assert_not_called()

    async def test_alpaca_422_translated_to_conflict(
        self, db, alpaca, patch_repos, user_id
    ):
        order = _make_order_event(user_id, status="new")
        patch_repos.get_order.return_value = order
        alpaca.cancel_order.side_effect = AlpacaBrokerError(
            status_code=422, message="order is no longer cancelable"
        )

        with pytest.raises(ConflictError) as info:
            await TradingService.cancel_order(
                db, alpaca=alpaca, user_id=user_id, order_id=order.id
            )
        assert info.value.code == "ORDER_NOT_CANCELABLE"
        # Status was not flipped — Alpaca rejected the cancel.
        assert order.status == "new"
        db.flush.assert_not_called()

    async def test_alpaca_5xx_translated_to_unavailable(
        self, db, alpaca, patch_repos, user_id
    ):
        """A 5xx from Alpaca during cancel is a transient outage, not a
        business-rule rejection. Translate to AlpacaBrokerUnavailableError
        so the global handler returns 503 instead of the generic 422 the
        AlpacaBrokerError handler would otherwise produce."""
        order = _make_order_event(user_id, status="new")
        patch_repos.get_order.return_value = order
        alpaca.cancel_order.side_effect = AlpacaBrokerError(
            status_code=500, message="server error"
        )

        with pytest.raises(AlpacaBrokerUnavailableError):
            await TradingService.cancel_order(
                db, alpaca=alpaca, user_id=user_id, order_id=order.id
            )
        assert order.status == "new"

    async def test_alpaca_other_4xx_bubbles_up(
        self, db, alpaca, patch_repos, user_id
    ):
        """Non-422 4xx (e.g. 401 expired auth, 404 unknown order) bubble
        unchanged so the global AlpacaBrokerError handler can render the
        message — only 422 (already-canceled) and 5xx (transient outage)
        get translated to domain errors."""
        order = _make_order_event(user_id, status="new")
        patch_repos.get_order.return_value = order
        alpaca.cancel_order.side_effect = AlpacaBrokerError(
            status_code=401, message="auth expired"
        )

        with pytest.raises(AlpacaBrokerError):
            await TradingService.cancel_order(
                db, alpaca=alpaca, user_id=user_id, order_id=order.id
            )
        assert order.status == "new"


# ---------------------------------------------------------------------------
# get_order
# ---------------------------------------------------------------------------


class TestGetOrder:
    async def test_returns_owned_order(self, db, patch_repos, user_id):
        order = _make_order_event(user_id)
        patch_repos.get_order.return_value = order

        result = await TradingService.get_order(
            db, user_id=user_id, order_id=order.id
        )
        assert result is order

    async def test_404_for_other_users_order(
        self, db, patch_repos, user_id
    ):
        # Repository returns None when ownership doesn't match.
        patch_repos.get_order.return_value = None

        with pytest.raises(NotFoundError):
            await TradingService.get_order(
                db, user_id=user_id, order_id=uuid.uuid4()
            )


# ---------------------------------------------------------------------------
# validate_trade_prerequisites — direct tests
# ---------------------------------------------------------------------------


class TestValidateTradePrerequisites:
    async def test_returns_brokerage_and_asset_on_success(
        self, db, alpaca, patch_repos, user_id, brokerage, asset
    ):
        result_brokerage, result_asset = await validate_trade_prerequisites(
            db,
            alpaca=alpaca,
            user_id=user_id,
            symbol="TSLA",
            side="buy",
            qty="1",
        )

        assert result_brokerage is brokerage
        assert result_asset is asset

    async def test_buy_skips_position_check(
        self, db, alpaca, patch_repos, user_id
    ):
        await validate_trade_prerequisites(
            db,
            alpaca=alpaca,
            user_id=user_id,
            symbol="TSLA",
            side="buy",
            qty="1",
        )

        alpaca.get_position.assert_not_called()

    async def test_notional_sell_passes_with_position_no_qty_check(
        self, db, alpaca, patch_repos, user_id, brokerage, asset
    ):
        # Position exists but caller provides no qty (notional sell). The
        # qty-vs-held comparison must be skipped — Alpaca enforces the
        # dollar cap server-side.
        alpaca.get_position.return_value = {"symbol": "TSLA", "qty": "1"}

        result_brokerage, result_asset = await validate_trade_prerequisites(
            db,
            alpaca=alpaca,
            user_id=user_id,
            symbol="TSLA",
            side="sell",
            qty=None,
        )

        assert result_brokerage is brokerage
        assert result_asset is asset
        alpaca.get_position.assert_awaited_once_with("alpaca_acc_42", "TSLA")

    async def test_invalid_qty_string_raises_typed_conflict(
        self, db, alpaca, patch_repos, user_id
    ):
        """Caller-supplied junk qty must surface as a typed ConflictError
        rather than the opaque `decimal.InvalidOperation` 500 the bare
        `Decimal(qty)` parse would otherwise raise. Important now that
        the helper is documented as reusable outside the schema-validated
        place_order flow."""
        alpaca.get_position.return_value = {"symbol": "TSLA", "qty": "10"}

        with pytest.raises(ConflictError) as info:
            await validate_trade_prerequisites(
                db,
                alpaca=alpaca,
                user_id=user_id,
                symbol="TSLA",
                side="sell",
                qty="not-a-number",
            )

        assert info.value.code == "INVALID_QTY"

    async def test_invalid_qty_string_in_fractionable_check_raises_typed_conflict(
        self, db, alpaca, patch_repos, user_id
    ):
        # Mirrors the sell-side INVALID_QTY case for the fractionability
        # branch: a non-fractionable asset + junk qty must surface a typed
        # ConflictError rather than a bare decimal.InvalidOperation.
        # Reachable when the helper is called outside the schema-validated
        # place_order flow.
        patch_repos.get_asset.return_value = SimpleNamespace(
            symbol="ILLQ", tradeable=True, fractionable=False
        )

        with pytest.raises(ConflictError) as info:
            await validate_trade_prerequisites(
                db,
                alpaca=alpaca,
                user_id=user_id,
                symbol="ILLQ",
                side="buy",
                qty="not-a-number",
            )

        assert info.value.code == "INVALID_QTY"
        assert info.value.detail == {"qty": "not-a-number"}


# ---------------------------------------------------------------------------
# place_order — time_in_force round-trip auditing
# ---------------------------------------------------------------------------


class TestPlaceOrderTimeInForceAudit:
    async def test_warns_when_alpaca_returns_diverging_time_in_force(
        self, db, alpaca, patch_repos, user_id, caplog
    ):
        """The schema synthesizes time_in_force from order_type rather than
        persisting Alpaca's echoed value. If Alpaca ever silently coerces
        the value (e.g. `day` → `gtc`), the response would otherwise lie.
        Verify the divergence is at least logged so the assumption is
        audited rather than invisible."""
        alpaca.create_order.return_value = {
            **alpaca.create_order.return_value,
            "time_in_force": "gtc",  # We sent `day`; Alpaca echoed `gtc`.
        }

        request = PlaceOrderRequest(
            symbol="TSLA", side="buy", type="market", qty="1"
        )
        await TradingService.place_order(
            db, alpaca=alpaca, user_id=user_id, data=request
        )

        assert any(
            "order_time_in_force_diverged" in record.getMessage()
            or getattr(record, "event", None) == "order_time_in_force_diverged"
            for record in caplog.records
        )
