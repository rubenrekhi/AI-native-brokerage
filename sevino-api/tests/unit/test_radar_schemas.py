"""Unit tests for radar Pydantic schemas."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.radar import RadarItemCreate, RadarItemRead, RadarItemUpdate


def _make_read(**overrides) -> RadarItemRead:
    data = {
        "id": uuid4(),
        "symbol": "AAPL",
        "company_name": "Apple Inc.",
        "context_blurb": None,
        "source": "user_added",
        "is_favorited": True,
        "relevance_score": None,
        "expires_at": None,
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }
    data.update(overrides)
    return RadarItemRead.model_validate(data)


class TestRadarItemCreate:
    def test_accepts_valid_symbol(self):
        assert RadarItemCreate(symbol="AAPL").symbol == "AAPL"

    def test_rejects_empty_symbol(self):
        with pytest.raises(ValidationError):
            RadarItemCreate(symbol="")

    def test_rejects_symbol_longer_than_10_chars(self):
        with pytest.raises(ValidationError):
            RadarItemCreate(symbol="A" * 11)

    def test_accepts_max_length_symbol(self):
        assert RadarItemCreate(symbol="A" * 10).symbol == "A" * 10


class TestRadarItemUpdate:
    def test_requires_is_favorited(self):
        with pytest.raises(ValidationError):
            RadarItemUpdate.model_validate({})

    def test_accepts_true_and_false(self):
        assert RadarItemUpdate(is_favorited=True).is_favorited is True
        assert RadarItemUpdate(is_favorited=False).is_favorited is False


class TestRadarItemRead:
    def test_overlay_fields_default_to_none(self):
        item = _make_read()
        assert item.price is None
        assert item.change_abs is None
        assert item.change_pct is None

    def test_overlay_fields_serialize_as_json_strings(self):
        item = _make_read(
            price=Decimal("180.50"),
            change_abs=Decimal("1.25"),
            change_pct=Decimal("0.0070"),
        )
        dumped = item.model_dump(mode="json")
        assert dumped["price"] == "180.50"
        assert dumped["change_abs"] == "1.25"
        assert dumped["change_pct"] == "0.0070"

    def test_null_overlay_fields_serialize_as_null(self):
        dumped = _make_read().model_dump(mode="json")
        assert dumped["price"] is None
        assert dumped["change_abs"] is None
        assert dumped["change_pct"] is None

    def test_rejects_unknown_source_value(self):
        with pytest.raises(ValidationError):
            _make_read(source="malicious")

    def test_round_trip_through_json(self):
        original = _make_read(price=Decimal("180.50"), change_pct=Decimal("0.0070"))
        revived = RadarItemRead.model_validate(original.model_dump(mode="json"))
        assert revived == original
