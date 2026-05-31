"""Daily retention sweep for digest snapshots."""

from datetime import datetime, timedelta, timezone

import structlog

from app.database import async_session
from app.repositories.digest import DigestRepository
from app.services.digest.context import ET

logger = structlog.get_logger(__name__)

DIGEST_RETENTION_WINDOW = timedelta(days=7)


async def sweep_digest_snapshots(ctx: dict) -> dict:
    """Delete digest snapshots older than the 7-day retention window."""
    cutoff = (
        datetime.now(timezone.utc).astimezone(ET) - DIGEST_RETENTION_WINDOW
    ).date()
    async with async_session() as db:
        deleted = await DigestRepository.delete_older_than(db, cutoff)
        await db.commit()

    logger.info(
        "digest_snapshot_sweep_complete",
        deleted_count=deleted,
        cutoff_ny_local_date=cutoff.isoformat(),
    )
    return {"status": "ok", "deleted_count": deleted}
