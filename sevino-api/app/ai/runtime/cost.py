"""Per-invocation cost in microUSD.

Thinking is billed at the output rate and bundled into
``Usage.output_tokens``, so there's no separate thinking term.
"""

from __future__ import annotations

from dataclasses import dataclass

from anthropic.types import Usage


@dataclass(frozen=True)
class ModelPricing:
    # microUSD per token ( = USD per million tokens).
    input: float
    output: float
    cache_read: float
    cache_write_5m: float
    cache_write_1h: float


# $10 per 1,000 requests, verified 2026-05-13. Code execution is metered
# by container time and not on ``Usage``, so it's omitted here.
_WEB_SEARCH_RATE_USD_MICROS = 10_000
_WEB_FETCH_RATE_USD_MICROS = 10_000


# Source: https://www.anthropic.com/pricing#api
_PRICING: dict[str, ModelPricing] = {
    "claude-sonnet-4-6": ModelPricing(
        input=3.0,
        output=15.0,
        cache_read=0.30,
        cache_write_5m=3.75,
        cache_write_1h=6.0,
    ),
    "claude-opus-4-7": ModelPricing(
        input=15.0,
        output=75.0,
        cache_read=1.50,
        cache_write_5m=18.75,
        cache_write_1h=30.0,
    ),
    "claude-haiku-4-5-20251001": ModelPricing(
        input=1.0,
        output=5.0,
        cache_read=0.10,
        cache_write_5m=1.25,
        cache_write_1h=2.0,
    ),
}


def cost_usd_micros(usage: Usage, model_id: str) -> int:
    """Cost of one Anthropic call, in microUSD.

    Uses the per-TTL ``cache_creation`` breakdown when present; falls back
    to the 5-minute rate on the legacy total.
    """
    try:
        pricing = _PRICING[model_id]
    except KeyError:
        raise ValueError(
            f"No pricing entry for model_id={model_id!r}. "
            f"Add it to app.ai.runtime.cost._PRICING. "
            f"Known models: {sorted(_PRICING)}"
        ) from None

    cost = (
        usage.input_tokens * pricing.input
        + usage.output_tokens * pricing.output
        + (usage.cache_read_input_tokens or 0) * pricing.cache_read
    )

    if usage.cache_creation is not None:
        cost += (
            usage.cache_creation.ephemeral_5m_input_tokens * pricing.cache_write_5m
            + usage.cache_creation.ephemeral_1h_input_tokens * pricing.cache_write_1h
        )
    elif usage.cache_creation_input_tokens:
        cost += usage.cache_creation_input_tokens * pricing.cache_write_5m

    server_usage = usage.server_tool_use
    if server_usage is not None:
        cost += server_usage.web_search_requests * _WEB_SEARCH_RATE_USD_MICROS
        cost += server_usage.web_fetch_requests * _WEB_FETCH_RATE_USD_MICROS

    return round(cost)
