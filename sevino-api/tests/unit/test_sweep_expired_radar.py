"""Unit tests for the daily radar sweep task."""

from unittest.mock import AsyncMock, MagicMock

from app.tasks.sweep_expired_radar import sweep_expired_radar_items


def _patch_session(monkeypatch) -> AsyncMock:
    """Patch async_session so the task gets a mock session as the context value.

    Returns the session mock so the test can assert calls on it.
    """
    session = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "app.tasks.sweep_expired_radar.async_session", lambda: cm
    )
    return session


async def test_sweep_calls_repo_commits_and_returns_count(monkeypatch):
    session = _patch_session(monkeypatch)

    async def fake_delete_expired(db):
        assert db is session
        return 7

    monkeypatch.setattr(
        "app.tasks.sweep_expired_radar.RadarItemRepository.delete_expired_ai_items",
        fake_delete_expired,
    )

    result = await sweep_expired_radar_items({})

    assert result == {"status": "ok", "deleted_count": 7}
    session.commit.assert_awaited_once()


async def test_sweep_returns_zero_when_nothing_to_delete(monkeypatch):
    session = _patch_session(monkeypatch)

    async def fake_delete_expired(db):
        return 0

    monkeypatch.setattr(
        "app.tasks.sweep_expired_radar.RadarItemRepository.delete_expired_ai_items",
        fake_delete_expired,
    )

    result = await sweep_expired_radar_items({})

    assert result == {"status": "ok", "deleted_count": 0}
    session.commit.assert_awaited_once()
