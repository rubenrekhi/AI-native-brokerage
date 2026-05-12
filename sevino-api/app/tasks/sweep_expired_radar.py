"""Daily sweep of expired AI-generated radar items.

The list endpoint already filters expired rows out at read time, so this
task is pure DB hygiene — it releases storage and keeps the
`radar_items` table small. Scheduled for 03:00 UTC (low-traffic window;
sync_assets runs at 10:00 UTC).
"""

import structlog

from app.database import async_session
from app.repositories.radar_item import RadarItemRepository

logger = structlog.get_logger(__name__)


async def sweep_expired_radar_items(ctx: dict) -> dict:
    """Delete expired non-favorited AI rows. Returns count for telemetry."""
    async with async_session() as session:
        deleted = await RadarItemRepository.delete_expired_ai_items(session)
        await session.commit()
    logger.info("radar_sweep_complete", deleted_count=deleted)
    return {"status": "ok", "deleted_count": deleted}
