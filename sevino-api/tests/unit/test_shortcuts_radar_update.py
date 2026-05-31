"""Unit tests for the `radar_update` shortcut rule.

These cover the fire/silent behavior against a mocked existence check. The
actual ``radar_items`` filter (unstarred + unexpired + AI-generated) is
exercised end-to-end against real rows in
``tests/integration/test_shortcuts_radar_update.py``.
"""

import uuid
from datetime import date
from unittest.mock import AsyncMock, Mock

from app.services.shortcuts.context import ShortcutContext
from app.services.shortcuts.rules import radar_update
from app.services.shortcuts.time_buckets import TimeBucket

USER = uuid.UUID("66666666-6666-6666-6666-666666666666")


def _ctx() -> ShortcutContext:
    return ShortcutContext(
        user_id=USER,
        bucket=TimeBucket.MARKET_HOURS,
        day=date(2026, 5, 30),
        account_age_days=100,
        conversation_count=100,
    )


def _db_with_unseen(has_unseen: bool) -> AsyncMock:
    db = AsyncMock()
    db.execute.return_value = Mock(scalar_one=Mock(return_value=has_unseen))
    return db


async def test_fires_when_unseen_items_exist():
    out = await radar_update.evaluate(_ctx(), _db_with_unseen(True))
    assert len(out) == 1
    assert out[0].text == "What's on Radar today?"
    assert out[0].category == "radar_update"


async def test_silent_when_no_items():
    out = await radar_update.evaluate(_ctx(), _db_with_unseen(False))
    assert out == []
