"""Anthropic-backed ordering for Daily Digest candidates.

The reranker only chooses from the candidate set. It never rewrites cards,
which keeps the "descriptive, never prescriptive" guardrail enforceable on
the persisted card payloads and makes fallback deterministic.
"""

from __future__ import annotations

import json
import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from anthropic import APIError

from app.config import settings
from app.services.digest.cards import DigestCard
from app.services.digest.types import CardCandidate, DigestContext

MIN_RERANKED_CARDS = 3
MAX_RERANKED_CARDS = 7
SHORTLIST_LIMIT = 15
MAX_OUTPUT_TOKENS = 512
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


class AnthropicMessagesClient(Protocol):
    async def create(self, **kwargs: Any) -> Any: ...


class AnthropicClient(Protocol):
    messages: AnthropicMessagesClient


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
        """Return ordered card IDs, falling back to the heuristic order.

        Anthropic output must be a JSON array of candidate IDs. Candidate
        payloads are scanned before the model call so prescriptive generator
        copy cannot be used as ranking context.
        """
        clean_candidates = _non_prescriptive_candidates(candidates)
        clean_ids = {candidate.card.id for candidate in clean_candidates}
        clean_fallback = [
            candidate
            for candidate in (fallback_order or candidates)
            if candidate.card.id in clean_ids
        ]
        fallback = _fallback_ids(clean_fallback)
        if len(clean_candidates) < MIN_RERANKED_CARDS or self._anthropic is None:
            return fallback

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
        except APIError:
            return fallback

        ordered = _parse_ordered_ids(response)
        if ordered is None:
            return fallback
        if not MIN_RERANKED_CARDS <= len(ordered) <= MAX_RERANKED_CARDS:
            return fallback
        if len(set(ordered)) != len(ordered):
            return fallback
        if any(card_id not in candidate_ids for card_id in ordered):
            return fallback
        return [uuid.UUID(card_id) for card_id in ordered]


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


def _parse_ordered_ids(response: Any) -> list[str] | None:
    text = _response_text(response).strip()
    if text.startswith("```"):
        text = _strip_code_fence(text)
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        return None
    return raw


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


_SYSTEM_PROMPT = """You order Daily Digest cards for Sevino.

Return only an ordered JSON array of card IDs from the candidate set.
Select 3 to 7 entries.
Cards must remain descriptive, never prescriptive.
Use portfolio composition, event magnitude, and user-stated preferences from
the financial profile. A 10% move on the user's biggest holding outranks the
same move on a small holding. Put the most important card first."""
