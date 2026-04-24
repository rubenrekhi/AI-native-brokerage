from decimal import Decimal

from app.schemas.portfolio import (
    HoldingsResponse,
    Position,
    PortfolioSnapshotResponse,
)


def _make_snapshot(**overrides) -> PortfolioSnapshotResponse:
    data = {
        "account_status": "ACTIVE",
        "currency": "USD",
        "equity": Decimal("1084.92"),
        "last_equity": Decimal("2134.24"),
        "cash": Decimal("12.50"),
        "buying_power": Decimal("12.50"),
        "daily_change_abs": Decimal("-1049.32"),
        "daily_change_pct": Decimal("-0.0838"),
    }
    data.update(overrides)
    return PortfolioSnapshotResponse(**data)


class TestPortfolioSnapshotResponse:
    def test_json_dump_serializes_money_as_strings(self):
        snapshot = _make_snapshot()
        dumped = snapshot.model_dump(mode="json")

        assert dumped["equity"] == "1084.92"
        assert dumped["last_equity"] == "2134.24"
        assert dumped["cash"] == "12.50"
        assert dumped["buying_power"] == "12.50"

    def test_negative_money_preserves_sign(self):
        snapshot = _make_snapshot()
        dumped = snapshot.model_dump(mode="json")

        assert dumped["daily_change_abs"] == "-1049.32"

    def test_percent_serializes_with_four_decimals(self):
        snapshot = _make_snapshot()
        dumped = snapshot.model_dump(mode="json")

        assert dumped["daily_change_pct"] == "-0.0838"

    def test_accepts_json_string_input(self):
        snapshot = PortfolioSnapshotResponse.model_validate(
            {
                "account_status": "ACTIVE",
                "currency": "USD",
                "equity": "1084.92",
                "last_equity": "2134.24",
                "cash": "12.50",
                "buying_power": "12.50",
                "daily_change_abs": "-1049.32",
                "daily_change_pct": "-0.0838",
            }
        )
        assert snapshot.equity == Decimal("1084.92")
        assert snapshot.daily_change_pct == Decimal("-0.0838")

    def test_round_trip_through_json(self):
        original = _make_snapshot()
        dumped = original.model_dump(mode="json")
        revived = PortfolioSnapshotResponse.model_validate(dumped)

        assert revived == original

    def test_instance_is_frozen(self):
        snapshot = _make_snapshot()
        try:
            snapshot.account_status = "REJECTED"  # type: ignore[misc]
        except Exception:
            return
        raise AssertionError("PortfolioSnapshotResponse should be frozen")


def _make_position(**overrides) -> Position:
    data = {
        "symbol": "TSLA",
        "name": "Tesla Inc",
        "qty": Decimal("3.5"),
        "avg_entry_price": Decimal("240.00"),
        "current_price": Decimal("250.00"),
        "market_value": Decimal("875.00"),
        "cost_basis": Decimal("840.00"),
        "unrealized_pl": Decimal("35.00"),
        "unrealized_plpc": Decimal("0.0417"),
    }
    data.update(overrides)
    return Position(**data)


def _make_holdings(**overrides) -> HoldingsResponse:
    data = {
        "account_status": "ACTIVE",
        "currency": "USD",
        "cash": Decimal("100.00"),
        "total_market_value": Decimal("1575.00"),
        "positions": [
            _make_position(),
            _make_position(
                symbol="AAPL",
                name="Apple Inc",
                qty=Decimal("4"),
                avg_entry_price=Decimal("170.00"),
                current_price=Decimal("175.00"),
                market_value=Decimal("700.00"),
                cost_basis=Decimal("680.00"),
                unrealized_pl=Decimal("20.00"),
                unrealized_plpc=Decimal("0.0294"),
            ),
        ],
    }
    data.update(overrides)
    return HoldingsResponse(**data)


class TestHoldingsResponse:
    def test_round_trip_two_positions_matches_json_shape(self):
        holdings = _make_holdings()
        dumped = holdings.model_dump(mode="json")

        assert dumped["account_status"] == "ACTIVE"
        assert dumped["currency"] == "USD"
        assert dumped["cash"] == "100.00"
        assert dumped["total_market_value"] == "1575.00"
        assert len(dumped["positions"]) == 2

        first = dumped["positions"][0]
        assert first["symbol"] == "TSLA"
        assert first["name"] == "Tesla Inc"
        assert first["qty"] == "3.5"
        assert first["avg_entry_price"] == "240.00"
        assert first["current_price"] == "250.00"
        assert first["market_value"] == "875.00"
        assert first["cost_basis"] == "840.00"
        assert first["unrealized_pl"] == "35.00"
        assert first["unrealized_plpc"] == "0.0417"

        revived = HoldingsResponse.model_validate(dumped)
        assert revived == holdings

    def test_fractional_qty_round_trips_exactly(self):
        position = _make_position(qty=Decimal("0.125"))
        dumped = position.model_dump(mode="json")

        assert dumped["qty"] == "0.125"
        assert Position.model_validate(dumped).qty == Decimal("0.125")

    def test_negative_unrealized_fields_keep_signs(self):
        position = _make_position(
            unrealized_pl=Decimal("-42.18"),
            unrealized_plpc=Decimal("-0.0502"),
        )
        dumped = position.model_dump(mode="json")

        assert dumped["unrealized_pl"] == "-42.18"
        assert dumped["unrealized_plpc"] == "-0.0502"

    def test_empty_positions_list_validates(self):
        holdings = _make_holdings(
            positions=[], total_market_value=Decimal("0.00")
        )
        dumped = holdings.model_dump(mode="json")

        assert dumped["positions"] == []
        assert dumped["total_market_value"] == "0.00"
