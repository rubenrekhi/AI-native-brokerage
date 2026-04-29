"""Cost calculator for Anthropic model invocations.

Per AI v0 plan A2.5 (sevino-api/docs/ai-v0-plan.md): pure function that
maps an Anthropic ``Usage`` payload + ``model_id`` to an integer microUSD
cost. Called per ``model_invocation`` and summed at end of turn.

Anthropic includes thinking tokens in ``Usage.output_tokens`` and bills
them at the output rate, so this module deliberately has no separate
thinking term. The plan calls this out explicitly: "thinking is billed at
output rate".
"""

from __future__ import annotations

from dataclasses import dataclass

from anthropic.types import Usage


@dataclass(frozen=True)
class ModelPricing:
    """Per-token cost in microUSD ( = USD per million tokens).

    ``cache_write_5m`` / ``cache_write_1h`` correspond to Anthropic's two
    ``ephemeral`` cache TTLs. v0 only uses 5-minute caches.
    """

    input: float
    output: float
    cache_read: float
    cache_write_5m: float
    cache_write_1h: float


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
    """Compute the cost of a single Anthropic API call, in microUSD.

    Cache writes use the per-TTL breakdown in ``usage.cache_creation`` when
    present (the SDK populates it whenever caching was used). When the
    breakdown is absent but the legacy total ``cache_creation_input_tokens``
    is set, the 5-minute rate is assumed — v0 only writes 5-minute caches.

    The result is rounded to the nearest microUSD using Python's default
    round-half-to-even, so tied half-microUSD costs may drift by ±1 µUSD —
    irrelevant at v0 billing precision.

    Raises ``ValueError`` if ``model_id`` has no entry in the rate table.
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

    return round(cost)
