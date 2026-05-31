"""Deterministic job-id dedup for the `refresh_due_radar` cron.

Two cron ticks in the same UTC day produce the *same* ``_job_id`` per
user (``radar_batch:<user_id>:<YYYY-MM-DD>``). ARQ treats a re-enqueue of
an existing job id as a no-op, so a user gets at most one batch per day no
matter how often the cron (or the onboarding hook) fires. The fake ARQ
pool below mirrors that contract: a repeat job id returns ``None`` and
creates no new job.
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


class _DedupArq:
    """Stand-in for ArqRedis that models enqueue-by-job-id dedup.

    A job id already seen returns ``None`` (no new job) — exactly what the
    real pool does, so ``created`` counts the jobs that actually landed on
    the queue across every cron run.
    """

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self.created: list[tuple[str, str]] = []

    async def enqueue_job(self, function, *args, _job_id=None, **kwargs):
        if _job_id in self._seen:
            return None
        self._seen.add(_job_id)
        self.created.append((function, _job_id))
        return object()


def _patch_async_session(monkeypatch, session) -> None:
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "app.tasks.refresh_due_radar.async_session", lambda: cm
    )


async def test_cron_run_twice_enqueues_each_user_once(
    db_session, test_user, monkeypatch
):
    now = datetime.now(timezone.utc)
    await db_session.execute(
        text(
            "UPDATE user_profiles SET next_radar_refresh_at = :anchor, "
            "onboarding_completed = true WHERE id = :id"
        ),
        {"anchor": now - timedelta(hours=1), "id": test_user},
    )
    await db_session.flush()

    _patch_async_session(monkeypatch, db_session)
    arq = _DedupArq()

    await refresh_due_radar({"redis": arq})
    await refresh_due_radar({"redis": arq})

    # The second run re-enqueued the same job id; ARQ collapsed it.
    assert len(arq.created) == 1
    function_name, job_id = arq.created[0]
    assert function_name == "generate_radar_batch"
    today = now.date().isoformat()
    assert job_id == f"radar_batch:{test_user}:{today}"
