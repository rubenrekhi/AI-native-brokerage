"""Builds the per-user profile block prepended to the agent's system context.

This is a stable, per-user summary of who the user is — their name plus the
investing profile collected during onboarding (experience, risk tolerance,
goals, financial capacity). It lets the model tailor explanations and
recommendations to the person it is actually talking to.

Unlike the live time context, the profile changes rarely, so it belongs high
in the cache prefix (the prefix is ordered ``tools → system → messages``): it
is sent as a second ``system`` block — after the static prompt, before the
conversation history — with its own cache breakpoint, so it caches across all
of a user's turns and conversations. The render must be deterministic: a given
profile state must produce byte-identical output every turn or it would
silently bust its own cache. See ``runtime/loop.py`` and
``docs/ai/ai-harness.md`` §"Prompt caching".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.user_financial_profile import UserFinancialProfile
    from app.models.user_profile import UserProfile

# (attribute on UserFinancialProfile, human label). Order is fixed so the
# rendered block is byte-stable across turns for a given profile state.
_SCALAR_FIELDS: list[tuple[str, str]] = [
    ("experience_level", "Investing experience"),
    ("risk_tolerance", "Risk tolerance"),
    ("time_horizon", "Time horizon"),
    ("max_loss_tolerance", "Max acceptable loss"),
    ("income_stability", "Income stability"),
    ("annual_income", "Annual income"),
    ("net_worth", "Net worth"),
    ("liquid_net_worth", "Liquid net worth"),
]
_LIST_FIELDS: list[tuple[str, str]] = [
    ("investment_goals", "Investing goals"),
    ("financial_worries", "Financial concerns"),
]


def _humanize(value: str) -> str:
    # Onboarding stores a mix of display-ready strings ("$50K – $99K",
    # "5-10 years") and snake_case codes ("invest_regularly", "grow_wealth").
    # Swapping underscores for spaces reads the codes; display strings (no
    # underscores) pass through untouched.
    return value.replace("_", " ").strip()


def build_user_profile_context(
    profile: "UserProfile | None",
    financial: "UserFinancialProfile | None",
) -> str | None:
    """Render the user-profile system block, or ``None`` if nothing is known.

    Includes only populated fields (a half-finished onboarding renders just
    what it has) and only tailoring-relevant data — never raw PII (date of
    birth, address, SSN, contact details), which the model doesn't need to
    shape its responses and shouldn't carry in every request.
    """
    name: str | None = None
    if profile is not None:
        name = profile.preferred_name or profile.first_name

    facts: list[str] = []
    if financial is not None:
        for attr, label in _SCALAR_FIELDS:
            value = getattr(financial, attr, None)
            if isinstance(value, str) and value.strip():
                facts.append(f"- {label}: {_humanize(value)}")
        for attr, label in _LIST_FIELDS:
            value = getattr(financial, attr, None)
            if isinstance(value, list):
                items = [
                    _humanize(v)
                    for v in value
                    if isinstance(v, str) and v.strip()
                ]
                if items:
                    facts.append(f"- {label}: {', '.join(items)}")

    if name is None and not facts:
        return None

    if name:
        intro = (
            f"You are speaking with {name}. Use what you know about them to "
            "tailor your explanations and recommendations to their experience, "
            "goals, and risk tolerance."
        )
    else:
        intro = (
            "Use what you know about this user to tailor your explanations and "
            "recommendations to their experience, goals, and risk tolerance."
        )

    block = f"## About the user\n\n{intro}"
    if facts:
        block += "\n\n" + "\n".join(facts)
    return block
