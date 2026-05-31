"""Hourly cron that enqueues radar batches for past-due users.

Sweeps ``user_profiles`` for anchors at or before now (set on onboarding
completion, then advanced 7d by the orchestrator after each batch) and
enqueues ``generate_radar_batch`` for each. The deterministic ``_job_id``
collapses the same user to one job per UTC day, so two cron ticks within
the same day never double-fire.

Self-healing: the anchor only advances on a *successful* batch, so a job
that exhausts ARQ's retries leaves the anchor in the past and the next
hourly tick re-enqueues it — no manual intervention needed.
"""

from datetime import datetime, timezone

import structlog

from app.database import async_session
from app.repositories.user_profile import UserProfileRepository

logger = structlog.get_logger(__name__)


async def refresh_due_radar(ctx: dict) -> dict:
    now = datetime.now(timezone.utc)
    async with async_session() as db:
        due = await UserProfileRepository.list_users_due_for_refresh(db, now)

    # ctx["redis"] is the ArqRedis pool the worker started with — it
    # subclasses redis.asyncio.Redis and exposes enqueue_job.
    arq = ctx["redis"]
    for user_id in due:
        await arq.enqueue_job(
            "generate_radar_batch",
            str(user_id),
            _job_id=f"radar_batch:{user_id}:{now.date().isoformat()}",
        )
        logger.debug("radar_refresh_due_enqueued", user_id=str(user_id))

    logger.info(
        "radar_refresh_due_complete",
        enqueued=len(due),
        user_ids=[str(u) for u in due],
    )
    return {"enqueued": len(due)}
