"""Daily ARQ task for generating user digest snapshots.

The cron runs twice around 9am New York time (13:00 and 14:00 UTC) so DST
doesn't need special scheduling logic. Idempotency is enforced before work
starts by selecting only users missing today's snapshot, and again by the
repository upsert used by ``DigestService.generate_for_user``.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import structlog

from app.database import async_session
from app.repositories.user_profile import UserProfileRepository
from app.services.digest.context import ET
from app.services.digest.service import DigestService

logger = structlog.get_logger(__name__)

RECENTLY_ACTIVE_WINDOW = timedelta(days=7)
DIGEST_GENERATION_CONCURRENCY = 10


async def generate_daily_digest(ctx: dict) -> dict:
    """Generate today's digest for recently active users missing one."""
    now = datetime.now(timezone.utc)
    ny_local_date = now.astimezone(ET).date()
    active_since = now - RECENTLY_ACTIVE_WINDOW

    async with async_session() as db:
        user_ids = await UserProfileRepository.list_active_users_without_digest(
            db,
            active_since=active_since,
            ny_local_date=ny_local_date,
        )

    semaphore = asyncio.Semaphore(DIGEST_GENERATION_CONCURRENCY)
    results = await asyncio.gather(
        *(_generate_for_user(ctx, user_id, semaphore) for user_id in user_ids),
        return_exceptions=True,
    )
    failures = [result for result in results if isinstance(result, Exception)]
    generated = len(results) - len(failures)

    logger.info(
        "daily_digest_generation_complete",
        candidate_count=len(user_ids),
        generated_count=generated,
        failed_count=len(failures),
        ny_local_date=ny_local_date.isoformat(),
    )
    if failures:
        raise ExceptionGroup("daily digest generation failed", failures)
    return {
        "status": "ok",
        "candidate_count": len(user_ids),
        "generated_count": generated,
        "failed_count": 0,
    }


async def _generate_for_user(
    ctx: dict,
    user_id: uuid.UUID,
    semaphore: asyncio.Semaphore,
) -> None:
    async with semaphore:
        async with async_session() as db:
            try:
                service = DigestService(
                    db,
                    alpaca=ctx["alpaca"],
                    market_data=ctx.get("market_data"),
                    fmp=ctx.get("fmp"),
                    anthropic=ctx.get("anthropic"),
                )
                await service.generate_for_user(user_id)
                await db.commit()
                logger.debug("daily_digest_user_generated", user_id=str(user_id))
            except Exception:
                await db.rollback()
                logger.exception("daily_digest_user_failed", user_id=str(user_id))
                raise
