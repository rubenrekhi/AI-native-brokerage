from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import BeforeValidator, PlainSerializer


def _to_decimal(v: object) -> Decimal:
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


MoneyStr = Annotated[
    Decimal,
    BeforeValidator(_to_decimal),
    PlainSerializer(
        lambda v: str(v.quantize(Decimal("0.01"))),
        return_type=str,
        when_used="json",
    ),
]
"""Money in USD. 2 decimal places. Serialized as JSON string."""

QtyStr = Annotated[
    Decimal,
    BeforeValidator(_to_decimal),
    PlainSerializer(
        lambda v: format(v.normalize(), "f"),
        return_type=str,
        when_used="json",
    ),
]
"""Share quantity. Up to 9 decimal places. Serialized as JSON string."""

PctStr = Annotated[
    Decimal,
    BeforeValidator(_to_decimal),
    PlainSerializer(
        lambda v: str(v.quantize(Decimal("0.0001"))),
        return_type=str,
        when_used="json",
    ),
]
"""Percentage as factor of 1. 4 decimal places. Serialized as JSON string."""
