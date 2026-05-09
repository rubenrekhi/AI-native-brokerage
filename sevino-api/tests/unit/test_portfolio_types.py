from decimal import Decimal

from pydantic import BaseModel

from app.schemas._types import MoneyStr, PctStr, QtyStr


class _Money(BaseModel):
    amt: MoneyStr


class _Qty(BaseModel):
    qty: QtyStr


class _Pct(BaseModel):
    pct: PctStr


def test_money_serializes_to_two_decimal_string() -> None:
    assert _Money(amt=Decimal("1084.92")).model_dump(mode="json") == {"amt": "1084.92"}
    assert _Money(amt=Decimal("1084.9")).model_dump(mode="json") == {"amt": "1084.90"}
    assert _Money(amt=Decimal("1084.999")).model_dump(mode="json") == {"amt": "1085.00"}


def test_qty_serializes_with_trailing_zeros_stripped() -> None:
    assert _Qty(qty=Decimal("57")).model_dump(mode="json") == {"qty": "57"}
    assert _Qty(qty=Decimal("0.125000000")).model_dump(mode="json") == {"qty": "0.125"}


def test_pct_serializes_to_four_decimal_string() -> None:
    assert _Pct(pct=Decimal("0.2731")).model_dump(mode="json") == {"pct": "0.2731"}
    assert _Pct(pct=Decimal("0.2")).model_dump(mode="json") == {"pct": "0.2000"}


def test_money_accepts_incoming_json_string_and_round_trips() -> None:
    model = _Money.model_validate({"amt": "100.50"})
    assert isinstance(model.amt, Decimal)
    assert model.amt == Decimal("100.50")
    assert model.model_dump(mode="json") == {"amt": "100.50"}


def test_qty_accepts_incoming_json_string() -> None:
    model = _Qty.model_validate({"qty": "0.125"})
    assert model.qty == Decimal("0.125")
    assert model.model_dump(mode="json") == {"qty": "0.125"}
