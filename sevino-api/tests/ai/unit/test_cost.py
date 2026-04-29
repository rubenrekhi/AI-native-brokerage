"""Tests for ``app.ai.runtime.cost`` (SEV-473, AI v0 plan A2.5)."""

import pytest
from anthropic.types import Usage
from anthropic.types.cache_creation import CacheCreation

from app.ai.runtime.cost import _PRICING, cost_usd_micros


class TestSonnet:
    """Sonnet 4.6 — the default main model. Rates: $3/$15/$0.30/$3.75/$6 per MTok."""

    def test_one_million_input_tokens_costs_three_dollars(self):
        usage = Usage(input_tokens=1_000_000, output_tokens=0)
        assert cost_usd_micros(usage, "claude-sonnet-4-6") == 3_000_000

    def test_one_million_output_tokens_costs_fifteen_dollars(self):
        usage = Usage(input_tokens=0, output_tokens=1_000_000)
        assert cost_usd_micros(usage, "claude-sonnet-4-6") == 15_000_000

    def test_input_and_output_summed(self):
        # 1000 × $3/MTok + 500 × $15/MTok = 3000 + 7500 = 10,500 microUSD
        usage = Usage(input_tokens=1000, output_tokens=500)
        assert cost_usd_micros(usage, "claude-sonnet-4-6") == 10_500


class TestHaiku:
    def test_input_and_output(self):
        # 100 × $1/MTok + 200 × $5/MTok = 100 + 1000 = 1100 microUSD
        usage = Usage(input_tokens=100, output_tokens=200)
        assert cost_usd_micros(usage, "claude-haiku-4-5-20251001") == 1_100


class TestOpus:
    def test_input_and_output(self):
        # 100 × $15/MTok + 50 × $75/MTok = 1500 + 3750 = 5250 microUSD
        usage = Usage(input_tokens=100, output_tokens=50)
        assert cost_usd_micros(usage, "claude-opus-4-7") == 5_250


class TestCacheRead:
    def test_cache_read_uses_cache_read_rate(self):
        # Cache reads are 10% of input rate for all current models.
        # 1M cache_read × $0.30/MTok = 300,000 microUSD
        usage = Usage(
            input_tokens=0,
            output_tokens=0,
            cache_read_input_tokens=1_000_000,
        )
        assert cost_usd_micros(usage, "claude-sonnet-4-6") == 300_000

    def test_cache_read_added_to_input_and_output(self):
        # 1000 × 3 + 500 × 15 + 200 × 0.30 = 3000 + 7500 + 60 = 10560
        usage = Usage(
            input_tokens=1000,
            output_tokens=500,
            cache_read_input_tokens=200,
        )
        assert cost_usd_micros(usage, "claude-sonnet-4-6") == 10_560


class TestCacheWrite:
    def test_cache_write_5m_via_breakdown(self):
        # 1M ephemeral_5m × $3.75/MTok = 3,750,000 microUSD
        usage = Usage(
            input_tokens=0,
            output_tokens=0,
            cache_creation_input_tokens=1_000_000,
            cache_creation=CacheCreation(
                ephemeral_5m_input_tokens=1_000_000,
                ephemeral_1h_input_tokens=0,
            ),
        )
        assert cost_usd_micros(usage, "claude-sonnet-4-6") == 3_750_000

    def test_cache_write_1h_via_breakdown(self):
        # 1M ephemeral_1h × $6/MTok = 6,000,000 microUSD
        usage = Usage(
            input_tokens=0,
            output_tokens=0,
            cache_creation_input_tokens=1_000_000,
            cache_creation=CacheCreation(
                ephemeral_5m_input_tokens=0,
                ephemeral_1h_input_tokens=1_000_000,
            ),
        )
        assert cost_usd_micros(usage, "claude-sonnet-4-6") == 6_000_000

    def test_cache_write_mixed_5m_and_1h(self):
        # 100 × 3.75 + 200 × 6 = 375 + 1200 = 1575 microUSD
        usage = Usage(
            input_tokens=0,
            output_tokens=0,
            cache_creation_input_tokens=300,
            cache_creation=CacheCreation(
                ephemeral_5m_input_tokens=100,
                ephemeral_1h_input_tokens=200,
            ),
        )
        assert cost_usd_micros(usage, "claude-sonnet-4-6") == 1_575

    def test_cache_write_falls_back_to_5m_when_breakdown_absent(self):
        # If only the legacy total is set, assume the 5m rate (v0 only writes
        # 5m caches via `cache_control: {"type": "ephemeral"}`).
        usage = Usage(
            input_tokens=0,
            output_tokens=0,
            cache_creation_input_tokens=1_000_000,
            cache_creation=None,
        )
        assert cost_usd_micros(usage, "claude-sonnet-4-6") == 3_750_000

    def test_breakdown_takes_precedence_over_total(self):
        # If both fields are set with conflicting values, the breakdown wins
        # — guards against double counting if cache_creation_input_tokens
        # were ever stale.
        usage = Usage(
            input_tokens=0,
            output_tokens=0,
            cache_creation_input_tokens=999_999,
            cache_creation=CacheCreation(
                ephemeral_5m_input_tokens=1_000_000,
                ephemeral_1h_input_tokens=0,
            ),
        )
        assert cost_usd_micros(usage, "claude-sonnet-4-6") == 3_750_000


class TestThinkingBilling:
    """Per A2.5: thinking is billed at the output rate. Anthropic already
    includes thinking tokens in ``Usage.output_tokens``, so the calculator
    has no dedicated thinking term — the test below pins that contract."""

    def test_thinking_already_in_output_tokens_is_billed_at_output_rate(self):
        # A turn with 1000 thinking + 500 visible output reports
        # output_tokens=1500. Expect 1500 × $15/MTok = 22,500 microUSD.
        usage = Usage(input_tokens=0, output_tokens=1500)
        assert cost_usd_micros(usage, "claude-sonnet-4-6") == 22_500


class TestOptionalFields:
    def test_none_cache_fields_treated_as_zero(self):
        usage = Usage(
            input_tokens=1000,
            output_tokens=500,
            cache_read_input_tokens=None,
            cache_creation_input_tokens=None,
            cache_creation=None,
        )
        # 1000 × 3 + 500 × 15 = 10,500
        assert cost_usd_micros(usage, "claude-sonnet-4-6") == 10_500

    def test_zero_token_usage_costs_nothing(self):
        usage = Usage(input_tokens=0, output_tokens=0)
        assert cost_usd_micros(usage, "claude-sonnet-4-6") == 0


class TestFullUsageMix:
    def test_all_categories_summed_correctly(self):
        # 1000 input × 3 = 3000
        # 500 output × 15 = 7500
        # 200 cache_read × 0.30 = 60
        # 100 cache_write_5m × 3.75 = 375
        # 50 cache_write_1h × 6 = 300
        # Total = 11,235
        usage = Usage(
            input_tokens=1000,
            output_tokens=500,
            cache_read_input_tokens=200,
            cache_creation_input_tokens=150,
            cache_creation=CacheCreation(
                ephemeral_5m_input_tokens=100,
                ephemeral_1h_input_tokens=50,
            ),
        )
        assert cost_usd_micros(usage, "claude-sonnet-4-6") == 11_235


class TestUnknownModel:
    def test_unknown_model_raises_value_error(self):
        usage = Usage(input_tokens=100, output_tokens=50)
        with pytest.raises(ValueError, match=r"No pricing entry for model_id"):
            cost_usd_micros(usage, "claude-not-a-real-model")

    def test_error_message_includes_unknown_model_id(self):
        usage = Usage(input_tokens=100, output_tokens=50)
        with pytest.raises(ValueError) as exc_info:
            cost_usd_micros(usage, "claude-not-a-real-model")
        assert "claude-not-a-real-model" in str(exc_info.value)

    def test_error_message_lists_known_models(self):
        # The message should help the caller fix the call site by surfacing
        # the supported model ids.
        usage = Usage(input_tokens=100, output_tokens=50)
        with pytest.raises(ValueError) as exc_info:
            cost_usd_micros(usage, "claude-not-a-real-model")
        msg = str(exc_info.value)
        for known in _PRICING:
            assert known in msg

    def test_empty_string_model_id_raises(self):
        usage = Usage(input_tokens=100, output_tokens=50)
        with pytest.raises(ValueError):
            cost_usd_micros(usage, "")


class TestPureFunction:
    """A2.5 acceptance: pure function (no side effects, no network)."""

    def test_does_not_mutate_usage(self):
        usage = Usage(
            input_tokens=1000,
            output_tokens=500,
            cache_read_input_tokens=100,
            cache_creation_input_tokens=50,
            cache_creation=CacheCreation(
                ephemeral_5m_input_tokens=50,
                ephemeral_1h_input_tokens=0,
            ),
        )
        snapshot = usage.model_dump()
        cost_usd_micros(usage, "claude-sonnet-4-6")
        assert usage.model_dump() == snapshot

    def test_repeated_calls_are_deterministic(self):
        usage = Usage(input_tokens=1234, output_tokens=567)
        first = cost_usd_micros(usage, "claude-sonnet-4-6")
        second = cost_usd_micros(usage, "claude-sonnet-4-6")
        third = cost_usd_micros(usage, "claude-sonnet-4-6")
        assert first == second == third
