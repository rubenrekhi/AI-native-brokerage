"""Unit tests for the ranker once all six categories are wired."""

from app.schemas.shortcuts import Shortcut, ShortcutCategory
from app.services.shortcuts import ranker


def _items(
    category: ShortcutCategory, n: int, *, magnitude: float = 0.0
) -> list[Shortcut]:
    return [
        Shortcut.create(
            text=f"{category}-{i}", category=category, magnitude=magnitude
        )
        for i in range(n)
    ]


def _full_rules() -> dict[str, list[Shortcut]]:
    return {
        "first_time": [],
        "portfolio_state": _items("portfolio_state", 2),
        "market_state": _items("market_state", 2),
        "radar_update": _items("radar_update", 1),
        "capability": _items("capability", 2),
        "quiet_state": _items("quiet_state", 5),
    }


def test_full_mix_caps_at_max_items():
    rules = {
        "first_time": [],
        "portfolio_state": _items("portfolio_state", 4),
        "market_state": _items("market_state", 4),
        "radar_update": _items("radar_update", 1),
        "capability": _items("capability", 2),
        "quiet_state": _items("quiet_state", 10),
    }
    result = ranker.rank(rules)
    assert len(result) == ranker.MAX_ITEMS


def test_category_order_respected():
    result = ranker.rank(_full_rules())
    categories = [s.category for s in result]
    assert categories == (
        ["portfolio_state"] * 2
        + ["market_state"] * 2
        + ["radar_update"]
        + ["capability"] * 2
        + ["quiet_state"] * 5
    )


def test_within_category_ordered_by_magnitude_desc():
    rules = {
        "first_time": [],
        "portfolio_state": [
            Shortcut.create(text="p-low", category="portfolio_state", magnitude=0.3),
            Shortcut.create(text="p-high", category="portfolio_state", magnitude=0.9),
        ],
        "market_state": [
            Shortcut.create(text="m-low", category="market_state", magnitude=0.1),
            Shortcut.create(text="m-high", category="market_state", magnitude=0.5),
        ],
        "radar_update": [],
        "capability": [],
        "quiet_state": [],
    }
    result = ranker.rank(rules)
    assert [s.text for s in result] == ["p-high", "p-low", "m-high", "m-low"]


def test_first_time_overrides_everything():
    rules = _full_rules()
    rules["first_time"] = _items("first_time", 3)
    result = ranker.rank(rules)
    assert [s.category for s in result] == ["first_time"] * 3 + ["quiet_state"] * 5
    assert not any(
        s.category in {"portfolio_state", "market_state", "radar_update", "capability"}
        for s in result
    )
