"""RadarLLM — the pick + label-generation step of the radar pipeline.

Stage 3 of the batch (product spec §13.4). Given T3's bucket-tagged
candidate pool and the user's context, a single Claude call selects 5–7
stocks and writes one descriptive label each, then the output runs through
schema + safety validation.

The LLM does the two judgments the static pieces can't:

1. **Dynamic quality lens** — it reads `risk_tolerance` and leans the picks
   accordingly (conservative → mature / dividend names; aggressive →
   growth-tolerant). The static gate is one-size-fits-all and can't.
2. **Underweight-sector judgment** — there is no target-allocation model, so
   the model infers which sectors the user is light in from their holdings
   and favors diversification picks.

Spec §13.4 frames every item as "worth knowing about," never "you should
buy this." Two things enforce that: the prompt, and a post-validation
deny-list that rejects prescriptive labels regardless of what the model
returns. A rejected batch gets one corrective retry; if ≥5 picks still
validate the offenders are dropped, otherwise the stage raises
``RadarJobError`` and T5 lets ARQ retry the whole task.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Literal

import structlog
from anthropic import APIError, AsyncAnthropic
from anthropic.types import Message
from pydantic import BaseModel, Field, ValidationError

from app.config import settings
from app.services.radar_job import RadarJobError
from app.services.radar_job.candidate_sourcer import (
    BUCKET_BROAD_NOTABLE,
    BUCKET_DIVERSIFICATION,
    BUCKET_OWNED_SECTOR,
    BUCKET_UPCOMING_EVENT,
    Candidate,
)

logger = structlog.get_logger(__name__)

# Resolved independently of the chat model (`app.ai.models.MAIN`) and
# env-overridable via RADAR_LLM_MODEL: radar runs per-user-per-week at scale,
# so it can be pinned to a cheaper tier without moving the chat model. Tunable
# per SEV-609 open item ("revisit if label quality insufficient").
RADAR_LLM_MODEL = settings.radar_llm_model
MAX_OUTPUT_TOKENS = 1024

MIN_PICKS = 5
MAX_PICKS = 7

TOOL_NAME = "submit_radar_picks"

# Substring match, not word-boundary, is deliberate: it catches inflections
# ("buying", "selling", "recommended") that a beginner-facing surface must
# still treat as prescriptive. Spec §13.4 deny-list.
PRESCRIPTIVE_TERMS: tuple[str, ...] = (
    "buy",
    "sell",
    "should",
    "recommend",
    "must",
    "pick up",
    "we like",
    "our top pick",
)


@dataclass
class OwnedPosition:
    symbol: str
    sector: str | None


@dataclass
class UserContext:
    """Everything the pick step needs about one user, gathered by the T5
    orchestrator from `UserProfile` / `UserFinancialProfile`, live Alpaca
    positions, and existing favorited radar items."""

    risk_tolerance: str | None = None
    age: int | None = None
    goals: list[str] = field(default_factory=list)
    positions: list[OwnedPosition] = field(default_factory=list)
    favorited_symbols: list[str] = field(default_factory=list)


class RadarPick(BaseModel):
    symbol: str
    label: str = Field(max_length=120)
    bucket: Literal[
        "owned_sector",
        "diversification",
        "upcoming_event",
        "broad_notable",
    ]
    relevance: float = Field(ge=0, le=1)


class RadarLLMOutput(BaseModel):
    picks: list[RadarPick] = Field(min_length=MIN_PICKS, max_length=MAX_PICKS)


def find_prescriptive_terms(label: str) -> list[str]:
    """Deny-listed terms present in `label`, case-insensitive (empty = clean)."""
    lowered = label.lower()
    return [term for term in PRESCRIPTIVE_TERMS if term in lowered]


def validate_pick(
    pick: RadarPick, pool_by_symbol: dict[str, Candidate]
) -> list[str]:
    """Post-schema safety checks for one pick; empty list means it passed.

    Catches the three failure modes the Pydantic schema can't: prescriptive
    labels, hallucinated symbols (not in the pool), and a bucket that doesn't
    match how the pool tagged the symbol.
    """
    issues: list[str] = []

    terms = find_prescriptive_terms(pick.label)
    if terms:
        issues.append(f"prescriptive language ({', '.join(terms)})")

    candidate = pool_by_symbol.get(pick.symbol.upper())
    if candidate is None:
        issues.append("symbol not in candidate pool")
    elif candidate.bucket != pick.bucket:
        issues.append(f"bucket should be {candidate.bucket}, not {pick.bucket}")

    return issues


class RadarLLM:
    def __init__(self, anthropic: AsyncAnthropic) -> None:
        self._client = anthropic

    async def pick(
        self, pool: list[Candidate], user_ctx: UserContext
    ) -> list[RadarPick]:
        """Pick 5–7 validated radar items from `pool` for the given user.

        Calls Claude once; if the result has schema or safety problems it
        retries once with corrective feedback and then drops any remaining
        offenders if ≥5 valid picks survive. Raises ``RadarJobError`` if the
        retry still can't yield five clean picks.
        """
        pool_by_symbol = {c.symbol.upper(): c for c in pool}
        user_message = _build_user_message(pool, user_ctx)

        output = await self._invoke([{"role": "user", "content": user_message}])
        valid, problems = _partition(output, pool_by_symbol)
        if output is not None and not problems:
            return _ranked(valid)

        retry_messages = [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": _echo_picks(output)},
            {"role": "user", "content": _corrective_feedback(output, problems)},
        ]
        retry = await self._invoke(retry_messages)
        valid, problems = _partition(retry, pool_by_symbol)
        if len(valid) >= MIN_PICKS:
            if problems:
                logger.info("radar_llm_dropped_offenders", dropped=len(problems))
            return _ranked(valid)[:MAX_PICKS]

        logger.warning(
            "radar_llm_validation_failed",
            valid=len(valid),
            problems=problems,
        )
        raise RadarJobError("llm_validation_failed")

    async def _invoke(
        self, messages: list[dict[str, Any]]
    ) -> RadarLLMOutput | None:
        """One forced-tool call. Returns None on a missing/invalid tool result
        so the caller can retry rather than crash on malformed model output.

        Provider failures (rate limit, 5xx, transport) are re-raised as
        ``RadarJobError`` so the orchestrator catches one failure type rather
        than a raw ``anthropic.APIError``."""
        try:
            response = await self._client.messages.create(
                model=RADAR_LLM_MODEL,
                max_tokens=MAX_OUTPUT_TOKENS,
                system=_SYSTEM_PROMPT,
                messages=messages,
                tools=[_pick_tool()],
                tool_choice={"type": "tool", "name": TOOL_NAME},
            )
        except APIError as exc:
            logger.warning("radar_llm_provider_error", error=str(exc))
            raise RadarJobError("llm_provider_error") from exc
        raw = _extract_tool_input(response)
        if raw is None:
            logger.warning("radar_llm_no_tool_use")
            return None
        try:
            return RadarLLMOutput.model_validate(raw)
        except ValidationError as exc:
            logger.warning("radar_llm_schema_invalid", errors=exc.error_count())
            return None


def _partition(
    output: RadarLLMOutput | None, pool_by_symbol: dict[str, Candidate]
) -> tuple[list[RadarPick], dict[str, list[str]]]:
    valid: list[RadarPick] = []
    problems: dict[str, list[str]] = {}
    if output is None:
        return valid, problems
    seen: set[str] = set()
    for pick in output.picks:
        key = pick.symbol.upper()
        issues = validate_pick(pick, pool_by_symbol)
        if key in seen:
            issues.append("duplicate symbol (already selected)")
        if issues:
            problems.setdefault(key, []).extend(issues)
            continue
        seen.add(key)
        valid.append(_canonical_symbol(pick, pool_by_symbol))
    return valid, problems


def _ranked(picks: list[RadarPick]) -> list[RadarPick]:
    return sorted(picks, key=lambda p: p.relevance, reverse=True)


def _canonical_symbol(
    pick: RadarPick, pool_by_symbol: dict[str, Candidate]
) -> RadarPick:
    canonical = pool_by_symbol[pick.symbol.upper()].symbol
    if canonical == pick.symbol:
        return pick
    return pick.model_copy(update={"symbol": canonical})


def _extract_tool_input(response: Message) -> dict[str, Any] | None:
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == TOOL_NAME:
            return block.input
    return None


def _pick_tool() -> dict[str, Any]:
    return {
        "name": TOOL_NAME,
        "description": "Return this week's final 5–7 radar picks with a "
        "descriptive label and relevance score for each.",
        "input_schema": RadarLLMOutput.model_json_schema(),
    }


_SYSTEM_PROMPT = """\
You are curating Riley's Radar — a weekly stock-discovery surface in a \
beginner-friendly brokerage app. The surface frames stocks as "worth knowing \
about," never as advice to act.

Pick 5–7 stocks from the candidate pool and write one short label for each. \
Follow these rules:

- Span the buckets — don't take every pick from one.
- Apply Riley's risk profile as a quality lens: conservative → mature, \
lower-volatility, dividend-paying names; aggressive → higher-growth, \
higher-beta names are acceptable.
- Infer which sectors Riley is underweight in from her holdings and favor \
diversification picks accordingly.
- Each label is at most 120 characters and DESCRIPTIVE, never prescriptive. \
State a fact about the company or an upcoming event; never tell her to act.
    GOOD: "Major chipmaker in a sector you don't currently own"
    GOOD: "Reports earnings Thursday — second-largest US bank"
    BAD:  "Great buying opportunity"
    BAD:  "You should add this to diversify"
- Only pick symbols that appear in the candidate pool, and use each pick's \
bucket exactly as the pool tags it.
- Set relevance from 0 to 1 for how well each pick fits Riley.

Call the submit_radar_picks tool with your final selection."""


_BUCKET_ORDER = (
    BUCKET_OWNED_SECTOR,
    BUCKET_DIVERSIFICATION,
    BUCKET_UPCOMING_EVENT,
    BUCKET_BROAD_NOTABLE,
)

_BUCKET_HINTS = {
    BUCKET_OWNED_SECTOR: "sectors Riley already holds",
    BUCKET_DIVERSIFICATION: "sectors Riley has no exposure to",
    BUCKET_UPCOMING_EVENT: "earnings or dividend in the next two weeks",
    BUCKET_BROAD_NOTABLE: "large, widely-followed names",
}


def _build_user_message(pool: list[Candidate], ctx: UserContext) -> str:
    lines = [
        "Riley's profile:",
        f"- Risk tolerance: {ctx.risk_tolerance or 'unknown'}",
        f"- Age: {ctx.age if ctx.age is not None else 'unknown'}",
        f"- Goals: {', '.join(ctx.goals) if ctx.goals else 'not specified'}",
        "",
    ]

    if ctx.positions:
        lines.append("Riley's current holdings (symbol — sector):")
        lines += [
            f"- {p.symbol} — {p.sector or 'unknown sector'}"
            for p in ctx.positions
        ]
    else:
        lines.append("Riley's current holdings: none yet (first batch).")
    lines.append("")

    if ctx.favorited_symbols:
        lines.append(
            "Already on her radar (do not re-pick): "
            + ", ".join(ctx.favorited_symbols)
        )
    else:
        lines.append("Already on her radar: nothing yet.")
    lines.append("")

    lines.append(
        "Candidate pool — pick ONLY from these symbols, and use each one's "
        "bucket exactly as tagged:"
    )
    by_bucket: dict[str, list[Candidate]] = defaultdict(list)
    for candidate in pool:
        by_bucket[candidate.bucket].append(candidate)

    ordered = [b for b in _BUCKET_ORDER if b in by_bucket]
    ordered += [b for b in by_bucket if b not in _BUCKET_ORDER]
    for bucket in ordered:
        hint = _BUCKET_HINTS.get(bucket)
        header = f"[{bucket}]" + (f" — {hint}" if hint else "")
        lines.append("")
        lines.append(header)
        lines += [_candidate_line(c) for c in by_bucket[bucket]]

    lines.append("")
    lines.append(
        "Select 5–7 picks. For each: symbol (from the pool), a descriptive "
        "label of at most 120 characters, the bucket exactly as tagged above, "
        "and a relevance score from 0 to 1."
    )
    return "\n".join(lines)


def _candidate_line(c: Candidate) -> str:
    parts = [f"{c.symbol} ({c.name})"]
    if c.sector:
        parts.append(c.sector)
    if c.market_cap:
        parts.append(f"mkt cap {_fmt_market_cap(c.market_cap)}")
    if c.last_price is not None:
        parts.append(f"${c.last_price}")
    if c.one_month_return_pct is not None:
        parts.append(f"1mo {c.one_month_return_pct}%")
    if c.next_earnings_date is not None:
        parts.append(f"earnings {c.next_earnings_date.isoformat()}")
    if c.next_dividend_date is not None:
        parts.append(f"ex-div {c.next_dividend_date.isoformat()}")
    return "- " + " · ".join(parts)


def _fmt_market_cap(cap: int) -> str:
    if cap >= 1_000_000_000_000:
        return f"${cap / 1_000_000_000_000:.1f}T"
    if cap >= 1_000_000_000:
        return f"${cap / 1_000_000_000:.1f}B"
    if cap >= 1_000_000:
        return f"${cap / 1_000_000:.1f}M"
    return f"${cap}"


def _echo_picks(output: RadarLLMOutput | None) -> str:
    if output is None:
        return "(no valid picks returned)"
    return "\n".join(
        f"- {p.symbol} [{p.bucket}] (relevance {p.relevance}): {p.label}"
        for p in output.picks
    )


def _corrective_feedback(
    output: RadarLLMOutput | None, problems: dict[str, list[str]]
) -> str:
    if output is None or not problems:
        return (
            "Your previous response did not fit the required format. Return "
            "5–7 picks, each with a symbol from the candidate pool, a label of "
            "at most 120 characters, the correct bucket, and a relevance score "
            "between 0 and 1. Call the submit_radar_picks tool again."
        )
    lines = ["Your previous picks had problems:"]
    lines += [
        f"- {symbol}: {'; '.join(issues)}" for symbol, issues in problems.items()
    ]
    lines.append("")
    lines.append(
        'Rewrite every label to be DESCRIPTIVE, never prescriptive (no "buy", '
        '"sell", "should", "recommend", "must", or similar). Pick only symbols '
        "from the candidate pool and keep each pick's bucket exactly as tagged. "
        "Return 5–7 valid picks."
    )
    return "\n".join(lines)
