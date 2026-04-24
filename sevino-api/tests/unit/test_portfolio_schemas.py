from decimal import Decimal

from app.schemas.portfolio import PortfolioSnapshotResponse


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
