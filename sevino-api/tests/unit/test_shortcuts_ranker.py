"""Unit tests for the shortcut ranker."""

from app.schemas.shortcuts import Shortcut, ShortcutCategory
from app.services.shortcuts import ranker


def _items(category: ShortcutCategory, n: int) -> list[Shortcut]:
    return [
        Shortcut.create(text=f"{category}-{i}", category=category)
        for i in range(n)
    ]


def test_first_time_leads_and_pads_with_quiet_state():
    rules = {
        "first_time": _items("first_time", 3),
        "quiet_state": _items("quiet_state", 4),
    }
    result = ranker.rank(rules)
    assert [s.category for s in result] == ["first_time"] * 3 + ["quiet_state"] * 4


def test_caps_at_max_items():
    rules = {
        "first_time": _items("first_time", 10),
        "quiet_state": _items("quiet_state", 10),
    }
    result = ranker.rank(rules)
    assert len(result) == ranker.MAX_ITEMS
    assert [s.category for s in result] == ["first_time"] * 10 + ["quiet_state"] * 3


def test_quiet_state_only_when_no_first_time():
    rules = {"first_time": [], "quiet_state": _items("quiet_state", 5)}
    result = ranker.rank(rules)
    assert len(result) == 5
    assert all(s.category == "quiet_state" for s in result)
