"""Anthropic-backed curation for Daily Digest candidates.

The curator both filters (drops noise / confusing-for-beginner cards) and
orders the survivors. It never rewrites cards, which keeps the "descriptive,
never prescriptive" guardrail enforceable on the persisted card payloads and
makes fallback deterministic.

Output contract: the model returns an ordered JSON array of objects of the
form ``{"id": "...", "reason": "..."}``. ``ordered_ids`` and a parallel
``reasons`` map flow out via ``RerankResult``; reasons are persisted onto
``card.card_context["gate_reason"]`` for operator review.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from anthropic import APIError
import sentry_sdk

from app.config import settings
from app.services.digest.cards import DigestCard
from app.services.digest.types import CardCandidate, DigestContext

MAX_RERANKED_CARDS = 7
SHORTLIST_LIMIT = 15
MAX_OUTPUT_TOKENS = 1024
_ET = ZoneInfo("America/New_York")

_PRESCRIPTIVE_RE = re.compile(
    r"\b("
    r"consider|you should|you could|you may want to|"
    r"buy|sell|hold|trim|add|reduce|increase|decrease|"
    r"rebalance|allocate|invest|exit|enter"
    r")\b",
    re.IGNORECASE,
)
_FACTUAL_CONTEXT_RE = re.compile(
    r"\b("
    r"analyst|analysts|company|companies|investors|traders|market|markets|"
    r"shares|stock|stocks|order|orders"
    r")\s+"
    r"(buy|sell|hold|trim|add|reduce|increase|decrease|rebalance|allocate|"
    r"invest|exit|enter)\b",
    re.IGNORECASE,
)
_USER_COPY_KEYS = frozenset(
    {
        "beat_miss_highlights",
        "headline",
        "name",
        "period_label",
        "reason",
        "summary",
    }
)
# Fallback reasons that are normal operation, not failures: too few cards to
# rerank, or no Anthropic client configured (dev). These stay breadcrumb-only
# so they don't generate Sentry noise; every other reason is an AI misbehaving.
_BENIGN_FALLBACK_REASONS = frozenset({"no_candidates", "anthropic_unavailable"})


class AnthropicMessagesClient(Protocol):
    async def create(self, **kwargs: Any) -> Any: ...


class AnthropicClient(Protocol):
    messages: AnthropicMessagesClient


@dataclass(frozen=True)
class RerankResult:
    ordered_ids: list[uuid.UUID]
    used_fallback: bool
    fallback_reason: str | None = None
    reasons: dict[uuid.UUID, str] = field(default_factory=dict)


class Reranker(Protocol):
    async def rank_with_metadata(
        self,
        candidates: list[CardCandidate],
        ctx: DigestContext,
        *,
        fallback_order: list[CardCandidate] | None = None,
    ) -> RerankResult: ...


class DigestReranker:
    def __init__(
        self,
        anthropic: AnthropicClient | None,
        *,
        model: str | None = None,
    ) -> None:
        self._anthropic = anthropic
        self._model = model or settings.anthropic_model_main

    async def rank(
        self,
        candidates: list[CardCandidate],
        ctx: DigestContext,
        *,
        fallback_order: list[CardCandidate] | None = None,
    ) -> list[uuid.UUID]:
        result = await self.rank_with_metadata(
            candidates, ctx, fallback_order=fallback_order
        )
        return result.ordered_ids

    async def rank_with_metadata(
        self,
        candidates: list[CardCandidate],
        ctx: DigestContext,
        *,
        fallback_order: list[CardCandidate] | None = None,
    ) -> RerankResult:
        """Return ordered + filtered card IDs with curator reasons.

        Anthropic output must be a JSON array of ``{"id", "reason"}``
        objects. The model both *drops* noise/confusing cards and orders
        the survivors — output length is 0 .. MAX_RERANKED_CARDS. Card
        payloads are scanned before the model call so prescriptive
        generator copy cannot be used as ranking context.
        """
        clean_candidates = _non_prescriptive_candidates(candidates)
        clean_ids = {candidate.card.id for candidate in clean_candidates}
        clean_fallback = [
            candidate
            for candidate in (fallback_order or candidates)
            if candidate.card.id in clean_ids
        ]
        fallback = _fallback_ids(clean_fallback)
        if not clean_candidates or self._anthropic is None:
            reason = (
                "no_candidates"
                if not clean_candidates
                else "anthropic_unavailable"
            )
            return _fallback_result(fallback, reason, ctx)

        candidate_ids = {str(candidate.card.id) for candidate in clean_candidates}
        try:
            response = await self._anthropic.messages.create(
                model=self._model,
                max_tokens=MAX_OUTPUT_TOKENS,
                temperature=0,
                system=_SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": _user_prompt(clean_candidates, ctx),
                    }
                ],
            )
        except APIError as exc:
            return _fallback_result(
                fallback, f"anthropic_api_error:{type(exc).__name__}", ctx
            )

        parsed = _parse_curator_output(response)
        if parsed is None:
            return _fallback_result(fallback, "invalid_json", ctx)
        if len(parsed) > MAX_RERANKED_CARDS:
            return _fallback_result(fallback, "invalid_card_count", ctx)
        ordered_ids_str = [item[0] for item in parsed]
        if len(set(ordered_ids_str)) != len(ordered_ids_str):
            return _fallback_result(fallback, "duplicate_card_ids", ctx)
        if any(card_id not in candidate_ids for card_id in ordered_ids_str):
            return _fallback_result(fallback, "unknown_card_id", ctx)
        ordered = [uuid.UUID(card_id) for card_id in ordered_ids_str]
        reasons = {uuid.UUID(card_id): reason for card_id, reason in parsed}
        return RerankResult(
            ordered_ids=ordered,
            used_fallback=False,
            reasons=reasons,
        )


def validate_non_prescriptive_cards(cards: list[DigestCard]) -> bool:
    return not _has_prescriptive_language(cards)


def _non_prescriptive_candidates(
    candidates: list[CardCandidate],
) -> list[CardCandidate]:
    return [
        candidate
        for candidate in candidates
        if not _has_prescriptive_language([candidate.card])
    ]


def _fallback_ids(candidates: list[CardCandidate]) -> list[uuid.UUID]:
    return [
        candidate.card.id
        for candidate in candidates[: min(MAX_RERANKED_CARDS, len(candidates))]
    ]


def _fallback_result(
    ids: list[uuid.UUID], reason: str, ctx: DigestContext
) -> RerankResult:
    sentry_sdk.add_breadcrumb(
        category="digest.reranker",
        message="fallback_to_heuristic_order",
        level="warning",
        data={"reason": reason},
    )
    if reason not in _BENIGN_FALLBACK_REASONS:
        # Anomalous fallbacks (Anthropic API errors, malformed/invalid output)
        # mean every digest is silently degrading to heuristic order. A
        # breadcrumb never surfaces without a later capture in the same scope,
        # so escalate to an alert ops can see.
        with sentry_sdk.new_scope() as scope:
            scope.set_tag("digest_component", "reranker")
            scope.set_tag("alert_type", "digest_reranker_fallback")
            scope.set_tag("fallback_reason", reason)
            scope.set_tag("user_id", str(ctx.user_id))
            scope.set_tag(
                "ny_local_date",
                ctx.market_state.as_of.astimezone(_ET).date().isoformat(),
            )
            sentry_sdk.capture_message(
                "digest_reranker_fallback",
                level="warning",
            )
    return RerankResult(
        ordered_ids=ids,
        used_fallback=True,
        fallback_reason=reason,
    )


def _parse_curator_output(response: Any) -> list[tuple[str, str]] | None:
    """Parse the curator response. Returns None on any structural failure.

    Expects a JSON array of ``{"id": str, "reason": str}`` objects.
    """
    text = _response_text(response).strip()
    if text.startswith("```"):
        text = _strip_code_fence(text)
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, list):
        return None
    parsed: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            return None
        card_id = item.get("id")
        reason = item.get("reason")
        if not isinstance(card_id, str) or not isinstance(reason, str):
            return None
        parsed.append((card_id, reason))
    return parsed


def _response_text(response: Any) -> str:
    parts: list[str] = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", ""))
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
    return "\n".join(parts)


def _strip_code_fence(text: str) -> str:
    lines = text.splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].startswith("```"):
        return "\n".join(lines[1:-1])
    return text


def _has_prescriptive_language(cards: list[DigestCard]) -> bool:
    for card in cards:
        if _has_prescriptive_value(card.model_dump(mode="json"), None):
            return True
    return False


def _has_prescriptive_value(value: Any, key: str | None) -> bool:
    if isinstance(value, str):
        return key in _USER_COPY_KEYS and _is_prescriptive_text(value)
    if isinstance(value, list):
        return any(_has_prescriptive_value(item, key) for item in value)
    if isinstance(value, dict):
        return any(
            _has_prescriptive_value(item, str(item_key))
            for item_key, item in value.items()
        )
    return False


def _is_prescriptive_text(text: str) -> bool:
    if text.strip().lower() in {"buy", "sell", "hold"}:
        return False
    if not _PRESCRIPTIVE_RE.search(text):
        return False
    return _FACTUAL_CONTEXT_RE.search(text) is None


def _user_prompt(candidates: list[CardCandidate], ctx: DigestContext) -> str:
    ny_local_date = ctx.market_state.as_of.astimezone(_ET).date().isoformat()
    payload = {
        "candidate_cards": [
            {
                "id": str(candidate.card.id),
                "event_type": candidate.event_type,
                "magnitude_score": candidate.magnitude_score,
                "related_symbols": candidate.related_symbols,
                "card": candidate.card.model_dump(mode="json"),
            }
            for candidate in candidates
        ],
        "top_10_holdings": _top_holdings(ctx),
        "financial_profile": _financial_profile(ctx),
        "market": {
            "ny_local_date": ny_local_date,
            "state": ctx.market_state.session,
        },
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _top_holdings(ctx: DigestContext) -> list[dict[str, Any]]:
    weighted: list[tuple[Decimal, dict[str, Any]]] = []
    market_values: dict[str, Decimal] = {}
    total = _decimal_or_none((ctx.portfolio_snapshot or {}).get("equity"))

    for holding in ctx.holdings:
        symbol = str(holding.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        market_value = _decimal_or_none(holding.get("market_value"))
        if market_value is not None:
            market_values[symbol] = market_value

    if total is None or total <= 0:
        total = sum(market_values.values(), Decimal("0"))

    for holding in ctx.holdings:
        symbol = str(holding.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        explicit = _weight_decimal(
            holding.get("portfolio_weight", holding.get("weight"))
        )
        weight = explicit
        if weight is None and total > 0:
            market_value = market_values.get(symbol)
            if market_value is not None:
                weight = market_value / total
        weight = max(weight or Decimal("0"), Decimal("0"))
        weighted.append(
            (
                weight,
                {
                    "symbol": symbol,
                    "name": holding.get("name") or holding.get("asset_name"),
                    "weight_pct": _format_weight_pct(weight),
                    "market_value": str(holding.get("market_value"))
                    if holding.get("market_value") is not None
                    else None,
                },
            )
        )

    weighted.sort(key=lambda item: item[0], reverse=True)
    return [item for _, item in weighted[:10]]


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value).strip().removesuffix("%"))
    except (InvalidOperation, ValueError):
        return None


def _weight_decimal(value: Any) -> Decimal | None:
    raw = _decimal_or_none(value)
    if raw is None:
        return None
    text = str(value).strip()
    if text.endswith("%") or raw > 1:
        return raw / Decimal("100")
    return raw


def _format_weight_pct(weight: Decimal) -> str:
    return str((weight * Decimal("100")).quantize(Decimal("0.01")))


def _financial_profile(ctx: DigestContext) -> dict[str, Any] | None:
    profile = ctx.financial_profile
    if profile is None:
        return None
    return {
        "risk_tolerance": profile.risk_tolerance,
        "goals": profile.investment_goals,
        "experience": profile.experience_level,
        "time_horizon": profile.time_horizon,
    }


_SYSTEM_PROMPT = """You curate Sevino's Daily Digest.

Pick the cards from the candidate set that are genuinely useful for the user
to read today, then order them most-important first.

Return ONLY a JSON array of objects:
[{"id": "<card-id>", "reason": "<one short sentence>"}, ...]

- Output length is 0 to 7. If nothing is useful, return [].
- Each id must come from the candidate set; no duplicates.
- "reason" is a short, internal note (one sentence) explaining why this card
  belongs in today's digest. It is for operators, not end users.
- Order matters — first = most important.

Drop cards when:
- The event is noise (e.g. a small move with no news driver).
- The card duplicates information already in another kept card.

Keep cards when:
- A holding, watchlist symbol, or index moved meaningfully with a clear driver.
- An earnings, dividend, or order event is relevant to the user's positions.
- News explains a real market or company event worth knowing about.

Cards must remain descriptive, never prescriptive — never tell users what to
do. Use portfolio composition, event magnitude, and the financial profile to
weight importance. A 10% move on the user's biggest holding outranks the same
move on a small holding.

BEGINNER MODE: if the user has no holdings (top_10_holdings is empty):
- ALWAYS keep RadarRefresh cards when present. The radar is the primary
  discovery surface for someone without a portfolio — it's how they find
  their first stock. The fact that the radar may list niche tickers is fine:
  it's a discovery list, not editorial content.
- For news, big_move, and other editorial cards, prefer well-known mega-cap
  names and explanatory market context. Drop news about niche or speculative
  tickers since beginners won't recognize them and can't act on them yet."""
