"""Unit tests for app.schemas.trading and AssetRepository.get_by_symbol."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.repositories.asset import AssetRepository
from app.schemas.trading import PlaceOrderRequest


class TestPlaceOrderRequestValid:
    def test_market_buy_by_qty(self):
        order = PlaceOrderRequest(
            symbol="TSLA", side="buy", type="market", qty="10"
        )
        assert order.qty == "10"
        assert order.notional is None
        assert order.limit_price is None

    def test_market_buy_by_notional(self):
        order = PlaceOrderRequest(
            symbol="TSLA", side="buy", type="market", notional="500.00"
        )
        assert order.notional == "500.00"
        assert order.qty is None

    def test_market_sell_by_notional(self):
        order = PlaceOrderRequest(
            symbol="TSLA", side="sell", type="market", notional="250.50"
        )
        assert order.side == "sell"
        assert order.notional == "250.50"

    def test_limit_buy_by_whole_qty(self):
        order = PlaceOrderRequest(
            symbol="TSLA",
            side="buy",
            type="limit",
            qty="5",
            limit_price="180.50",
        )
        assert order.qty == "5"
        assert order.limit_price == "180.50"

    def test_fractional_qty_market_allowed(self):
        order = PlaceOrderRequest(
            symbol="TSLA", side="buy", type="market", qty="0.5"
        )
        assert order.qty == "0.5"


class TestPlaceOrderRequestQtyNotional:
    def test_rejects_both_qty_and_notional(self):
        with pytest.raises(ValidationError, match="not both"):
            PlaceOrderRequest(
                symbol="TSLA",
                side="buy",
                type="market",
                qty="10",
                notional="500",
            )

    def test_rejects_neither_qty_nor_notional(self):
        with pytest.raises(ValidationError, match="required"):
            PlaceOrderRequest(symbol="TSLA", side="buy", type="market")


class TestPlaceOrderRequestTypeRules:
    def test_rejects_notional_with_limit(self):
        with pytest.raises(
            ValidationError,
            match="Dollar amount orders are only supported for market orders",
        ):
            PlaceOrderRequest(
                symbol="TSLA",
                side="buy",
                type="limit",
                notional="500",
                limit_price="180",
            )

    def test_rejects_limit_price_with_market(self):
        with pytest.raises(
            ValidationError, match="Market orders cannot have a limit price"
        ):
            PlaceOrderRequest(
                symbol="TSLA",
                side="buy",
                type="market",
                qty="10",
                limit_price="180",
            )

    def test_rejects_missing_limit_price_with_limit(self):
        with pytest.raises(
            ValidationError, match="Limit orders require a limit price"
        ):
            PlaceOrderRequest(
                symbol="TSLA", side="buy", type="limit", qty="10"
            )

    def test_rejects_fractional_qty_with_limit(self):
        with pytest.raises(
            ValidationError,
            match="Limit orders require whole share quantities",
        ):
            PlaceOrderRequest(
                symbol="TSLA",
                side="buy",
                type="limit",
                qty="0.5",
                limit_price="180",
            )


class TestPlaceOrderRequestStop:
    def test_stop_sell_by_whole_qty(self):
        order = PlaceOrderRequest(
            symbol="AAPL",
            side="sell",
            type="stop",
            qty="5",
            stop_price="170.00",
        )
        assert order.type == "stop"
        assert order.side == "sell"
        assert order.qty == "5"
        assert order.stop_price == "170.00"
        assert order.limit_price is None

    def test_stop_buy_by_whole_qty(self):
        order = PlaceOrderRequest(
            symbol="AAPL",
            side="buy",
            type="stop",
            qty="3",
            stop_price="250.00",
        )
        assert order.side == "buy"
        assert order.stop_price == "250.00"

    def test_rejects_missing_stop_price(self):
        with pytest.raises(
            ValidationError, match="Stop orders require a stop price"
        ):
            PlaceOrderRequest(
                symbol="AAPL", side="sell", type="stop", qty="5"
            )

    def test_rejects_stop_price_with_market(self):
        with pytest.raises(
            ValidationError, match="Only stop orders can have a stop price"
        ):
            PlaceOrderRequest(
                symbol="AAPL",
                side="sell",
                type="market",
                qty="5",
                stop_price="170",
            )

    def test_rejects_stop_price_with_limit(self):
        with pytest.raises(
            ValidationError, match="Only stop orders can have a stop price"
        ):
            PlaceOrderRequest(
                symbol="AAPL",
                side="sell",
                type="limit",
                qty="5",
                limit_price="180",
                stop_price="170",
            )

    def test_rejects_limit_price_with_stop(self):
        with pytest.raises(
            ValidationError, match="Stop orders cannot have a limit price"
        ):
            PlaceOrderRequest(
                symbol="AAPL",
                side="sell",
                type="stop",
                qty="5",
                stop_price="170",
                limit_price="165",
            )

    def test_rejects_fractional_qty_with_stop(self):
        with pytest.raises(
            ValidationError,
            match="Stop orders require whole share quantities",
        ):
            PlaceOrderRequest(
                symbol="AAPL",
                side="sell",
                type="stop",
                qty="0.5",
                stop_price="170",
            )

    def test_rejects_notional_with_stop(self):
        with pytest.raises(
            ValidationError,
            match="Dollar amount orders are only supported for market orders",
        ):
            PlaceOrderRequest(
                symbol="AAPL",
                side="sell",
                type="stop",
                notional="500",
                stop_price="170",
            )


class TestPlaceOrderRequestPositiveDecimals:
    @pytest.mark.parametrize(
        "field, bad_value",
        [
            ("qty", "0"),
            ("qty", "-1"),
            ("qty", "-0.5"),
            ("notional", "0"),
            ("notional", "-100"),
            ("notional", "-0.01"),
            ("limit_price", "0"),
            ("limit_price", "-180.50"),
            ("stop_price", "0"),
            ("stop_price", "-180.50"),
        ],
    )
    def test_rejects_non_positive(self, field, bad_value):
        kwargs: dict = {"symbol": "TSLA", "side": "buy"}
        if field == "limit_price":
            kwargs.update(type="limit", qty="10", limit_price=bad_value)
        elif field == "stop_price":
            kwargs.update(type="stop", qty="10", stop_price=bad_value)
        else:
            kwargs.update(type="market", **{field: bad_value})
        with pytest.raises(
            ValidationError, match=f"{field} must be positive"
        ):
            PlaceOrderRequest(**kwargs)

    def test_rejects_non_numeric_qty(self):
        with pytest.raises(
            ValidationError, match="qty must be a valid decimal number"
        ):
            PlaceOrderRequest(
                symbol="TSLA", side="buy", type="market", qty="abc"
            )

    def test_rejects_non_numeric_notional(self):
        with pytest.raises(
            ValidationError, match="notional must be a valid decimal number"
        ):
            PlaceOrderRequest(
                symbol="TSLA",
                side="buy",
                type="market",
                notional="not-a-number",
            )

    def test_rejects_non_numeric_limit_price(self):
        with pytest.raises(
            ValidationError, match="limit_price must be a valid decimal number"
        ):
            PlaceOrderRequest(
                symbol="TSLA",
                side="buy",
                type="limit",
                qty="10",
                limit_price="oops",
            )

    def test_rejects_non_numeric_stop_price(self):
        with pytest.raises(
            ValidationError, match="stop_price must be a valid decimal number"
        ):
            PlaceOrderRequest(
                symbol="TSLA",
                side="sell",
                type="stop",
                qty="10",
                stop_price="oops",
            )


class TestPlaceOrderRequestSymbol:
    def test_rejects_empty_symbol(self):
        with pytest.raises(ValidationError):
            PlaceOrderRequest(
                symbol="", side="buy", type="market", qty="10"
            )

    def test_rejects_symbol_over_10_chars(self):
        with pytest.raises(ValidationError):
            PlaceOrderRequest(
                symbol="A" * 11, side="buy", type="market", qty="10"
            )


class TestAssetRepositoryGetBySymbol:
    @staticmethod
    def _session_returning(asset):
        session = MagicMock()
        execute_result = MagicMock()
        execute_result.scalar_one_or_none = MagicMock(return_value=asset)
        session.execute = AsyncMock(return_value=execute_result)
        return session

    async def test_returns_asset_when_tradeable(self):
        sentinel = object()
        session = self._session_returning(sentinel)

        result = await AssetRepository.get_by_symbol(
            session, "TSLA"
        )

        assert result is sentinel
        session.execute.assert_awaited_once()

    async def test_returns_none_when_missing_or_untradeable(self):
        session = self._session_returning(None)

        result = await AssetRepository.get_by_symbol(
            session, "TSLA"
        )

        assert result is None

    async def test_uppercases_symbol_for_query(self):
        session = self._session_returning(None)

        await AssetRepository.get_by_symbol(session, "tsla")

        stmt = session.execute.await_args.args[0]
        compiled = str(
            stmt.compile(compile_kwargs={"literal_binds": True})
        )
        assert "'TSLA'" in compiled
