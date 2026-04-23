"""Unit tests for app.schemas.asset."""

import pytest
from pydantic import ValidationError

from app.schemas.asset import AssetSearchQuery, AssetSearchResult


class TestAssetSearchQuery:
    def test_valid_query_passes(self):
        query = AssetSearchQuery(q="TSLA", limit=20)
        assert query.q == "TSLA"
        assert query.limit == 20

    def test_default_limit_is_10(self):
        query = AssetSearchQuery(q="T")
        assert query.limit == 10

    def test_empty_q_raises(self):
        with pytest.raises(ValidationError):
            AssetSearchQuery(q="")

    def test_q_over_10_chars_raises(self):
        with pytest.raises(ValidationError):
            AssetSearchQuery(q="A" * 11)

    def test_q_exactly_10_chars_passes(self):
        query = AssetSearchQuery(q="A" * 10)
        assert query.q == "A" * 10

    def test_limit_below_1_raises(self):
        with pytest.raises(ValidationError):
            AssetSearchQuery(q="T", limit=0)

    def test_limit_above_50_raises(self):
        with pytest.raises(ValidationError):
            AssetSearchQuery(q="T", limit=51)

    def test_limit_boundaries_pass(self):
        assert AssetSearchQuery(q="T", limit=1).limit == 1
        assert AssetSearchQuery(q="T", limit=50).limit == 50


class TestAssetSearchResult:
    def test_serializes_from_orm_like_object(self):
        class FakeAsset:
            symbol = "TSLA"
            name = "Tesla, Inc."
            logo_url = "https://financialmodelingprep.com/image-stock/TSLA.png"

        result = AssetSearchResult.model_validate(FakeAsset())
        assert result.symbol == "TSLA"
        assert result.name == "Tesla, Inc."
        assert result.logo_url == "https://financialmodelingprep.com/image-stock/TSLA.png"

    def test_logo_url_optional(self):
        class FakeAsset:
            symbol = "FOO"
            name = "Foo Corp"
            logo_url = None

        result = AssetSearchResult.model_validate(FakeAsset())
        assert result.logo_url is None

    def test_constructs_from_dict(self):
        result = AssetSearchResult(symbol="AAPL", name="Apple Inc.")
        assert result.symbol == "AAPL"
        assert result.name == "Apple Inc."
        assert result.logo_url is None
