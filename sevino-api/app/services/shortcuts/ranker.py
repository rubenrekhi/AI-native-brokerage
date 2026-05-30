"""Ordering policy that merges per-category shortcut lists into the feed."""

from __future__ import annotations

from app.schemas.shortcuts import Shortcut

# iOS feed budget: 3 shortcuts inline above the chat input + 10 in the
# "more" overflow sheet.
MAX_ITEMS = 13


def rank(rules: dict[str, list[Shortcut]]) -> list[Shortcut]:
    """Merge category lists into the final ordered feed, capped at MAX_ITEMS.

    A non-empty ``first_time`` list takes precedence and leads the feed,
    padded with ``quiet_state``. Otherwise categories stack in priority
    order — ``portfolio_state`` (sorted by magnitude) first, then
    ``quiet_state`` fills the rest. Further categories join this ladder as
    later stages add them.
    """
    first_time = rules.get("first_time", [])
    quiet_state = rules.get("quiet_state", [])
    if first_time:
        return (first_time + quiet_state)[:MAX_ITEMS]

    ranked: list[Shortcut] = []
    ranked += sorted(
        rules.get("portfolio_state", []), key=lambda s: -s.magnitude
    )
    ranked += quiet_state
    return ranked[:MAX_ITEMS]
