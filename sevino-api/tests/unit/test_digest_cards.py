"""Contract tests for the ``DigestCard`` discriminated union (SEV-631 / T1).

Acceptance: all 9 variants dispatch on ``kind`` and round-trip through JSON
without losing their variant or mangling money/qty/pct fields (which cross
the wire as strings). The JSONB persistence round-trip is exercised by the
repository integration tests.
"""

import pytest
from pydantic import ValidationError

from app.services.digest.cards import (
    BigMoveCard,
    DigestCardAdapter,
    DigestCardListAdapter,
    DividendsCard,
    EarningsResultCard,
    MarketContextCard,
    NewsCard,
    OrderActivityItem,
    PendingOrderActivityCard,
    RadarRefreshCard,
    UpcomingEarningsCard,
    WatchlistMoveCard,
)

_ID = "11111111-1111-1111-1111-111111111111"


def _payloads() -> dict[str, dict]:
    """One reference JSON payload per variant, keyed by ``kind``.

    Money/qty/pct values are strings (the wire/JSONB shape) so the tests
    exercise the ``BeforeValidator`` -> ``Decimal`` -> serializer path.
    """
    common = {
        "id": _ID,
        "priority": 5,
        "related_symbols": ["AAPL"],
        "card_context": {"k": "v"},
    }
    return {
        "dividends": {
            **common,
            "kind": "dividends",
            "payments": [
                {
                    "symbol": "AAPL",
                    "amount": "1.20",
                    "paid_at": "2026-05-30T13:30:00Z",
                }
            ],
            "total_amount": "1.20",
            "period_label": "This week",
        },
        "pending_order_activity": {
            **common,
            "kind": "pending_order_activity",
            "filled": [
                {
                    "symbol": "TSLA",
                    "name": "Tesla, Inc.",
                    "side": "buy",
                    "qty": "2",
                    "notional": "500.00",
                }
            ],
            "recurring_executed": [
                {"symbol": "VOO", "side": "buy", "notional": "100.00"}
            ],
            "recurring_skipped": [],
        },
        "big_move": {
            **common,
            "kind": "big_move",
            "symbol": "NVDA",
            "name": "NVIDIA Corporation",
            "prev_close": "180.00",
            "current": "198.00",
            "change_abs": "18.00",
            "change_pct": "0.1000",
            "reason": "Beat earnings.",
        },
        "watchlist_move": {
            **common,
            "kind": "watchlist_move",
            "symbol": "AMD",
            "name": "Advanced Micro Devices",
            "prev_close": "150.00",
            "current": "142.50",
            "change_abs": "-7.50",
            "change_pct": "-0.0500",
            "reason": None,
        },
        "market_context": {
            **common,
            "kind": "market_context",
            "direction": "up",
            "sp500_change_pct": "0.0123",
            "nasdaq_change_pct": "0.0150",
            "summary": "Broad rally led by tech.",
        },
        "radar_refresh": {
            **common,
            "kind": "radar_refresh",
            "refreshed_at": "2026-05-31T11:00:00Z",
            "new_count": 3,
            "removed_count": 1,
        },
        "earnings_result": {
            **common,
            "kind": "earnings_result",
            "symbol": "MSFT",
            "name": "Microsoft Corporation",
            "grade": "A",
            "eps_actual": "2.95",
            "eps_estimate": "2.80",
            "rev_actual": "62000000000.00",
            "rev_estimate": "60500000000.00",
            "stock_reaction_pct": "0.0345",
            "beat_miss_highlights": ["EPS beat by 5%", "Revenue beat"],
        },
        "upcoming_earnings": {
            **common,
            "kind": "upcoming_earnings",
            "symbol": "GOOGL",
            "name": "Alphabet Inc.",
            "reports_at": "2026-06-03T20:00:00Z",
            "relative_label": "in 3 days",
        },
        "news": {
            **common,
            "kind": "news",
            "symbol": "NVDA",
            "headline": "NVIDIA unveils next-gen GPU",
            "source": "Reuters",
            "url": "https://example.com/news/nvda",
            "published_at": "2026-05-30T18:30:00Z",
            "summary": "The chipmaker announced...",
        },
    }


_EXPECTED_TYPE = {
    "dividends": DividendsCard,
    "pending_order_activity": PendingOrderActivityCard,
    "big_move": BigMoveCard,
    "watchlist_move": WatchlistMoveCard,
    "market_context": MarketContextCard,
    "radar_refresh": RadarRefreshCard,
    "earnings_result": EarningsResultCard,
    "upcoming_earnings": UpcomingEarningsCard,
    "news": NewsCard,
}

_ALL_KINDS = sorted(_payloads().keys())


class TestDiscriminatorDispatch:
    @pytest.mark.parametrize("kind", _ALL_KINDS)
    def test_payload_dispatches_to_correct_variant(self, kind):
        card = DigestCardAdapter.validate_python(_payloads()[kind])
        assert isinstance(card, _EXPECTED_TYPE[kind])
        assert card.kind == kind

    def test_unknown_kind_rejected(self):
        with pytest.raises(ValidationError):
            DigestCardAdapter.validate_python(
                {"kind": "mystery", "id": _ID}
            )

    def test_missing_kind_rejected(self):
        payload = _payloads()["big_move"]
        del payload["kind"]
        with pytest.raises(ValidationError):
            DigestCardAdapter.validate_python(payload)


class TestRoundTrip:
    @pytest.mark.parametrize("kind", _ALL_KINDS)
    def test_json_roundtrip_preserves_variant_and_values(self, kind):
        original = DigestCardAdapter.validate_python(_payloads()[kind])

        restored = DigestCardAdapter.validate_json(original.model_dump_json())

        assert isinstance(restored, _EXPECTED_TYPE[kind])
        assert restored == original

    @pytest.mark.parametrize("kind", _ALL_KINDS)
    def test_dump_always_carries_kind_discriminator(self, kind):
        card = DigestCardAdapter.validate_python(_payloads()[kind])
        assert card.model_dump(mode="json")["kind"] == kind

    def test_common_fields_round_trip(self):
        card = DigestCardAdapter.validate_python(_payloads()["news"])
        assert str(card.id) == _ID
        assert card.priority == 5
        assert card.related_symbols == ["AAPL"]
        assert card.card_context == {"k": "v"}

    def test_list_adapter_dispatches_every_variant(self):
        payloads = [_payloads()[k] for k in _ALL_KINDS]

        restored = DigestCardListAdapter.validate_python(payloads)

        assert len(restored) == len(_ALL_KINDS)
        assert {c.kind for c in restored} == set(_ALL_KINDS)

    def test_list_json_roundtrip_preserves_order_and_variants(self):
        payloads = [_payloads()[k] for k in _ALL_KINDS]
        original = DigestCardListAdapter.validate_python(payloads)

        restored = DigestCardListAdapter.validate_json(
            DigestCardListAdapter.dump_json(original)
        )

        assert restored == original


class TestMoneyQtyPctSerialization:
    def test_money_serializes_as_two_decimal_string(self):
        card = DigestCardAdapter.validate_python(_payloads()["dividends"])
        assert card.model_dump(mode="json")["total_amount"] == "1.20"

    def test_pct_serializes_as_four_decimal_string(self):
        card = DigestCardAdapter.validate_python(_payloads()["big_move"])
        assert card.model_dump(mode="json")["change_pct"] == "0.1000"

    def test_negative_change_round_trips(self):
        card = DigestCardAdapter.validate_python(_payloads()["watchlist_move"])
        dumped = card.model_dump(mode="json")
        assert dumped["change_abs"] == "-7.50"
        assert dumped["change_pct"] == "-0.0500"

    def test_optional_money_fields_allow_none(self):
        payload = _payloads()["earnings_result"]
        payload["eps_actual"] = None
        payload["stock_reaction_pct"] = None
        card = DigestCardAdapter.validate_python(payload)
        assert card.eps_actual is None
        assert card.stock_reaction_pct is None


class TestVariantInvariants:
    def test_market_context_rejects_unknown_direction(self):
        payload = _payloads()["market_context"]
        payload["direction"] = "sideways"
        with pytest.raises(ValidationError):
            DigestCardAdapter.validate_python(payload)

    def test_order_activity_rejects_unknown_side(self):
        with pytest.raises(ValidationError):
            OrderActivityItem(symbol="AAPL", side="hold")  # type: ignore[arg-type]

    def test_news_symbol_optional(self):
        payload = _payloads()["news"]
        payload["symbol"] = None
        card = DigestCardAdapter.validate_python(payload)
        assert isinstance(card, NewsCard)
        assert card.symbol is None
