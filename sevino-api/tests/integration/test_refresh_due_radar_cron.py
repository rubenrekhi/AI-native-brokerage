"""Integration tests for the hourly `refresh_due_radar` cron.

The cron reads due users (anchor ``<= now``, onboarded) and enqueues one
``generate_radar_batch`` per user via the ARQ pool on ``ctx["redis"]``.

Self-healing (verified by `test_cron_leaves_anchor_unchanged_so_failed_batch_reenqueues`):
the cron never touches ``next_radar_refresh_at`` — only a *successful*
batch advances it (orchestrator's ``try_claim_radar_slot``). So if a batch
fails and ARQ exhausts retries, the anchor stays in the past and the next
hourly tick re-enqueues the user. Recovery needs no manual intervention.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text

from app.tasks.refresh_due_radar import refresh_due_radar
from tests.integration.conftest import _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync, reason="Local Postgres not running"
)


def _patch_async_session(monkeypatch, session) -> None:
    """Make the cron's ``async_session()`` yield the rolling-back test
    session so it observes the flushed-but-uncommitted seed rows. The
    no-op ``__aexit__`` keeps the fixture in charge of teardown."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "app.tasks.refresh_due_radar.async_session", lambda: cm
    )


async def _set_radar_state(
    db_session,
    user_id: uuid.UUID,
    *,
    anchor: datetime | None,
    onboarding_completed: bool,
) -> None:
    await db_session.execute(
        text(
            "UPDATE user_profiles SET next_radar_refresh_at = :anchor, "
            "onboarding_completed = :done WHERE id = :id"
        ),
        {"anchor": anchor, "done": onboarding_completed, "id": user_id},
    )
    await db_session.flush()


async def test_cron_enqueues_due_users_and_skips_others(
    db_session, test_user, make_extra_user, monkeypatch
):
    now = datetime.now(timezone.utc)

    await _set_radar_state(
        db_session, test_user, anchor=now - timedelta(hours=2),
        onboarding_completed=True,
    )
    future = await make_extra_user()
    await _set_radar_state(
        db_session, future, anchor=now + timedelta(days=2),
        onboarding_completed=True,
    )
    not_onboarded = await make_extra_user()
    await _set_radar_state(
        db_session, not_onboarded, anchor=now - timedelta(hours=2),
        onboarding_completed=False,
    )

    _patch_async_session(monkeypatch, db_session)
    arq = AsyncMock()
    result = await refresh_due_radar({"redis": arq})

    assert result == {"enqueued": 1}
    arq.enqueue_job.assert_awaited_once()
    call = arq.enqueue_job.await_args
    assert call.args[0] == "generate_radar_batch"
    assert call.args[1] == str(test_user)
    today = datetime.now(timezone.utc).date().isoformat()
    assert call.kwargs["_job_id"] == f"radar_batch:{test_user}:{today}"


async def test_cron_enqueues_nothing_when_no_users_due(
    db_session, test_user, monkeypatch
):
    now = datetime.now(timezone.utc)
    await _set_radar_state(
        db_session, test_user, anchor=now + timedelta(days=1),
        onboarding_completed=True,
    )

    _patch_async_session(monkeypatch, db_session)
    arq = AsyncMock()
    result = await refresh_due_radar({"redis": arq})

    assert result == {"enqueued": 0}
    arq.enqueue_job.assert_not_awaited()


async def test_cron_leaves_anchor_unchanged_so_failed_batch_reenqueues(
    db_session, test_user, monkeypatch
):
    """Self-healing: the cron only *enqueues* — it never advances the
    anchor. A batch that exhausts ARQ retries leaves the anchor in the
    past, so the user is still due on the next tick and gets re-enqueued.
    """
    now = datetime.now(timezone.utc)
    past_anchor = now - timedelta(hours=3)
    await _set_radar_state(
        db_session, test_user, anchor=past_anchor, onboarding_completed=True
    )

    _patch_async_session(monkeypatch, db_session)
    arq = AsyncMock()
    await refresh_due_radar({"redis": arq})

    persisted = (
        await db_session.execute(
            text(
                "SELECT next_radar_refresh_at FROM user_profiles WHERE id = :id"
            ),
            {"id": test_user},
        )
    ).scalar_one()
    assert persisted == past_anchor

    # Still in the past → the next cron run finds the user due again.
    second = await refresh_due_radar({"redis": arq})
    assert second == {"enqueued": 1}
