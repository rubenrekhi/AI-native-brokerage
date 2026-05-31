"""ARQ wrapper for the AI Radar batch generator.

Pulls per-process resources (Alpaca client, cache Redis, FMP client) off
the worker's ctx — they were initialized in ``app.worker.startup`` — and
constructs a fresh Anthropic client per job (cheap, stateless, lets each
job get a clean HTTP/2 connection rather than sharing one across runs).

Errors from the orchestrator surface as ``RadarJobError`` and propagate to
ARQ's retry policy. The deterministic ``_job_id`` callers pass to
``enqueue_job`` ("radar_batch:<user_id>:<YYYY-MM-DD>") dedups simultaneous
firings without any locking here.
"""

from uuid import UUID

import structlog

from app.database import async_session
from app.services.radar_job import RadarJobError
from app.services.radar_job.orchestrator import generate_radar_batch as run_orchestrator
from app.ai.anthropic_client import create_anthropic_client

logger = structlog.get_logger(__name__)

# Error codes that are deterministic given current DB/Alpaca state — retrying
# the ARQ job won't change the outcome. Treat them as successful no-ops so we
# don't burn the default max_tries=5 budget on guaranteed failures.
# - ``already_rotated``: another worker won the FOR-UPDATE race on this user's
#   slot; the batch landed elsewhere, nothing more to do.
# - ``pool_too_small``: the candidate sourcer produced <10 items, meaning the
#   gated universe is too sparse for this user right now (e.g. their held
#   sectors plus exclusions left nothing). The next scheduled refresh will
#   try again with fresh data.
_DETERMINISTIC_NOOP_CODES = frozenset({"already_rotated", "pool_too_small"})


async def generate_radar_batch(ctx: dict, user_id: str) -> dict:
    """Run one radar batch for the user. ARQ task entrypoint.

    Returns a small summary dict (logged by ARQ as the job result). Raises
    ``RadarJobError`` or any unexpected exception — ARQ's default retry
    policy handles transient failures and ``next_radar_refresh_at`` only
    advances on success, so a fully exhausted job is picked up again by
    the next hourly refresh cron (T6) without manual intervention.
    """
    alpaca = ctx["alpaca"]
    cache_redis = ctx["cache_redis"]
    fmp = ctx.get("fmp")
    if fmp is None:
        # FMP client only initializes when fmp_api_key is set; without it
        # the candidate sourcer's event bucket can't run. Surface as a
        # config error rather than crash on a None deref deep in the stack.
        logger.error("radar_task_no_fmp_client", user_id=user_id)
        raise RuntimeError("fmp client not configured on worker")

    anthropic = create_anthropic_client()
    async with async_session() as db:
        try:
            result = await run_orchestrator(
                UUID(user_id),
                db,
                alpaca=alpaca,
                fmp=fmp,
                redis=cache_redis,
                anthropic=anthropic,
            )
            await db.commit()
        except RadarJobError as exc:
            await db.rollback()
            if exc.code in _DETERMINISTIC_NOOP_CODES:
                logger.info(
                    "radar_task_skipped",
                    user_id=user_id,
                    code=exc.code,
                )
                return {"user_id": user_id, "skipped": exc.code}
            raise
        except Exception:
            await db.rollback()
            raise

    logger.info(
        "radar_task_complete",
        user_id=user_id,
        picks_count=result.picks_count,
        next_refresh_at=result.next_refresh_at.isoformat(),
    )
    return {
        "user_id": user_id,
        "picks_count": result.picks_count,
        "next_refresh_at": result.next_refresh_at.isoformat(),
    }
